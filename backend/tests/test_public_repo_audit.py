import importlib.util
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


def _run(
    root: Path, *args: str, environment_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment.update(environment_overrides or {})
    return subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def _fake_key() -> str:
    return "sk" + "-" + ("a" * 48)


def _key_body() -> str:
    return "Ab1_Cd2-Ef3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3ab"


def _private_key_header(modifier: str) -> str:
    return "-----BEGIN " + modifier + "PRIVATE" + " KEY-----"


def _load_audit_module():
    specification = importlib.util.spec_from_file_location("audit_public_repo", AUDIT_SCRIPT)
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


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


@pytest.mark.parametrize("filename", ("sample.pdf", "sample.pptx", "sample.docx", "sample.xls"))
def test_rejects_non_xlsx_synthetic_fixture_files(tmp_path, filename):
    root = _repository(tmp_path)
    path = f"backend/tests/fixtures/synthetic/{filename}"
    _write(root, path)
    _track(root, path)

    result = _run(root)

    assert result.returncode == 1
    assert path in result.stdout


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


def test_history_reports_deleted_key_at_its_relative_path(tmp_path):
    root = _repository(tmp_path)
    key = _fake_key()
    path = "docs/deleted-key.py"
    _write(root, path, key)
    _track(root, path)
    _commit(root, "add deleted key")
    (root / "docs" / "deleted-key.py").unlink()
    _git(root, "add", "-u")
    _commit(root, "remove deleted key")

    result = _run(root, "--history")

    assert result.returncode == 1
    assert path in result.stdout
    assert key not in result.stdout
    assert key not in result.stderr


def test_history_reports_deleted_key_from_merge_at_unicode_space_path(tmp_path):
    root = _repository(tmp_path)
    _write(root, "README.md")
    _track(root, "README.md")
    _commit(root, "create merge base")
    _git(root, "checkout", "-b", "feature")
    key = _fake_key()
    path = "docs/공백 경로/deleted key.py"
    _write(root, path, key)
    _track(root, path)
    _commit(root, "add merged key")
    _git(root, "checkout", "-")
    _git(root, "merge", "--no-ff", "feature", "-m", "merge feature")
    (root / "docs" / "공백 경로" / "deleted key.py").unlink()
    _git(root, "add", "-u")
    _commit(root, "remove merged key")

    current = _run(root)
    history = _run(root, "--history")

    assert current.returncode == 0
    assert history.returncode == 1
    assert path in history.stdout
    assert key not in history.stdout
    assert key not in history.stderr


def test_non_git_root_is_operational_error(tmp_path):
    root = tmp_path / "not-a-repository"
    root.mkdir()

    result = _run(root)

    assert result.returncode == 2
    assert "Git" in result.stderr


@pytest.mark.parametrize("modifier", ("", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED "))
def test_rejects_private_key_headers_including_pkcs8(tmp_path, modifier):
    root = _repository(tmp_path)
    _write(root, "key.txt", _private_key_header(modifier) + "\n")
    _track(root, "key.txt")

    result = _run(root)

    assert result.returncode == 1
    assert "비밀 패턴: key.txt" in result.stdout


def test_rejects_aws_access_key_id(tmp_path):
    # 리뷰 발견 6 (2026-09-03): 다른 패턴은 전부 양성 테스트가 있는데 AKIA 만 없었다
    root = _repository(tmp_path)
    key = "AKIA" + "IOSFODNN7EXAMPLE"
    _write(root, "notes.md", f"aws {key}\n")
    _track(root, "notes.md")

    result = _run(root)

    assert result.returncode == 1
    assert "비밀 패턴: notes.md" in result.stdout
    assert key not in result.stdout


@pytest.mark.parametrize(
    "prefix",
    (
        ("sk", "-proj-"),
        ("sk", "-svcacct-"),
        ("sk", "-ant-api03-"),
        ("sk", "-"),
        ("gh", "p_"),
        ("gh", "o_"),
        ("gh", "u_"),
        ("gh", "s_"),
        ("gh", "r_"),
        ("github", "_pat_11ABCDEFG_"),
    ),
)
def test_rejects_expanded_key_prefixes(tmp_path, prefix):
    root = _repository(tmp_path)
    key = "".join(prefix) + _key_body()
    _write(root, "notes.md", f"token {key}\n")
    _track(root, "notes.md")

    result = _run(root)

    assert result.returncode == 1
    assert "비밀 패턴: notes.md" in result.stdout
    assert key not in result.stdout


@pytest.mark.parametrize(
    "template",
    (
        "{name}={value}\n",
        "export {name}={value}\n",
        "{name}: {value}\n",
        '{name} = "{value}"\n',
        '"{name}": "{value}"\n',
    ),
)
def test_rejects_literal_environment_assignments(tmp_path, template):
    root = _repository(tmp_path)
    name = "ANTHROPIC" + "_API_KEY"
    _write(root, "config.txt", template.format(name=name, value=_key_body()))
    _track(root, "config.txt")

    result = _run(root)

    assert result.returncode == 1
    assert "비밀 패턴: config.txt" in result.stdout
    assert _key_body() not in result.stdout


@pytest.mark.parametrize("name", ("anthropic_api_key", "github_token", "Openai_Api_Key"))
def test_rejects_lowercase_environment_assignments(tmp_path, name):
    # 재작업 리뷰 발견 (2026-09-03): 오탐을 줄이며 이름의 대소문자 구분을 켰더니 pydantic Settings 관례인
    # 소문자 스네이크케이스 이름에 담긴 실제 비밀값을 놓쳤다. 값 형태(20자 이상)가 오탐을 막는 실질 조건이다
    root = _repository(tmp_path)
    _write(root, "config.py", f'{name} = "{_key_body()}"\n')
    _track(root, "config.py")

    result = _run(root)

    assert result.returncode == 1
    assert "비밀 패턴: config.py" in result.stdout
    assert _key_body() not in result.stdout


def test_allows_environment_lookups_ci_syntax_and_placeholders(tmp_path):
    root = _repository(tmp_path)
    samples = {
        "config.py": 'OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")\n',
        "settings.py": "anthropic_api_key = settings.anthropic_api_key\n",
        "ci_nospace.yml": "GITHUB_TOKEN=${{secrets.GITHUB_TOKEN}}\n",
        "ci_space.yml": "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n",
        "readme.md": "export AWS_ACCESS_KEY_ID=<your-access-key-id>\n",
        "placeholder.env.example": "OPENAI_API_KEY=your-openai-api-key-here\n",
        "task.txt": "task-abcdefghijklmnopqrstuvwxyz0123\n",
        "skhynix.txt": "SK-hynix-semiconductor-fab-2026-report\n",
    }
    for path, content in samples.items():
        _write(root, path, content)
    _track(root, *samples)

    result = _run(root)

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "directory", (".venv", "node_modules", ".superpowers", ".worktrees", "__pycache__")
)
def test_forbids_tool_directories_at_any_depth(tmp_path, directory):
    root = _repository(tmp_path)
    path = f"backend/{directory}/nested/file.txt"
    _write(root, path)
    _git(root, "add", "-f", "--", path)

    result = _run(root)

    assert result.returncode == 1
    assert f"금지 디렉터리: {path}" in result.stdout


@pytest.mark.parametrize(
    "path",
    (
        "uploads/sample.txt",
        "exports/sample.txt",
        "snapshots/sample.json",
        "dist/bundle.js",
        "Uploads/upper.txt",
        "frontend/dist/index.html",
    ),
)
def test_forbids_runtime_data_directories_at_root_and_frontend_dist(tmp_path, path):
    root = _repository(tmp_path)
    _write(root, path)
    _track(root, path)

    result = _run(root)

    assert result.returncode == 1
    assert f"금지 디렉터리: {path}" in result.stdout


def test_allows_runtime_directory_names_below_root(tmp_path):
    root = _repository(tmp_path)
    paths = (
        "frontend/src/pages/projects/List.tsx",
        "src/projects/list.ts",
        "frontend/src/screens/uploads/Panel.tsx",
        "docs/dist",
        "distribution/notes.md",
        "backend/app/uploads.py",
        "build/dist.txt",
        "docs/reviewers.md",
        "docs/review-guide.md",
    )
    for path in paths:
        _write(root, path)
    _track(root, *paths)

    result = _run(root)

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "path",
    (
        "docs/reviews/2026-09-02-review.md",
        "docs/reviews/nested/notes.txt",
        "Docs/Reviews/upper.md",
    ),
)
def test_rejects_review_records_under_docs_reviews(tmp_path, path):
    root = _repository(tmp_path)
    _write(root, path)
    _track(root, path)

    result = _run(root)

    assert result.returncode == 1
    assert f"리뷰 기록: {path}" in result.stdout


def test_missing_git_executable_is_operational_error(tmp_path):
    root = _repository(tmp_path)
    _write(root, "app.py")
    _track(root, "app.py")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()

    result = _run(root, environment_overrides={"PATH": str(empty_path)})

    assert result.returncode == 2
    assert "git" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_invalid_utf8_index_path_is_reported_without_crashing(tmp_path):
    root = _repository(tmp_path)
    _write(root, "README.md")
    _track(root, "README.md")
    blob = subprocess.run(
        ["git", "-C", str(root), "hash-object", "-w", "README.md"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # 잘못된 UTF-8 경로는 인자가 아니라 표준 입력으로 심는다: Windows 의 subprocess 는 인자를 유니코드로
    # 강제 변환하므로 바이트 인자에서 죽는다 (CI 실측 2026-09-03). --index-info 는 어느 플랫폼에서든 바이트를 받는다
    subprocess.run(
        ["git", "-C", str(root), "update-index", "--add", "--index-info"],
        input=f"100644 blob {blob}\t".encode("ascii") + b"projects/caf\xe9.txt\n",
        check=True,
        capture_output=True,
    )

    result = _run(root)

    assert result.returncode == 1
    assert "금지 디렉터리: projects/caf" in result.stdout
    assert result.stderr == ""


def test_module_omits_unused_historical_diff_and_documents_binary_history_limit():
    module = _load_audit_module()

    assert hasattr(module, "historical_paths")
    assert not hasattr(module, "historical_diff")
    assert "Binary files" in (module.__doc__ or "")
