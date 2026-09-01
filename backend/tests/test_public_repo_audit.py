import os
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPOSITORY_ROOT / "scripts" / "audit_public_repo.py"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "audit@example.invalid")
    _git(root, "config", "user.name", "Public Audit Test")
    return root


def _write(root: Path, relative_path: str, content: str = "safe\n") -> Path:
    path = root.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _track(root: Path, *relative_paths: str) -> None:
    _git(root, "add", "--", *relative_paths)


def _commit(root: Path, message: str) -> None:
    _git(root, "commit", "-m", message)


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def _fake_key() -> str:
    return "sk" + "-" + ("a" * 48)


def test_allows_safe_tracked_python_and_markdown_files(tmp_path):
    root = _repository(tmp_path)
    _write(root, "app.py", "print('safe')\n")
    _write(root, "README.md", "# Safe\n")
    _track(root, "app.py", "README.md")

    result = _run(root)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_ignores_untracked_ignored_xlsx_file(tmp_path):
    root = _repository(tmp_path)
    _write(root, ".gitignore", "ignored.xlsx\n")
    _write(root, "app.py")
    _write(root, "ignored.xlsx")
    _track(root, ".gitignore", "app.py")

    result = _run(root)

    assert result.returncode == 0


def test_rejects_forbidden_directories_office_files_and_pilot_raw_files(tmp_path):
    root = _repository(tmp_path)
    for path in (
        "projects/demo/deck.json",
        "materials/DECK.XLSX",
        "docs/pilot/raw/brief.txt",
        "docs/pilot/raw/data.csv",
    ):
        _write(root, path)
        _track(root, path)

    result = _run(root)

    assert result.returncode == 1
    for path in (
        "projects/demo/deck.json",
        "materials/DECK.XLSX",
        "docs/pilot/raw/brief.txt",
        "docs/pilot/raw/data.csv",
    ):
        assert path in result.stdout


def test_allows_synthetic_xlsx_fixture(tmp_path):
    root = _repository(tmp_path)
    path = "backend/tests/fixtures/synthetic/sample.xlsx"
    _write(root, path)
    _track(root, path)

    result = _run(root)

    assert result.returncode == 0


def test_allows_valid_pilot_note_and_false_positive_path_names(tmp_path):
    root = _repository(tmp_path)
    paths = (
        "docs/pilot/2026-09-02-파일럿-관찰지.md",
        "distribution.md",
        "secretary.ts",
    )
    for path in paths:
        _write(root, path)
    _track(root, *paths)

    result = _run(root)

    assert result.returncode == 0


def test_rejects_key_content_without_disclosing_its_value(tmp_path):
    root = _repository(tmp_path)
    key = _fake_key()
    environment_name = "OPENAI" + "_API_KEY"
    _write(root, "settings.py", f"{environment_name}={key}\n")
    _track(root, "settings.py")

    result = _run(root)

    assert result.returncode == 1
    assert "settings.py" in result.stdout
    assert key not in result.stdout
    assert key not in result.stderr


def test_does_not_follow_external_or_broken_symlinks(tmp_path):
    root = _repository(tmp_path)
    external = tmp_path / "outside.txt"
    external.write_text(_fake_key(), encoding="utf-8")
    try:
        os.symlink(external, root / "link.txt")
        os.symlink(root / "missing.txt", root / "broken.txt")
    except OSError as error:
        pytest.skip(f"This operating system does not permit symlinks: {error}")
    _track(root, "link.txt", "broken.txt")

    result = _run(root)

    assert result.returncode == 0
    assert _fake_key() not in result.stdout
    assert _fake_key() not in result.stderr


def test_history_detects_deleted_forbidden_path_and_key(tmp_path):
    root = _repository(tmp_path)
    key = _fake_key()
    path = "projects/old/settings.py"
    _write(root, path, key)
    _track(root, path)
    _commit(root, "add historical finding")
    (root / "projects" / "old" / "settings.py").unlink()
    _git(root, "add", "-u")
    _commit(root, "delete historical finding")

    current = _run(root)
    history = _run(root, "--history")

    assert current.returncode == 0
    assert history.returncode == 1
    assert key not in history.stdout
    assert key not in history.stderr


def test_non_git_root_is_operational_error(tmp_path):
    root = tmp_path / "not-a-repository"
    root.mkdir()

    result = _run(root)

    assert result.returncode == 2
    assert "Git" in result.stderr
