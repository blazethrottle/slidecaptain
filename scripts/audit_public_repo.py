"""Audit tracked files before publishing this repository.

알려진 한계:

- 바이너리 파일 안에 든 키는 기본 검사가 파일 바이트를 직접 읽으므로 잡지만,
  ``--history`` 는 ``git log -p`` 출력만 보고 바이너리 변경은 그 출력에
  "Binary files differ" 로만 나오므로 놓친다. 삭제된 바이너리 안에 있던 키는
  이력 검사로 드러나지 않는다.
- ``sk-`` 뒤에 영숫자와 밑줄, 붙임표가 20자 이상 이어지면 키로 본다. 그래서
  ``sk-`` 뒤에 16진수 해시가 오는 문자열도 잡힌다. 실제 키와 구분할 수 없으므로
  이 오탐은 허용한다.
- 내용 검사는 작업트리 바이트를 읽는다. HEAD 에 커밋된 키를 작업트리에서만
  지우면 기본 검사는 통과하고 ``--history`` 가 잡는다.
- Office 파일 검사는 확장자 기반이다. 확장자 없이 zip 시그니처(``PK``)만 가진
  오피스 파일(잘못 저장된 pptx 등)은 잡지 못한다.
- 식별 문자열 검사는 사용자 계정이 든 경로(``C:\\Users\\<계정>``, ``/Users/<계정>``)만
  본다. 사람 이름이나 회사 이름 자체는 추측으로 잡지 않는다. 자리표시자(``<...>``,
  ``%...%``, ``$...``)와 공용 계정(Public, Default, Shared 등)은 통과시킨다.
- ``--history`` 의 식별 문자열 검사는 ``_IDENTITY_EXEMPT_COMMITS`` 의 커밋을 건너뛴다.
  이 저장소의 과거 계정명 유입 2건은 사용자 결정(2026-09-07)으로 이력에 남기기로 했고,
  그 결정이 새 유입까지 덮지 않도록 예외는 커밋 해시로만 한정한다. 이력을 재작성하면
  해시가 바뀌므로 이 목록도 함께 갱신해야 한다.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str


class GitAuditError(RuntimeError):
    pass


_TOOL_DIRECTORIES = frozenset(
    {".venv", "node_modules", ".superpowers", ".worktrees", "__pycache__"}
)
_ROOT_DATA_DIRECTORIES = frozenset({"projects", "uploads", "exports", "snapshots", "dist"})
# 빌드 산출 폴더는 정확한 2단계 접두어로만 비교한다. 새 하위 패키지가 자기 빌드 산출 폴더를 갖게 되면
# (예: backend/dist) 여기에 그 조합을 추가해야 잡힌다 (2026-09-03 리뷰 발견 5)
_NESTED_FORBIDDEN_DIRECTORIES = frozenset({("frontend", "dist")})
_REVIEW_DIRECTORY = ("docs", "reviews")
_OFFICE_EXTENSIONS = frozenset({".pptx", ".docx", ".pdf", ".xls", ".xlsx"})
_PRIVATE_KEY_EXTENSIONS = frozenset({".key", ".pem", ".ppk", ".p12", ".pfx", ".der"})
_SYNTHETIC_FIXTURE = ("backend", "tests", "fixtures", "synthetic")
_PILOT_DIRECTORY = ("docs", "pilot")
_PILOT_NOTE = re.compile(r"\d{4}-\d{2}-\d{2}-파일럿-관찰지\.md\Z")
_COMMIT_HEADER = re.compile(rb"(?m)^([0-9a-f]{40})\0\n\n")
_SECRET_NAME_TOKENS = frozenset({"credential", "credentials", "secret", "secrets"})
_SAMPLE_NAME_TOKENS = frozenset({"example", "sample", "template"})
_NAME_TOKEN_SEPARATORS = re.compile(r"[-_.]+")


def _bytes_pattern(*parts: bytes, flags: int = 0) -> re.Pattern[bytes]:
    return re.compile(b"".join(parts), flags)


_KEY_BODY = b"[A-Za-z0-9_-]{20,}"
_SECRET_PATTERNS = (
    _bytes_pattern(b"\\b", b"sk", b"-", b"(?:proj-|svcacct-|ant-[a-z0-9]+-)?", _KEY_BODY),
    _bytes_pattern(b"\\b", b"gh", b"[pousr]", b"_", _KEY_BODY),
    _bytes_pattern(b"\\b", b"github", b"_pat", b"_", _KEY_BODY),
    _bytes_pattern(b"\\b", b"AKIA", b"[A-Z0-9]{16}\\b", flags=re.IGNORECASE),
    _bytes_pattern(b"-----BEGIN ", b"(?:[A-Z ]+ )?", b"PRIVATE KEY-----", flags=re.IGNORECASE),
)
_ENVIRONMENT_ASSIGNMENT = _bytes_pattern(
    b"\\b(?:",
    b"OPENAI",
    b"_API_KEY|",
    b"ANTHROPIC",
    b"_API_KEY|",
    b"GITHUB",
    b"_TOKEN|",
    b"AWS",
    b"_ACCESS_KEY_ID)",
    b"[\"']?\\s*[=:]\\s*[\"']?(",
    _KEY_BODY,
    b")",
    # 이름은 대소문자를 가리지 않는다: pydantic Settings 관례(anthropic_api_key)로 선언된 실제 값도 잡는다.
    # 오탐(조회식, CI 문법, 자리표시자)은 값 형태 제한과 _PLACEHOLDER_VALUE 가 막는다 (2026-09-03 리뷰 반영)
    flags=re.IGNORECASE,
)
_PLACEHOLDER_VALUE = re.compile(rb"your|example|placeholder|changeme|dummy", re.IGNORECASE)

# 두 패턴은 조각을 이어 붙여 만든다. 소스에 경로 리터럴을 그대로 두면 이 파일 자신이
# 검사에 걸린다 (2026-09-07 실측. 비밀 패턴이 ``_bytes_pattern`` 을 쓰는 것과 같은 이유).
# Windows 는 드라이브 접두어가 있어 대소문자를 가리지 않아도 URL 과 헷갈리지 않는다.
# POSIX 는 대문자로 시작하는 사용자 폴더만 본다. 소문자까지 보면 REST 경로의 사용자 목록
# 엔드포인트를 계정 경로로 오인한다 (2026-09-07 설계 판단)
_WINDOWS_ACCOUNT_PATH = _bytes_pattern(
    rb"[a-z]:", rb"\\", rb"users", rb"\\", rb"([^\\\r\n\"']{1,64})", flags=re.IGNORECASE
)
_POSIX_ACCOUNT_PATH = _bytes_pattern(rb"/", rb"Users", rb"/", rb"([^/\r\n\"'\s]{1,64})")
_SHARED_ACCOUNT_SEGMENTS = frozenset(
    {b"public", b"default", b"default user", b"all users", b"shared"}
)
_PLACEHOLDER_PREFIXES = (b"<", b"%", b"$", b"~", b"{")
# 이 저장소의 과거 계정명이 diff 본문에 있는 커밋 4건(문맥 줄 포함 실측). 3e47fbb 가 들여왔고
# 57572e3 과 077f329 가 같은 줄을 문맥으로 통과시켰으며 9d20ba9 가 익명화했다.
# `git log -S` 는 추가와 삭제만 세므로 문맥 줄에 남은 2건을 놓친다 (2026-09-07 실측). 사용자 결정(2026-09-07)으로 이력은 재작성하지 않는다
_IDENTITY_EXEMPT_COMMITS = frozenset(
    {
        "3e47fbbbf3aca85c0f7b647f15f1c2153573aa83",
        "57572e3615213bee28d727206ca22ca48e315281",
        "077f32991717108dfb5e81704df592f12f0cfe23",
        "9d20ba90610aedc1d5bf85d148f654dc1f34c80a",
    }
)


def _run_git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise GitAuditError(
            "git 실행 파일을 찾지 못했습니다. Git 을 설치하고 PATH 에 추가한 뒤 다시 실행하세요."
        ) from error
    if result.returncode != 0:
        raise GitAuditError("Git 저장소를 검사하지 못했습니다.")
    return result.stdout


def _repository_root(root: Path) -> Path:
    output = _run_git(root, "rev-parse", "--show-toplevel")
    return Path(output.decode("utf-8", "surrogateescape").strip())


def _normalise_path(path: str) -> str:
    return path.replace("\\", "/")


def _nul_paths(output: bytes) -> list[str]:
    return [
        _normalise_path(value.decode("utf-8", "surrogateescape"))
        for value in output.split(b"\0")
        if value
    ]


def tracked_paths(root: Path) -> list[str]:
    """Return only the tracked paths in a Git working tree."""
    return _nul_paths(_run_git(root, "ls-files", "-z"))


def historical_paths(root: Path) -> list[str]:
    """Return paths that appear in every reachable commit."""
    return _nul_paths(_run_git(root, "log", "--all", "--name-only", "-z", "--pretty=format:"))


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.split("/") if part)


def _is_forbidden_directory(lowered_parts: tuple[str, ...]) -> bool:
    directories = lowered_parts[:-1]
    if any(part in _TOOL_DIRECTORIES for part in directories):
        return True
    if directories and directories[0] in _ROOT_DATA_DIRECTORIES:
        return True
    return directories[:2] in _NESTED_FORBIDDEN_DIRECTORIES


def _is_review_record(lowered_parts: tuple[str, ...]) -> bool:
    return len(lowered_parts) > 2 and lowered_parts[:2] == _REVIEW_DIRECTORY


def _is_synthetic_xlsx(parts: tuple[str, ...]) -> bool:
    return (
        tuple(part.lower() for part in parts[:4]) == _SYNTHETIC_FIXTURE
        and Path(parts[-1]).suffix.lower() == ".xlsx"
    )


def _is_allowed_pilot_note(parts: tuple[str, ...]) -> bool:
    return (
        len(parts) == 3
        and tuple(part.lower() for part in parts[:2]) == _PILOT_DIRECTORY
        and _PILOT_NOTE.fullmatch(parts[-1]) is not None
    )


def _name_tokens(name: str) -> set[str]:
    """파일명을 붙임표와 밑줄과 점으로 나눈 조각들. 앞의 점은 떼어 ``.secrets`` 도 본다."""

    return {token for token in _NAME_TOKEN_SEPARATORS.split(name.strip(".")) if token}


def _is_secret_filename(name: str) -> bool:
    lowered = name.lower()
    if lowered == ".env":
        return True
    if lowered.startswith(".env.") and lowered != ".env.example":
        return True
    if Path(lowered).suffix in _PRIVATE_KEY_EXTENSIONS:
        return True
    tokens = _name_tokens(lowered)
    if tokens & _SAMPLE_NAME_TOKENS:
        return False
    return bool(tokens & _SECRET_NAME_TOKENS)


def _is_placeholder_account(segment: bytes) -> bool:
    stripped = segment.strip()
    if not stripped:
        return True
    if stripped[:1] in _PLACEHOLDER_PREFIXES:
        return True
    return stripped.lower() in _SHARED_ACCOUNT_SEGMENTS


def _contains_identity(content: bytes) -> bool:
    for pattern in (_WINDOWS_ACCOUNT_PATH, _POSIX_ACCOUNT_PATH):
        for match in pattern.finditer(content):
            if not _is_placeholder_account(match.group(1)):
                return True
    return False


def audit_paths(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        parts = _path_parts(path)
        lowered_parts = tuple(part.lower() for part in parts)
        if _is_forbidden_directory(lowered_parts):
            findings.append(Finding("금지 디렉터리", path))
        if _is_review_record(lowered_parts):
            findings.append(Finding("리뷰 기록", path))
        if lowered_parts[:2] == _PILOT_DIRECTORY and not _is_allowed_pilot_note(parts):
            findings.append(Finding("파일럿 원본", path))
        if Path(path).suffix.lower() in _OFFICE_EXTENSIONS and not _is_synthetic_xlsx(parts):
            findings.append(Finding("Office 파일", path))
        if parts and _is_secret_filename(parts[-1]):
            findings.append(Finding("비밀 파일", path))
    return findings


def _contains_secret(content: bytes) -> bool:
    if any(pattern.search(content) is not None for pattern in _SECRET_PATTERNS):
        return True
    return any(
        _PLACEHOLDER_VALUE.search(match.group(1)) is None
        for match in _ENVIRONMENT_ASSIGNMENT.finditer(content)
    )


def _working_file(root: Path, relative_path: str) -> Path | None:
    parts = _path_parts(relative_path)
    if not parts or any(part in {".", ".."} for part in parts):
        return None
    candidate = root
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            return None
    return candidate


def audit_contents(root: Path, paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in paths:
        candidate = _working_file(root, relative_path)
        if candidate is None or not candidate.is_file():
            continue
        try:
            content = candidate.read_bytes()
        except OSError:
            findings.append(Finding("파일 읽기 오류", relative_path))
            continue
        if _contains_secret(content):
            findings.append(Finding("비밀 패턴", relative_path))
        if _contains_identity(content):
            findings.append(Finding("식별 문자열", relative_path))
    return findings


def _unique_findings(findings: list[Finding]) -> list[Finding]:
    return list(dict.fromkeys(findings))


def _historical_content_findings(root: Path) -> list[Finding]:
    paths_by_commit = _historical_paths_by_commit(root)
    findings: list[Finding] = []
    diff_output = _run_git(root, "log", "--all", "--format=%H%x00", "-p", "--no-ext-diff")
    headers = list(_COMMIT_HEADER.finditer(diff_output))
    for index, header in enumerate(headers):
        commit = header.group(1).decode("ascii")
        next_start = headers[index + 1].start() if index + 1 < len(headers) else len(diff_output)
        diff = diff_output[header.end() : next_start]
        paths = paths_by_commit.get(commit, [])
        checks = [("비밀 패턴(이력)", _contains_secret)]
        if commit not in _IDENTITY_EXEMPT_COMMITS:
            checks.append(("식별 문자열(이력)", _contains_identity))
        patches = [patch for patch in diff.split(b"\ndiff --git ") if patch]
        if len(paths) != len(patches):
            for rule, matches in checks:
                if matches(diff):
                    findings.extend(Finding(rule, path) for path in paths)
            continue
        for path, patch in zip(paths, patches, strict=True):
            for rule, matches in checks:
                if matches(patch):
                    findings.append(Finding(rule, path))
    return findings


def _historical_paths_by_commit(root: Path) -> dict[str, list[str]]:
    output = _run_git(root, "log", "--all", "--format=%H%x00", "--name-only", "-z")
    chunks = output.split(b"\0")
    paths_by_commit: dict[str, list[str]] = {}
    current_commit: str | None = None
    remove_format_newline = False
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        if remove_format_newline:
            if chunk.startswith(b"\n"):
                chunk = chunk[1:]
            remove_format_newline = False
        if (
            len(chunk) == 40
            and all(character in b"0123456789abcdef" for character in chunk)
            and index + 1 < len(chunks)
            and chunks[index + 1] == b""
        ):
            current_commit = chunk.decode("ascii")
            paths_by_commit.setdefault(current_commit, [])
            remove_format_newline = True
            index += 2
            continue
        if current_commit is not None and chunk:
            path = _normalise_path(chunk.decode("utf-8", "surrogateescape"))
            paths_by_commit[current_commit].append(path)
        index += 1
    return paths_by_commit


def audit_repository(root: Path, include_history: bool = False) -> list[Finding]:
    root = _repository_root(root)
    current_paths = tracked_paths(root)
    findings = audit_paths(current_paths)
    findings.extend(audit_contents(root, current_paths))
    if include_history:
        findings.extend(audit_paths(historical_paths(root)))
        findings.extend(_historical_content_findings(root))
    return _unique_findings(findings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공개 저장소의 추적 파일을 검사합니다.")
    parser.add_argument("--root", type=Path, help="검사할 Git 저장소 경로")
    parser.add_argument("--history", action="store_true", help="도달 가능한 커밋 이력도 검사")
    arguments = parser.parse_args(argv)
    root = arguments.root if arguments.root is not None else Path.cwd()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        findings = audit_repository(root, include_history=arguments.history)
    except GitAuditError as error:
        print(str(error) or "Git 저장소를 검사하지 못했습니다.", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{finding.rule}: {finding.path}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
