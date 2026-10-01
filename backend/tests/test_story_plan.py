"""Q2a: 합성 입력에서 실제 저장과 장 생성까지 계획 계약을 왕복한다."""

import asyncio
from copy import deepcopy
import hashlib

import pytest
from fastapi.testclient import TestClient

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.pipeline.service import GenerationService
from slidecaptain.server.app import create_app


SOURCE = "합성 자료.md"
TEXT = "합성 검토 자료\n시범 운영 만족도: 80%, 응답자 20명.\n전체 확대 비용은 미확인."
SOURCES = {SOURCE: TEXT}
BRIEF = {
    "decision_question": "시범 운영을 확대할 것인가?",
    "audience": "검토 담당자", "report_type": "approval",
    "reading_profile": "미지정", "constraints": [],
}
PAYLOAD = {
    "evidence": [{"id": "e1", "source_id": SOURCE,
                  "locator": {"line_start": 2, "line_end": 2},
                  "value": "80%", "unit": "%", "period": None,
                  "entity": "시범 운영", "denominator": "응답자 20명"}],
    "claims": [
        {"id": "k1", "statement": "시범 운영 만족도는 80%다", "kind": "fact",
         "evidence_ids": ["e1"], "caveats": ["응답자 20명 기준"]},
        {"id": "k2", "statement": "비용 확인 후 확대 여부를 판단한다", "kind": "proposal",
         "evidence_ids": ["e1"], "caveats": ["전체 확대 비용은 미확인"]},
        {"id": "k3", "statement": "전체 확대 비용은 미확인이다", "kind": "unknown",
         "evidence_ids": [], "caveats": ["비용 견적 필요"]},
    ],
    "answer_claim_ids": ["k2"],
    "unanswered_questions": ["전체 확대 비용은 얼마인가?"],
    "chapters": [
        {"topic": "조건부 판단", "conclusion": "비용 확인 후 판단", "template": "summary",
         "role": "answer", "claim_ids": ["k2"]},
        {"topic": "시범 운영 근거", "conclusion": "응답 범위에 한정", "template": "bullet_box",
         "role": "evidence", "claim_ids": ["k1"]},
        {"topic": "추가 확인", "conclusion": "비용 견적 필요", "template": "bullet_box",
         "role": "risk", "claim_ids": ["k3"]},
    ],
}
SLOTS = {"template": "bullet_box", "bullets": [{"text": "만족도 80%", "level": 0}],
         "conclusion": "응답자 20명 기준", "footnote": "합성 자료"}
HEADERS = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}


class StubProvider:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    async def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        return ProviderResponse(structured=deepcopy(self.payloads.pop(0)), raw_text="synthetic")


def generate(payloads):
    from slidecaptain.models.story import ReportBrief

    stub = StubProvider(payloads)
    service = GenerationService(stub, FontMetrics.load_default())
    result = asyncio.run(service.generate_structure(
        DeckMeta(title="합성 보고"), SOURCES, brief=ReportBrief(**BRIEF),
    ))
    return result, service, stub


def test_question_to_bound_plan_and_chapter_context():
    result, service, stub = generate([PAYLOAD, SLOTS])
    assert result.status == "ok"
    plan = result.structure.story_plan
    assert plan.brief.decision_question == BRIEF["decision_question"]
    assert plan.evidence[0].excerpt == TEXT.splitlines()[1]
    assert plan.evidence[0].source_id == SOURCE
    assert plan.evidence[0].source_revision == hashlib.sha256(TEXT.encode()).hexdigest()
    assert plan.answer_claim_ids == ["k2"]
    assert [ch.chapter_id for ch in plan.chapters] == ["c1", "c2", "c3"]
    assert result.structure.chapters[1].source_refs == [SOURCE]
    assert "[L2]" in stub.calls[0][0]
    assert "보고 유형: 승인요청형" in stub.calls[0][0]
    assert "피보고자: 검토 담당자" in stub.calls[0][0]
    deck = Deck(meta=DeckMeta(title="합성 보고"), structure=result.structure)
    from slidecaptain.models.preset import Preset
    chapter = asyncio.run(service.generate_chapter(deck, "c2", SOURCES, Preset()))
    assert chapter.status == "ok"
    assert BRIEF["decision_question"] in stub.calls[1][0]
    assert "응답자 20명 기준" in stub.calls[1][0]
    assert "전체 확대 비용은 얼마인가?" in stub.calls[1][0]
    assert '"kind": "proposal"' in stub.calls[1][0]
    assert "피보고자: 검토 담당자" in stub.calls[1][0]


