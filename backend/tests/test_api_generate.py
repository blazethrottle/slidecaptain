from fastapi.testclient import TestClient

from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderResponse
from slidecaptain.server.app import create_app

# store 픽스처는 backend/tests/conftest.py 참조

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


_APP_HEADERS = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}


def _client(store, responses) -> TestClient:
    return TestClient(create_app(store, provider=StubProvider(responses)), headers=_APP_HEADERS)


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
    client = TestClient(create_app(store), headers=_APP_HEADERS)  # provider 없음: 기존 시그니처 호환
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


def test_target_chapters_zero_422(store):
    client = _client(store, [])
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 0})
    assert r.status_code == 422
    assert "target_chapters" in r.json()["detail"]  # 자료 없음 422가 아니라 ge 검증 422임을 판별


def test_sources_over_total_limit_422(store):
    client = _client(store, [])
    client.post("/api/projects", json={"name": "p1"})
    client.put("/api/projects/p1/sources/큰자료.md", json={"text": "가" * 100_001})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 422
    assert "발췌" in r.json()["detail"]


# AI 전송 고지 관문 (계획서 B3, 가정 5): 생성 3종은 X-AI-Consent 헤더가 없으면 428이고 프로바이더가
# 호출되지 않는다. 헤더는 있으나 표식 헤더(X-Requested-With)가 없으면 A2 보호 미들웨어의 403이 먼저다.


def test_generate_structure_without_ai_consent_header_428(store):
    # 프로바이더 응답을 넣지 않는다: 428이 먼저면 프로바이더가 아예 호출되지 않으므로 큐가 비어도 통과한다
    client = TestClient(
        create_app(store, provider=StubProvider([])), headers={"X-Requested-With": "SlideCaptain"}
    )
    client.post("/api/projects", json={"name": "p1"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 428
    assert "AI 전송 확인" in r.json()["detail"]


def test_generate_chapter_without_ai_consent_header_428(store):
    client = TestClient(
        create_app(store, provider=StubProvider([])), headers={"X-Requested-With": "SlideCaptain"}
    )
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={})
    assert r.status_code == 428


def test_condense_chapter_without_ai_consent_header_428(store):
    client = TestClient(
        create_app(store, provider=StubProvider([])), headers={"X-Requested-With": "SlideCaptain"}
    )
    _project_with_structure(client)
    body = {"slots": {"template": "bullet_box",
                      "bullets": [{"text": "현재 내용이 다소 길다", "level": 0}],
                      "conclusion": "성장 지속", "footnote": ""}}
    r = client.post("/api/projects/p1/generate/chapter/c1/condense", json=body)
    assert r.status_code == 428


def test_generate_structure_with_ai_consent_header_passes(store):
    # 헤더가 있으면 종전대로 200이다 (관문 자체는 통과를 막지 않는다)
    client = _client(store, [ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")])
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 5})
    assert r.status_code == 200


def test_generate_without_any_marker_headers_is_403_not_428(store):
    # 표식 헤더(X-Requested-With)까지 없으면 A2 보호 미들웨어의 403이 428보다 먼저다 (계획서 B3)
    client = TestClient(create_app(store, provider=StubProvider([])))
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 403
