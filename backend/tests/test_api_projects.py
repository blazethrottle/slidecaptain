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