@pytest.mark.parametrize("defect", [
    "source", "locator", "value", "missing_evidence", "missing_claim", "duplicate_evidence",
    "duplicate_claim", "unbacked_fact", "uncaveated_inference", "uncaveated_unknown",
    "missing_answer", "unassigned_claim", "missing_unknown_question", "empty_chapters",
    "role_mismatch", "cover_claim", "reversed_locator", "duplicate_answer",
])
def test_invalid_plan_retries_once_then_returns_format_error(defect):
    payload = deepcopy(PAYLOAD)
    if defect == "source":
        payload["evidence"][0]["source_id"] = "absent.md"
    elif defect == "locator":
        payload["evidence"][0]["locator"]["line_end"] = 99
    elif defect == "value":
        payload["evidence"][0]["value"] = "90%"
    elif defect == "missing_evidence":
        payload["claims"][0]["evidence_ids"] = ["absent"]
    elif defect == "missing_claim":
        payload["chapters"][0]["claim_ids"] = ["absent"]
    elif defect == "duplicate_evidence":
        payload["evidence"].append(payload["evidence"][0])
    elif defect == "duplicate_claim":
        payload["claims"].append(payload["claims"][0])
    elif defect == "unbacked_fact":
        payload["claims"][0]["evidence_ids"] = []
    elif defect == "uncaveated_inference":
        payload["claims"][0].update(kind="inference", caveats=[])
    elif defect == "uncaveated_unknown":
        payload["claims"][2]["caveats"] = []
    elif defect == "missing_answer":
        payload["chapters"][0]["claim_ids"] = ["k1"]
    elif defect == "unassigned_claim":
        payload["chapters"].pop()
    elif defect == "missing_unknown_question":
        payload["unanswered_questions"] = []
    elif defect == "role_mismatch":
        payload["chapters"][1]["template"] = "cover"
    elif defect == "cover_claim":
        payload["chapters"][1].update(template="cover", role="cover")
    elif defect == "reversed_locator":
        payload["evidence"][0]["locator"] = {"line_start": 3, "line_end": 2}
    elif defect == "duplicate_answer":
        payload["answer_claim_ids"] *= 2
    else:
        payload["chapters"] = []
    result, _, stub = generate([payload, payload])
    assert result.status == "format_error"
    assert result.structure is None
    assert result.format_retried
    assert len(stub.calls) == 2
    assert result.usage.calls == 2
    assert "실패 사유:" in stub.calls[1][0]


def test_invalid_plan_can_be_repaired_by_single_retry():
    bad = deepcopy(PAYLOAD)
    bad["claims"][0]["evidence_ids"] = ["absent"]
    result, _, stub = generate([bad, PAYLOAD])
    assert result.status == "ok"
    assert result.format_retried
    assert len(stub.calls) == 2


def prepare_api(store, payloads):
    provider = StubProvider(payloads)
    client = TestClient(create_app(store, provider=provider), headers=HEADERS)
    assert client.post("/api/projects", json={"name": "synthetic", "title": "합성 보고"}).status_code == 201
    assert client.put(f"/api/projects/synthetic/sources/{SOURCE}", json={"text": TEXT}).status_code == 200
    return client, provider


def save_plan(client):
    response = client.post("/api/projects/synthetic/generate/structure", json={"brief": BRIEF})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    structure = response.json()["structure"]
    assert client.get("/api/projects/synthetic/deck").json()["structure"]["chapters"] == []
    deck = client.get("/api/projects/synthetic/deck").json()
    deck["structure"] = structure
    assert client.put("/api/projects/synthetic/deck", json=deck).status_code == 200
    return deck


def test_api_save_reload_edit_and_condense_preserve_plan(store):
    client, provider = prepare_api(store, [PAYLOAD, SLOTS, SLOTS])
    deck = save_plan(client)
    assert client.get("/api/projects/synthetic/deck").json() == deck
    generated = client.post("/api/projects/synthetic/generate/chapter/c2", json={})
    assert generated.status_code == 200
    deck["slides"] = [{"chapter_id": "c2", "eyebrow": "수동 분류", "subtitle": "", "slots": generated.json()["slots"]}]
    assert client.put("/api/projects/synthetic/deck", json=deck).status_code == 200
    restored = store.load_deck("synthetic")
    assert restored.structure.story_plan.model_dump(mode="json") == deck["structure"]["story_plan"]
    condensed = client.post("/api/projects/synthetic/generate/chapter/c2/condense", json={"slots": SLOTS})
    assert condensed.status_code == 200
    assert BRIEF["decision_question"] in provider.calls[-1][0]


