import pytest
from fastapi.testclient import TestClient

from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderResponse
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore

STRUCTURE_PAYLOAD = {"chapters": [
    {"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []},
    {"topic": "시장 현황", "conclusion": "규모 500억", "template": "bullet_box",
     "source_refs": ["리서치.md"]},
]}

SLOTS_PAYLOAD = {"template": "bullet_box",
                 "bullets": [{"text": "시장 규모 500억", "level": 0}],
                 "conclusion": "성장 지속", "footnote": ""}


class StubProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    async def complete(self, prompt, schema):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _client(store, responses) -> TestClient:
    return TestClient(create_app(store, provider=StubProvider(responses)))


def _project_with_structure(client):
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"] = {"chapters": [
        {"id": "c1", "topic": "시장 현황", "conclusion": "성장", "template": "bullet_box",
         "source_refs": ["리서치.md"]},
    ]}
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def test_generate_structure_returns_draft_without_saving(store):
    client = _client(store, [ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")])
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert [ch["id"] for ch in body["structure"]["chapters"]] == ["c1", "c2"]
    # 초안일 뿐 저장되지 않는다 (설계 결정 3)
    assert client.get("/api/projects/p1/deck").json()["structure"]["chapters"] == []


def test_generate_structure_without_sources_422(store):
    client = _client(store, [])
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 422
    assert "자료" in r.json()["detail"]


def test_generate_chapter_ok(store):
    client = _client(store, [ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["slots"]["template"] == "bullet_box"
    assert body["unverified_numbers"] == []
    # 생성 결과는 저장되지 않는다
    assert client.get("/api/projects/p1/deck").json()["slides"] == []


def test_generate_chapter_unknown_chapter_404(store):
    client = _client(store, [])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/없는장", json={})
    assert r.status_code == 404


def test_provider_failure_returns_503(store):
    client = _client(store, [ProviderCallFailed("한도를 소진했습니다")])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={})
    assert r.status_code == 503
    assert "한도" in r.json()["detail"]


def test_generate_without_provider_returns_503(store):
    client = TestClient(create_app(store))  # provider 없음: 기존 시그니처 호환
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 503


def test_condense_chapter_endpoint(store):
    client = _client(store, [ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    _project_with_structure(client)
    body = {"slots": {"template": "bullet_box",
                      "bullets": [{"text": "현재 내용이 다소 길다", "level": 0}],
                      "conclusion": "성장 지속", "footnote": ""}}
    r = client.post("/api/projects/p1/generate/chapter/c1/condense", json=body)
    assert r.status_code == 200
    assert r.json()["condensed"] is True


def test_condense_chapter_template_mismatch_422(store):
    client = _client(store, [])
    _project_with_structure(client)
    body = {"slots": {"template": "table", "columns": ["a"], "rows": [["b"]]}}
    r = client.post("/api/projects/p1/generate/chapter/c1/condense", json=body)
    assert r.status_code == 422
