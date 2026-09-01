"""Audit tracked files before publishing this repository."""

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


_FORBIDDEN_DIRECTORIES = frozenset(
    {
        ".venv",
        "node_modules",
        "dist",
        ".superpowers",
        ".worktrees",
        "projects",
        "uploads",
        "exports",
        "snapshots",
    }
)
_OFFICE_EXTENSIONS = frozenset({".pptx", ".docx", ".pdf", ".xls", ".xlsx"})
_PRIVATE_KEY_EXTENSIONS = frozenset({".key", ".pem", ".ppk", ".p12", ".pfx", ".der"})
_SYNTHETIC_FIXTURE = ("backend", "tests", "fixtures", "synthetic")
_PILOT_DIRECTORY = ("docs", "pilot")
_PILOT_NOTE = re.compile(r"\d{4}-\d{2}-\d{2}-파일럿-관찰지\.md\Z")


def _bytes_pattern(*parts: bytes) -> re.Pattern[bytes]:
    return re.compile(b"".join(parts), re.IGNORECASE)


_SECRET_PATTERNS = (
    _bytes_pattern(b"\\b", b"sk", b"-", b"ant", b"-", b"[A-Za-z0-9_-]{20,}"),
    _bytes_pattern(b"\\b", b"sk", b"-", b"[A-Za-z0-9]{20,}"),
    _bytes_pattern(b"\\b", b"ghp", b"_", b"[A-Za-z0-9]{20,}"),
    _bytes_pattern(b"\\b", b"github", b"_pat", b"_", b"[A-Za-z0-9_]{20,}"),
    _bytes_pattern(b"\\b", b"AKIA", b"[A-Z0-9]{16}\\b"),
    _bytes_pattern(b"-----BEGIN ", b"[A-Z ]+", b"PRIVATE KEY-----"),
    _bytes_pattern(
        b"\\b(?:",
        b"OPENAI",
        b"_API_KEY|",
        b"ANTHROPIC",
        b"_API_KEY|",
        b"GITHUB",
        b"_TOKEN|",
        b"AWS",
        b"_ACCESS_KEY_ID)\\s*=\\s*[^\\s]{16,}",
    ),
)


def _run_git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitAuditError
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


def historical_diff(root: Path) -> bytes:
    """Return text diffs for every reachable commit without printing them."""
    return _run_git(root, "log", "--all", "-p", "--format=", "--no-ext-diff")


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in path.split("/") if part)


def _is_synthetic_fixture(parts: tuple[str, ...]) -> bool:
    return tuple(part.lower() for part in parts[:4]) == _SYNTHETIC_FIXTURE


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
        if any(part in _FORBIDDEN_DIRECTORIES for part in lowered_parts):
            findings.append(Finding("금지 디렉터리", path))
        if lowered_parts[:2] == _PILOT_DIRECTORY and not _is_allowed_pilot_note(parts):
            findings.append(Finding("파일럿 원본", path))
        if Path(path).suffix.lower() in _OFFICE_EXTENSIONS and not _is_synthetic_fixture(parts):
            findings.append(Finding("Office 파일", path))
        if parts and _is_secret_filename(parts[-1]):
            findings.append(Finding("비밀 파일", path))
    return findings


def _contains_secret(content: bytes) -> bool:
    return any(pattern.search(content) is not None for pattern in _SECRET_PATTERNS)


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


def audit_repository(root: Path, include_history: bool = False) -> list[Finding]:
    root = _repository_root(root)
    current_paths = tracked_paths(root)
    findings = audit_paths(current_paths)
    findings.extend(audit_contents(root, current_paths))
    if include_history:
        findings.extend(audit_paths(historical_paths(root)))
        if _contains_secret(historical_diff(root)):
            findings.append(Finding("비밀 패턴(이력)", ".git/history-diff"))
    return _unique_findings(findings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공개 저장소의 추적 파일을 검사합니다.")
    parser.add_argument("--root", type=Path, help="검사할 Git 저장소 경로")
    parser.add_argument("--history", action="store_true", help="도달 가능한 커밋 이력도 검사")
    arguments = parser.parse_args(argv)
    root = arguments.root if arguments.root is not None else Path.cwd()
    try:
        findings = audit_repository(root, include_history=arguments.history)
    except GitAuditError:
        print("Git 저장소를 검사하지 못했습니다.", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{finding.rule}: {finding.path}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