@pytest.mark.parametrize("changed", ["source", "structure", "meta", "plan"])
@pytest.mark.parametrize("operation", ["generate", "condense"])
def test_stale_plan_is_preserved_but_blocks_generation_before_provider(store, changed, operation):
    client, provider = prepare_api(store, [PAYLOAD])
    deck = save_plan(client)
    plan_before = deepcopy(deck["structure"]["story_plan"])
    if changed == "source":
        client.put(f"/api/projects/synthetic/sources/{SOURCE}", json={"text": TEXT + "\n조건 변경"})
    elif changed == "structure":
        deck["structure"]["chapters"][1]["conclusion"] = "사용자 수정"
    elif changed == "meta":
        deck["meta"]["audience"] = "다른 독자"
    else:
        deck["structure"]["story_plan"]["claims"][0]["statement"] = "수정한 주장"
    assert client.put("/api/projects/synthetic/deck", json=deck).status_code == 200
    suffix, body = ("", {}) if operation == "generate" else ("/condense", {"slots": SLOTS})
    response = client.post(f"/api/projects/synthetic/generate/chapter/c2{suffix}", json=body)
    assert response.status_code == 409
    assert response.json().get("code") == "stale_story_plan"
    assert "다시 생성" in response.json()["detail"]
    assert len(provider.calls) == 1
    if changed != "plan":
        assert client.get("/api/projects/synthetic/deck").json()["structure"]["story_plan"] == plan_before


def test_planned_request_still_requires_ai_consent(store):
    client, provider = prepare_api(store, [])
    client.headers.pop("X-AI-Consent")
    response = client.post("/api/projects/synthetic/generate/structure", json={"brief": BRIEF})
    assert response.status_code == 428
    assert provider.calls == []


def test_blank_question_is_rejected_before_provider(store):
    client, provider = prepare_api(store, [])
    response = client.post("/api/projects/synthetic/generate/structure", json={"brief": {**BRIEF, "decision_question": "  "}})
    assert response.status_code == 422
    assert provider.calls == []


def test_source_identifiers_and_multiline_excerpts_are_not_editorially_normalized():
    from slidecaptain.models.story import ReportBrief

    name = "합성·자료.md"
    text = "자료 제목\n  시범·운영 만족도:  80%.\n응답자 20명.\n"
    payload = deepcopy(PAYLOAD)
    payload["evidence"][0].update(source_id=name, locator={"line_start": 2, "line_end": 3})
    payload["claims"][0]["statement"] = "시범·운영\n만족도는 80%다"
    stub = StubProvider([payload])
    service = GenerationService(stub, FontMetrics.load_default())
    result = asyncio.run(service.generate_structure(DeckMeta(title="합성 보고"), {name: text}, brief=ReportBrief(**BRIEF)))
    assert result.status == "ok"
    evidence = result.structure.story_plan.evidence[0]
    assert evidence.source_id == name
    assert evidence.excerpt == "  시범·운영 만족도:  80%.\n응답자 20명."
    assert result.structure.chapters[1].source_refs == [name]
    assert result.structure.story_plan.claims[0].statement == "시범, 운영 만족도는 80%다"


def test_snapshot_restore_preserves_binding_and_detects_later_source_changes(store):
    client, provider = prepare_api(store, [PAYLOAD, SLOTS])
    deck = save_plan(client)
    changed = deepcopy(deck)
    changed["structure"]["chapters"][1]["topic"] = "수동 수정"
    assert client.put("/api/projects/synthetic/deck", json=changed).status_code == 200
    snapshots = client.get("/api/projects/synthetic/snapshots").json()
    response = client.post(f"/api/projects/synthetic/snapshots/{snapshots[-1]['id']}/restore")
    assert response.status_code == 200
    assert response.json() == deck
    assert client.post("/api/projects/synthetic/generate/chapter/c2", json={}).status_code == 200
    assert client.put(f"/api/projects/synthetic/sources/{SOURCE}", json={"text": TEXT + "\n조건 변경"}).status_code == 200
    assert client.post("/api/projects/synthetic/generate/chapter/c2", json={}).status_code == 409
    assert len(provider.calls) == 2
