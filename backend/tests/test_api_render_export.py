import json

import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def _project_with_slide(client):
    client.post("/api/projects", json={"name": "p1", "title": "덱"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"] = {"chapters": [
        {"id": "c1", "topic": "요약", "template": "summary"}
    ]}
    deck["slides"] = [{"chapter_id": "c1", "slots": {
        "template": "summary", "conclusion": "결론 한 줄",
        "points": [{"text": "요점"}],
    }}]
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def test_render_plan_returns_frames_and_style(client):
    _project_with_slide(client)
    r = client.get("/api/projects/p1/render-plan")
    assert r.status_code == 200
    plan = r.json()
    assert plan["page_width_pt"] == 960.0
    assert plan["style"]["korean_font"] == "맑은 고딕"
    assert plan["style"]["border_width_pt"] == 0.75
    assert len(plan["slides"]) == 1
    assert plan["slides"][0]["frames"], "프레임이 비어 있습니다"


def test_render_plan_applies_deck_overrides(client):
    _project_with_slide(client)
    deck = client.get("/api/projects/p1/deck").json()
    deck["meta"]["preset_overrides"] = {"colors": {"text": "111111"}}
    client.put("/api/projects/p1/deck", json=deck)
    plan = client.get("/api/projects/p1/render-plan").json()
    assert plan["style"]["text_color"] == "111111"


def test_export_writes_versioned_pptx(client, store):
    _project_with_slide(client)
    r = client.post("/api/projects/p1/export")
    assert r.status_code == 200
    path = r.json()["path"]
    assert path.endswith("_v001.pptx")
    assert (store.exports_dir("p1") / path.split("\\")[-1].split("/")[-1]).exists()
    # 내보내기가 deck.json을 바꾸지 않는다 (설계서 8)
    before = client.get("/api/projects/p1/deck").json()
    client.post("/api/projects/p1/export")
    assert client.get("/api/projects/p1/deck").json() == before


def test_render_plan_missing_project_404(client):
    assert client.get("/api/projects/없는것/render-plan").status_code == 404


def _corrupt_overrides_on_disk(store):
    # 사용자가 탐색기에서 deck.json을 직접 고쳐 PUT 검증을 우회한 상황을 재현한다
    deck_path = store.root / "p1" / "deck.json"
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    data["meta"]["preset_overrides"] = {"font_roles": {"body_pt": 8}}  # 하한 위반
    deck_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_render_plan_with_hand_edited_bad_overrides_422(store):
    client = TestClient(create_app(store), raise_server_exceptions=False)
    _project_with_slide(client)
    _corrupt_overrides_on_disk(store)
    r = client.get("/api/projects/p1/render-plan")
    assert r.status_code == 422
    assert "프리셋" in r.json()["detail"]


def test_export_with_hand_edited_bad_overrides_422(store):
    client = TestClient(create_app(store), raise_server_exceptions=False)
    _project_with_slide(client)
    _corrupt_overrides_on_disk(store)
    r = client.post("/api/projects/p1/export")
    assert r.status_code == 422
    assert "프리셋" in r.json()["detail"]
