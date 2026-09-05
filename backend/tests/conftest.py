"""공용 픽스처 (태스크 A2).

`store`(임시 프로젝트 저장소)와 `client`(표식 헤더가 기본으로 붙는 API 클라이언트)는 여러 테스트
파일이 각자 같은 모양으로 정의하고 있었다(호출 78곳). 상태 변경 요청을 표식 헤더로 보호하는
미들웨어가 생기면서 그 중복 정의를 그대로 두면 파일마다 헤더를 빠뜨리기 쉬워지므로 여기 한 곳으로
모은다. 헤더 자체를 검증하는 보호 테스트는 이 기본 헤더가 없는 클라이언트를 별도로 만든다.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidecaptain.fonts import installer
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


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
    결과 경로만 임시 폴더 아래로 옮겨진다(Windows 분기는 `LOCALAPPDATA` 환경변수를 쓰고
    `Path.home()`을 참조하지 않으므로 원래도 안전하다).
    `_system_font_dirs`는 절대경로(`/Library/Fonts`, `C:/Windows/Fonts`)라 홈과
    무관하므로 이쪽은 원안대로 빈 목록을 돌려주는 함수로 바꾼다.
    `_run_serve`는 함수 안에서 `ensure_fonts`를 임포트해 부르므로, 여기서 바꾼
    `Path.home`과 `_system_font_dirs`가 그 호출에도 그대로 적용된다.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "isolated_home")
    monkeypatch.setattr(installer, "_system_font_dirs", lambda: [])
