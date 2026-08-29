import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def client(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    return TestClient(create_app(store))


def test_create_and_list_projects(client):
    r = client.post("/api/projects", json={"name": "주간보고", "title": "주간 보고"})
    assert r.status_code == 201
    assert r.json()["name"] == "주간보고"
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["주간보고"]


def test_create_duplicate_conflict(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects", json={"name": "p1"})
    assert r.status_code == 409
    assert "이미 있습니다" in r.json()["detail"]


def test_create_invalid_name_unprocessable(client):
    r = client.post("/api/projects", json={"name": "a/b"})
    assert r.status_code == 422


def test_get_and_put_deck(client):
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    assert deck["meta"]["title"] == "제목"
    deck["meta"]["title"] = "고친 제목"
    r = client.put("/api/projects/p1/deck", json=deck)
    assert r.status_code == 200
    assert client.get("/api/projects/p1/deck").json()["meta"]["title"] == "고친 제목"


def test_get_deck_missing_project_404(client):
    r = client.get("/api/projects/없는것/deck")
    assert r.status_code == 404


def test_put_deck_invalid_schema_422(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.put("/api/projects/p1/deck", json={"meta": {}})  # title 없음
    assert r.status_code == 422


def test_put_deck_ghost_chapter_id_422(client):
    client.post("/api/projects", json={"name": "p1"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["slides"] = [{"chapter_id": "유령장", "slots": {
        "template": "bullet_box", "bullets": [{"text": "가"}], "conclusion": "결론",
    }}]
    r = client.put("/api/projects/p1/deck", json=deck)
    assert r.status_code == 422


def test_put_deck_bad_preset_overrides_422(client):
    client.post("/api/projects", json={"name": "p1"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["meta"]["preset_overrides"] = {"font_roles": {"body_pt": 8}}  # 하한 위반
    r = client.put("/api/projects/p1/deck", json=deck)
    assert r.status_code == 422
    assert "하한" in r.json()["detail"]


def test_preset_get_put_and_render_uses_it(client):
    r = client.get("/api/preset")
    assert r.status_code == 200
    preset = r.json()
    preset["font_roles"]["title_pt"] = 30.0
    assert client.put("/api/preset", json=preset).status_code == 200
    assert client.get("/api/preset").json()["font_roles"]["title_pt"] == 30.0
    # 렌더 계획이 전역 프리셋을 밑판으로 쓴다
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"]["chapters"] = [{"id": "c1", "topic": "주제", "template": "bullet_box"}]
    deck["slides"] = [{"chapter_id": "c1", "slots": {
        "template": "bullet_box", "bullets": [], "conclusion": "결론"}}]
    plan = client.post("/api/render-plan", json=deck).json()
    title_para = next(
        p for f in plan["slides"][0]["frames"] if f["name"].endswith(":title") for p in f["paras"]
    )
    assert title_para["font_pt"] == 30.0


def test_preset_put_below_floor_422(client):
    preset = client.get("/api/preset").json()
    preset["font_roles"]["body_pt"] = 5.0
    assert client.put("/api/preset", json=preset).status_code == 422


def test_put_deck_snapshot_query(client):
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    client.put("/api/projects/p1/deck?snapshot=false", json=deck)
    assert client.get("/api/projects/p1/snapshots").json() == []
    client.put("/api/projects/p1/deck", json=deck)  # 기본값은 스냅샷
    assert len(client.get("/api/projects/p1/snapshots").json()) == 1


def test_explicit_snapshot_endpoint(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots")
    assert r.status_code == 201
    assert len(client.get("/api/projects/p1/snapshots").json()) == 1


def test_validation_error_detail_is_korean_string(client):
    r = client.post("/api/projects", json={})  # name 빠짐
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert "name" in r.json()["detail"] and "빠졌습니다" in r.json()["detail"]


def test_deck_validator_korean_message_preserved(client):
    client.post("/api/projects", json={"name": "p1"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["slides"] = [{"chapter_id": "유령", "slots": {"template": "bullet_box", "conclusion": "결"}}]
    r = client.put("/api/projects/p1/deck", json=deck)
    assert r.status_code == 422
    assert "구조안에 없는 장" in r.json()["detail"]  # 모델 검증의 한국어 문구가 그대로 나온다


def test_foreign_host_header_rejected(client):
    r = client.get("/api/projects", headers={"host": "evil.example.com"})
    assert r.status_code == 400


def test_recovery_flow_over_api(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    api = TestClient(create_app(store))
    api.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = api.get("/api/projects/p1/deck").json()
    api.put("/api/projects/p1/deck", json=deck)  # 스냅샷 생성
    (tmp_path / "projects" / "p1" / "deck.json").unlink()
    assert api.get("/api/projects").json()[0]["status"] == "needs_recovery"
    snaps = api.get("/api/projects/p1/snapshots").json()
    r = api.post(f"/api/projects/p1/snapshots/{snaps[0]['id']}/restore")
    assert r.status_code == 200
    assert api.get("/api/projects/p1/deck").status_code == 200
