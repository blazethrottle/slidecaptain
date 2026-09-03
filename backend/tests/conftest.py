"""공용 픽스처 (태스크 A2).

`store`(임시 프로젝트 저장소)와 `client`(표식 헤더가 기본으로 붙는 API 클라이언트)는 여러 테스트
파일이 각자 같은 모양으로 정의하고 있었다(호출 78곳). 상태 변경 요청을 표식 헤더로 보호하는
미들웨어가 생기면서 그 중복 정의를 그대로 두면 파일마다 헤더를 빠뜨리기 쉬워지므로 여기 한 곳으로
모은다. 헤더 자체를 검증하는 보호 테스트는 이 기본 헤더가 없는 클라이언트를 별도로 만든다.
"""

import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


@pytest.fixture
def client(store):
    return TestClient(create_app(store), headers={"X-Requested-With": "SlideCaptain"})
