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


def _is_secret_filename(name: str) -> bool:
    lowered = name.lower()
    if lowered == ".env":
        return True
    if lowered.startswith(".env.") and lowered != ".env.example":
        return True
    if Path(lowered).suffix in _PRIVATE_KEY_EXTENSIONS:
        return True
    stem = lowered.split(".", 1)[0]
    return stem in {"credential", "credentials", "secret", "secrets"}


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
    return findings


def _unique_findings(findings: list[Finding]) -> list[Finding]:
    return list(dict.fromkeys(findings))


def _historical_secret_findings(root: Path) -> list[Finding]:
    paths_by_commit = _historical_paths_by_commit(root)
    findings: list[Finding] = []
    diff_output = _run_git(root, "log", "--all", "--format=%H%x00", "-p", "--no-ext-diff")
    headers = list(_COMMIT_HEADER.finditer(diff_output))
    for index, header in enumerate(headers):
        commit = header.group(1).decode("ascii")
        next_start = headers[index + 1].start() if index + 1 < len(headers) else len(diff_output)
        diff = diff_output[header.end() : next_start]
        paths = paths_by_commit.get(commit, [])
        patches = [patch for patch in diff.split(b"\ndiff --git ") if patch]
        if len(paths) != len(patches):
            if _contains_secret(diff):
                findings.extend(Finding("비밀 패턴(이력)", path) for path in paths)
            continue
        for path, patch in zip(paths, patches, strict=True):
            if _contains_secret(patch):
                findings.append(Finding("비밀 패턴(이력)", path))
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
        findings.extend(_historical_secret_findings(root))
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
