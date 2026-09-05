import json

from fastapi.testclient import TestClient

from slidecaptain.models.deck import DeckMeta
from slidecaptain.pipeline.prompts import build_structure_prompt
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
    def __init__(self, responses, model=None):
        self.responses = list(responses)
        self.model = model  # 단계 5A 묶음 C 태스크 C3: requested_model이 이 속성을 그대로 옮긴다

    async def complete(self, prompt, schema):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_APP_HEADERS = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}


def _client(store, responses, model=None) -> TestClient:
    return TestClient(
        create_app(store, provider=StubProvider(responses, model=model)), headers=_APP_HEADERS
    )


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


# AI 사용량 로컬 기록 (단계 5A 묶음 C 태스크 C3, 가정 4와 5): 생성 3종 라우트가 GenerationService의
# on_usage 콜백으로 projects/<이름>/ai-usage.jsonl에 작업 1건 = 1줄을 남긴다.


def test_generate_structure_writes_usage_record(store):
    client = _client(
        store, [ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")],
        model="claude-sonnet-4-5-20250929",
    )
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 5})
    assert r.status_code == 200
    assert r.json()["usage"]["calls"] == 1

    lines = (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "structure"
    assert record["chapter_id"] is None
    assert record["outcome"] == "ok"
    assert record["summary"]["calls"] == 1
    assert record["requested_model"] == "claude-sonnet-4-5-20250929"


def test_generate_structure_without_model_writes_none_requested_model(store):
    # 스텁이 model 속성을 안 주면(기본값 None) 기록에도 None으로 남는다
    client = _client(store, [ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")])
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    client.post("/api/projects/p1/generate/structure", json={"target_chapters": 5})
    record = json.loads(
        (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["requested_model"] is None


def test_generate_chapter_with_format_retry_writes_usage_record(store):
    client = _client(store, [
        ProviderResponse(structured=None, raw_text="이상한 응답"),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r"),
    ])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={})
    assert r.status_code == 200
    assert r.json()["format_retried"] is True

    record = json.loads(
        (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["kind"] == "chapter"
    assert record["chapter_id"] == "c1"
    assert record["outcome"] == "ok"
    assert record["summary"]["calls"] == 2
    assert [c["purpose"] for c in record["summary"]["records"]] == ["generate", "format_retry"]


def test_condense_chapter_writes_usage_record(store):
    client = _client(store, [ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    _project_with_structure(client)
    body = {"slots": {"template": "bullet_box",
                      "bullets": [{"text": "현재 내용이 다소 길다", "level": 0}],
                      "conclusion": "성장 지속", "footnote": ""}}
    r = client.post("/api/projects/p1/generate/chapter/c1/condense", json=body)
    assert r.status_code == 200

    record = json.loads(
        (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["kind"] == "condense"
    assert record["chapter_id"] == "c1"
    assert record["summary"]["calls"] == 1


def test_provider_failure_writes_failed_usage_record(store):
    client = _client(store, [ProviderCallFailed("한도를 소진했습니다")])
    _project_with_structure(client)
    r = client.post("/api/projects/p1/generate/chapter/c1", json={})
    assert r.status_code == 503  # 종전과 동일한 상태 코드 (기록 추가가 오류 처리를 바꾸지 않는다)

    record = json.loads(
        (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["kind"] == "chapter"
    assert record["outcome"] == "failed"
    assert record["summary"]["failed_calls"] == 1


def test_generate_ok_even_if_usage_log_write_fails(store, monkeypatch):
    def _boom(name, line):
        raise RuntimeError("기록 실패")

    monkeypatch.setattr(store, "append_usage", _boom)
    client = _client(store, [ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")])
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "시장 규모는 500억 원이다"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 5})
    assert r.status_code == 200  # 기록 쓰기 실패는 생성 결과를 막지 않는다 (가정 4)


def test_usage_log_has_no_content_leak(store):
    # 자료 문장, 지시사항, 응답 원문, 슬롯 문장, 프롬프트 고정 문구, 프로바이더 오류 문구 중
    # 어느 것도 ai-usage.jsonl에 실리지 않는다 (가정 4: 로컬 기록에는 내용이 없다)
    client = _client(store, [
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="원문유출금지첫번째"),
        ProviderResponse(
            structured={"template": "bullet_box",
                        "bullets": [{"text": "슬롯내용유출금지그자체", "level": 0}],
                        "conclusion": "성장 지속", "footnote": ""},
            raw_text="원문유출금지두번째",
        ),
        ProviderCallFailed("프로바이더오류유출금지문구"),
    ])
    client.post("/api/projects", json={"name": "p1", "title": "검토"})
    client.put("/api/projects/p1/sources/리서치.md", json={"text": "자료문장유출금지그자체"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"] = {"chapters": [
        {"id": "c1", "topic": "시장 현황", "conclusion": "성장", "template": "bullet_box",
         "source_refs": ["리서치.md"]},
    ]}
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200

    client.post("/api/projects/p1/generate/structure", json={"instructions": "지시문유출금지그자체"})
    client.post("/api/projects/p1/generate/chapter/c1", json={})
    client.post("/api/projects/p1/generate/chapter/c1", json={})  # 실패 호출

    content = (store.root / "p1" / "ai-usage.jsonl").read_text(encoding="utf-8")
    assert content.count("\n") == 3  # 세 호출 각각 1줄

    fixed_prefix = build_structure_prompt(DeckMeta(title="아무"), {}).splitlines()[0]
    forbidden = [
        "자료문장유출금지그자체",
        "지시문유출금지그자체",
        "원문유출금지첫번째",
        "원문유출금지두번째",
        "슬롯내용유출금지그자체",
        fixed_prefix,
        "프로바이더오류유출금지문구",
    ]
    for text in forbidden:
        assert text not in content
