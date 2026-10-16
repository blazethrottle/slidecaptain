"""공용 픽스처 (태스크 A2).

`store`(임시 프로젝트 저장소)와 `client`(표식 헤더가 기본으로 붙는 API 클라이언트)는 여러 테스트
파일이 각자 같은 모양으로 정의하고 있었다(호출 78곳). 상태 변경 요청을 표식 헤더로 보호하는
미들웨어가 생기면서 그 중복 정의를 그대로 두면 파일마다 헤더를 빠뜨리기 쉬워지므로 여기 한 곳으로
모은다. 헤더 자체를 검증하는 보호 테스트는 이 기본 헤더가 없는 클라이언트를 별도로 만든다.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidecaptain.fonts import installer
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


def _patch_testclient_base_url() -> None:
    """TestClient의 기본 Host를 운영 허용 목록 안의 127.0.0.1로 돌린다 (2026-10-14 최종 리뷰 SV-11).

    starlette TestClient의 기본 base_url은 `http://testserver`다. 종전에는 이 이름을 운영
    TrustedHost 허용 목록에 넣어 시험을 통과시켰는데, 그러면 실제 서버도 `Host: testserver`를
    받아들인다. pytest 시험 파일 40개(생성 213줄)가 TestClient를 직접 만들므로 파일마다 base_url을
    적는 대신 여기 한 곳에서 기본값을 바꾼다. base_url을 명시한 호출(`test_api_protection.py`의
    Host 검사)은 그대로 그 값을 쓴다.

    이 교체는 pytest 프로세스 안에서만 적용된다. pytest 밖에서 TestClient를 만드는 코드
    (`scripts/quality_pilot.py`, `tests/measure_jobs.py`, multiprocessing spawn 자식)는 반드시
    `base_url="http://127.0.0.1"`을 명시한다. `test_quality_pilot.py`의 별도 프로세스 시험이 이를 지킨다
    (2026-10-14 머지 전 리뷰 PM-01: 이 보정 없이 두 스크립트가 모든 요청에 400을 받았다).
    """
    original_init = TestClient.__init__
    if getattr(original_init, "_slidecaptain_base_url_patch", False):
        return

    def patched_init(self, app, base_url="http://127.0.0.1", *args, **kwargs):
        original_init(self, app, base_url, *args, **kwargs)

    patched_init._slidecaptain_base_url_patch = True  # type: ignore[attr-defined]
    TestClient.__init__ = patched_init  # type: ignore[method-assign]


_patch_testclient_base_url()


@pytest.fixture
def symlink_or_skip():
    """Skip only Windows accounts without symbolic-link creation permission."""
    def create(path, target, *, target_is_directory=False):
        try:
            path.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("Windows account lacks symbolic-link creation permission (WinError 1314)")
            raise
    return create


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


@pytest.fixture
def client(store):
    return TestClient(create_app(store), headers={"X-Requested-With": "SlideCaptain"})


@pytest.fixture(autouse=True)
def isolated_font_dirs(tmp_path, monkeypatch):
    """모든 테스트에서 폰트 설치 대상을 실제 사용자 폰트 폴더 대신 임시 폴더로 돌린다 (태스크 D2-2).

    `test_cli.py::test_serve_binds_localhost_only`처럼 `main(["serve", ...])`를 통해
    `ensure_fonts()`를 호출하는 테스트가 이 픽스처 없이 돌면, 폰트가 아직 없는 PC에서
    실제 사용자 폰트 폴더(macOS `~/Library/Fonts` 등)에 Noto Sans KR을 설치해 버린다
    (이 Mac에서는 2026-09-02 테스트 실행이 이미 그렇게 설치한 이력이 있다).

    `installer._user_font_dir` 자체를 통째로 다른 함수로 바꾸면 `test_fonts.py`의
    `test_user_font_dir_windows/macos/linux`처럼 원본 함수의 플랫폼 분기 로직 자체를
    검증하는 테스트와 충돌한다(그 테스트들은 `_user_font_dir`를 재정의하지 않고 실제
    반환값을 검사하므로, 함수를 여기서 갈아치우면 검증 대상 자체가 사라져 실패한다.
    실측: 그 방식으로 먼저 시도했다가 이 세 테스트가 깨지는 것을 확인했다). 대신
    `Path.home`을 임시 폴더로 바꾼다: `_user_font_dir`의 macOS와 Linux 분기는 내부에서
    `Path.home()`을 호출해 경로를 조립하므로, 홈만 바꾸면 원본 로직은 그대로 실행되면서
    결과 경로만 임시 폴더 아래로 옮겨진다. Windows 분기는 `LOCALAPPDATA` 환경변수를 쓰고
    `Path.home()`을 참조하지 않으므로 그 변수도 임시 폴더로 돌린다(D2-2 리뷰 반영: 이것이 없으면
    CI windows-latest 러너에서 격리가 되지 않아 실제 사용자 폰트 폴더에 설치하고 격리 단언이 실패한다).
    `_system_font_dirs`는 절대경로(`/Library/Fonts`, `C:/Windows/Fonts`)라 홈과
    무관하므로 이쪽은 원안대로 빈 목록을 돌려주는 함수로 바꾼다.
    `_run_serve`는 함수 안에서 `ensure_fonts`를 임포트해 부르므로, 여기서 바꾼
    `Path.home`과 `_system_font_dirs`가 그 호출에도 그대로 적용된다.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "isolated_home")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "isolated_home" / "AppData" / "Local"))
    monkeypatch.setattr(installer, "_system_font_dirs", lambda: [])
    if sys.platform == "win32":
        _isolate_windows_font_registration(monkeypatch)


class _NoRegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _isolate_windows_font_registration(monkeypatch) -> None:
    """실제 Windows 계정에 남는 글꼴 설치의 부작용을 막는다 (2026-10-16 회사 PC 실측).

    폴더만 임시로 돌리면 `install_fonts`의 Windows 분기가 실제 HKCU 글꼴 등록에 임시 경로를 쓰고,
    세션 글꼴 표에 임시 파일을 올리고, 모든 창에 WM_FONTCHANGE를 보낸다. 백엔드 전체 시험 한 번 뒤
    사용자 계정의 등록 2건이 pytest 임시 폴더를 가리킨 채 남았다. 설치기 논리를 검증하는 시험은
    `sys.modules`의 `winreg`와 `ctypes`를 가짜 모듈로 통째 바꾸므로 여기서 바꾼 진짜 모듈의 함수를
    부르지 않는다. 그래서 진짜 모듈의 쓰기 함수만 아무 일도 하지 않는 함수로 바꾼다(읽기는 그대로 둔다).
    """
    import ctypes
    import winreg

    monkeypatch.setattr(winreg, "CreateKeyEx", lambda *args, **kwargs: _NoRegistryKey())
    monkeypatch.setattr(winreg, "SetValueEx", lambda *args, **kwargs: None)
    monkeypatch.setattr(ctypes.windll.gdi32, "AddFontResourceW", lambda path: 1)
    monkeypatch.setattr(ctypes.windll.user32, "SendMessageTimeoutW", lambda *args: 1)


def pytest_sessionfinish(session, exitstatus):
    # 래퍼 이전 대응표의 범주 기록 (D3c-7). D3C7_MIGRATION_OUT이 없으면 아무것도 쓰지 않는다
    from tests.job_runs import write_records

    write_records()
