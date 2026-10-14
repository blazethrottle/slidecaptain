"""상태 변경 요청 보호 미들웨어 테스트 (계획서 태스크 A2, 가정 3).

client/store 픽스처는 backend/tests/conftest.py 참조. 이 파일은 보호 자체를 검증하므로
기본 헤더가 없는 클라이언트(bare_client)도 따로 둔다.
"""

import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def bare_client(store):
    """표식 헤더가 기본으로 붙지 않는 클라이언트: 보호 자체를 검증하는 테스트 전용."""
    return TestClient(create_app(store))


def test_post_without_app_header_is_403_not_500(bare_client):
    r = bare_client.post("/api/projects/p1/snapshots")
    assert r.status_code == 403
    assert "Slide Captain 화면에서만" in r.json()["detail"]


def test_post_with_app_header_passes_protection(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots")
    assert r.status_code == 201


def test_bad_host_without_app_header_is_403_first(bare_client):
    # 보호 미들웨어가 TrustedHost 보다 바깥이라 나쁜 Host 와 헤더 없음이 겹치면 403 이 먼저다 (계획서 A2, 리뷰 A2-F1)
    r = bare_client.post("/api/projects/p1/snapshots", headers={"Host": "evil.example.com"})
    assert r.status_code == 403


def test_get_passes_without_app_header(bare_client):
    assert bare_client.get("/api/projects").status_code == 200


@pytest.mark.parametrize("host", ["testserver", "testserver:8765", "evil.example"])
def test_unlisted_host_is_rejected_even_for_get(store, host):
    # 2026-10-14 최종 리뷰 SV-11: 운영 허용 목록은 127.0.0.1 과 localhost 뿐이다. 시험 클라이언트의
    # 기본 이름 testserver 도 실제 서버에서는 거절해야 한다 (점 없는 이름은 브라우저가 보낼 수 있다).
    # conftest 가 TestClient 기본 base_url 을 127.0.0.1 로 돌리므로 여기서는 Host 를 명시해 보낸다.
    raw = TestClient(create_app(store), base_url="http://127.0.0.1")
    r = raw.get("/api/projects", headers={"Host": host})
    assert r.status_code == 400


@pytest.mark.parametrize("base_url", ["http://127.0.0.1", "http://localhost"])
def test_listed_hosts_pass(store, base_url):
    raw = TestClient(create_app(store), base_url=base_url)
    assert raw.get("/api/projects").status_code == 200


@pytest.mark.parametrize("origin", ["https://evil.example", "http://127.0.0.1.evil.example"])
def test_disallowed_origin_rejected_even_with_app_header(client, origin):
    # 127.0.0.1.evil.example은 접두사 비교였다면 뚫렸을 값이다 (계획서 가정 3)
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots", headers={"Origin": origin})
    assert r.status_code == 403
    assert "Slide Captain 화면에서만" in r.json()["detail"]


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8765", "http://localhost:5173"])
def test_allowed_origin_passes(client, origin):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots", headers={"Origin": origin})
    assert r.status_code == 201


def test_request_without_origin_header_passes(client):
    # 이 앱의 실제 화면은 Origin을 보내지 않는 요청도 흔하다(같은 오리진 fetch). 헤더 부재를 거부하지 않는다
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots")
    assert r.status_code == 201


def test_post_to_static_path_returns_405_not_403(tmp_path):
    # /api/ 밖 경로는 미들웨어가 손대지 않는다: StaticFiles의 기존 405가 그대로 나와야 한다
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<h1>ui</h1>", encoding="utf-8")
    store = FileProjectStore(tmp_path / "projects")
    bare = TestClient(create_app(store, static_dir=ui))
    r = bare.post("/")
    assert r.status_code == 405
