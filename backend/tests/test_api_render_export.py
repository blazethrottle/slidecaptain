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
    assert plan["style"]["korean_font"] == "Noto Sans KR"
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


def test_measure_returns_plan_without_saving(client):
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"]["chapters"] = [{"id": "c1", "topic": "주제", "template": "bullet_box"}]
    deck["slides"] = [{"chapter_id": "c1", "slots": {
        "template": "bullet_box", "bullets": [{"text": "가"}], "conclusion": "결론"}}]
    r = client.post("/api/render-plan", json=deck)
    assert r.status_code == 200
    assert [s["chapter_id"] for s in r.json()["slides"]] == ["c1"]
    # 프로젝트에는 반영되지 않았다 (무저장)
    assert client.get("/api/projects/p1/deck").json()["slides"] == []


def test_measure_reports_capacity_warnings(client):
    # 실측 근거(2026-08-29, 기본 프리셋): 이 문장의 반복 150부터 bullets 영역(318pt)을 넘긴다
    # (needed 319.2pt). 경계가 1.2pt로 얇아 여유를 두고 200을 쓴다. 프리셋 기본값이 바뀌면 재실측할 것
    long_text = "분량 초과 확인 문장 " * 200
    deck = {"meta": {"title": "t"},
            "structure": {"chapters": [{"id": "c1", "topic": "주제", "template": "bullet_box"}]},
            "slides": [{"chapter_id": "c1", "slots": {
                "template": "bullet_box", "bullets": [{"text": long_text}], "conclusion": "결론"}}]}
    r = client.post("/api/render-plan", json=deck)
    assert r.status_code == 200
    assert any(w["slot"] == "bullets" for w in r.json()["slides"][0]["warnings"])


def test_measure_invalid_overrides_422(client):
    deck = {"meta": {"title": "t", "preset_overrides": {"font_roles": {"body_pt": 5}}}}
    r = client.post("/api/render-plan", json=deck)
    assert r.status_code == 422
