"""저장소의 Git 규칙(.gitignore, .gitattributes)이 단계 5A D1 계약대로 동작하는지 실제 Git 명령으로 검사한다.

문자열 검색이 아니라 `git check-ignore`와 `git check-attr`의 실제 결과와 작업트리 바이트를 본다 (계획서 Global Constraints).
"""

import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_TTF = REPOSITORY_ROOT / "backend" / "slidecaptain" / "fonts" / "assets" / "NotoSansKR-Regular.ttf"
BATCH_FILE = REPOSITORY_ROOT / "SlideCaptain실행.bat"
EOL_FIXTURES = (
    REPOSITORY_ROOT / "backend" / "tests" / "fixtures" / "eol" / "probe.sh",
    REPOSITORY_ROOT / "backend" / "tests" / "fixtures" / "eol" / "probe.command",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _is_ignored(path: str) -> bool:
    # --no-index: 이미 추적 중인지와 무관하게 규칙만 본다. 종료 코드 0 = 무시됨, 1 = 무시되지 않음, 128 = 오류
    result = _git("check-ignore", "--no-index", "-q", "--", path)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def _attr(name: str, path: str) -> str:
    result = _git("check-attr", name, "--", path)
    assert result.returncode == 0, result.stderr
    # 출력 형식: "<path>: <name>: <value>"
    return result.stdout.strip().rsplit(": ", 1)[-1]


@pytest.mark.parametrize(
    "path",
    [
        ".DS_Store",
        "tmp/.DS_Store",
        "Thumbs.db",
        ".env.local",
        "projects/demo/uploads/demo.xlsx",
        "projects/demo/exports/demo.pptx",
        "projects/demo/snapshots/demo.json",
        "docs/pilot/raw/brief.txt",
        "docs/pilot/notes.txt",
        "materials/deck.pptx",
        "backend/tests/fixtures/other/sample.xlsx",
    ],
)
def test_ignores_local_and_confidential_paths(path):
    assert _is_ignored(path), f"무시되어야 하는 경로가 추적 가능하다: {path}"


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "docs/pilot/2026-09-02-파일럿-관찰지.md",
        "backend/tests/fixtures/synthetic/sample.xlsx",
        "backend/slidecaptain/__init__.py",
        "README.md",
    ],
)
def test_keeps_allowed_paths_trackable(path):
    assert not _is_ignored(path), f"추적 가능해야 하는 경로가 무시된다: {path}"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("SlideCaptain실행.bat", "crlf"),
        ("scripts/run.command", "lf"),
        ("scripts/run.sh", "lf"),
        ("backend/slidecaptain/__main__.py", "lf"),
        ("README.md", "lf"),
        (".github/workflows/ci.yml", "lf"),
    ],
)
def test_eol_attribute_by_file_type(path, expected):
    assert _attr("eol", path) == expected


def test_bundled_font_is_binary_not_text():
    assert BUNDLED_TTF.is_file()
    assert _attr("text", str(BUNDLED_TTF.relative_to(REPOSITORY_ROOT))) == "unset"


def test_working_tree_batch_file_uses_crlf():
    data = BATCH_FILE.read_bytes()
    assert b"\r\n" in data, "배치 파일은 체크아웃 시 CRLF 여야 한다 (cmd.exe goto 라벨 탐색)"
    assert b"\n" not in data.replace(b"\r\n", b""), "배치 파일에 LF 단독 줄이 섞여 있다"


@pytest.mark.parametrize("fixture", EOL_FIXTURES, ids=lambda p: p.name)
def test_working_tree_shell_fixtures_use_lf(fixture: Path):
    data = fixture.read_bytes()
    assert data, f"줄바꿈 픽스처가 비어 있다: {fixture.name}"
    assert b"\r" not in data, f"셸 스크립트 픽스처에 CR 이 있다: {fixture.name}"
