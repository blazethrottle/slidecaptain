"""편집 보존 재작성의 실제 API 왕복과 거절 경계. 외부 AI를 호출하지 않는다."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slidecaptain.models.deck import Deck
from slidecaptain.models.story import ReportBrief
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.pipeline.story import require_current_story, story_fingerprint
from slidecaptain.server.app import create_app


class StubProvider:
    def __init__(self, payload, effect=None):
        self.payload = payload
        self.effect = effect
        self.calls = []

    async def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        if self.effect:
            self.effect()
        return ProviderResponse(structured=deepcopy(self.payload), raw_text="synthetic rewrite")


@pytest.fixture
def rewrite_input(store):
    sample = json.loads((Path(__file__).parent / "fixtures/q3b-project.json").read_text("utf-8"))
    deck = Deck.model_validate(sample["deck"])
    sources = sample["sources"]
    plan = deck.structure.story_plan
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)
    store.create_project("rewrite")
    for filename, text in sources.items():
        store.write_source("rewrite", filename, text)
    store.save_deck("rewrite", deck, snapshot=False)
    payload = {
        "chapter_order": ["synthetic-flow", "cover"],
        "evidence": [],
        "claims": [],
        "answer_claim_ids": plan.answer_claim_ids,
        "chapters": [{"chapter_id": "cover", "role": "cover", "claim_ids": []}],
        "unanswered_questions": [], "comparisons": [], "derivations": [],
    }
    brief = plan.brief.model_copy(update={"decision_question": "기존 업무를 어떻게 개선할 것인가?"})
    return deck, sources, payload, brief


def app_client(store, provider):
    return TestClient(create_app(store, provider=provider), headers={
        "X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain",
        "If-Match": f'"{store.deck_etag("rewrite")}"',
    })


def preview(client, brief):
    return client.post("/api/projects/rewrite/story-plan/rewrite", json={"brief": brief.model_dump(), "instructions": "내용 보존"})


def apply(client, result):
    return client.post("/api/projects/rewrite/story-plan/rewrite/apply", json={
        "deck": result["deck"], "sources_fingerprint": result["sources_fingerprint"],
    }, headers={"If-Match": result["base_etag"]})


def test_preview_apply_preserves_edits_and_keeps_old_snapshot(rewrite_input, store):
    deck, sources, payload, brief = rewrite_input
    provider = StubProvider(payload)
    client = app_client(store, provider)
    etag = store.deck_etag("rewrite")
    response = preview(client, brief)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ok"
    assert store.deck_etag("rewrite") == etag
    assert store.list_snapshots("rewrite") == []
    candidate = Deck.model_validate(result["deck"])
    assert candidate.slides == deck.slides
    assert candidate.meta == deck.meta
    assert [c.id for c in candidate.structure.chapters] == ["synthetic-flow", "cover"]
    assert candidate.structure.story_plan.brief == brief
    assert candidate.structure.story_plan.evidence == deck.structure.story_plan.evidence
    assert candidate.structure.story_plan.rewrite_review.preserved_chapter_ids == [s.chapter_id for s in deck.slides]
    require_current_story(candidate, sources)
    response = apply(client, result)
    assert response.status_code == 200, response.text
    assert response.headers["etag"].strip('"') == store.deck_etag("rewrite")
    assert store.load_deck("rewrite") == candidate
    assert len(store.list_snapshots("rewrite")) == 1
    snap = store.list_snapshots("rewrite")[0]
    restored = client.post(f'/api/projects/rewrite/snapshots/{snap.id}/restore', headers={"If-Match": response.headers["etag"]})
    assert restored.status_code == 200
    assert store.load_deck("rewrite") == deck
    assert len(provider.calls) == 1


@pytest.mark.parametrize("change", ["append", "delete", "move"])
def test_protected_source_change_blocks_before_ai(rewrite_input, store, change):
    deck, sources, payload, brief = rewrite_input
    filename, original = next(iter(sources.items()))
    if change == "delete":
        (store.root / "rewrite" / "sources" / filename).unlink()
    else:
        store.write_source("rewrite", filename, original + "\n조건 변경" if change == "append" else "새 문맥\n" + original)
    provider = StubProvider(payload)
    client = app_client(store, provider)
    response = preview(client, brief)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "rewrite_protected_evidence"
    assert provider.calls == []
    assert store.load_deck("rewrite") == deck
    assert store.list_snapshots("rewrite") == []


@pytest.mark.parametrize("when,change", [(w, c) for w in ["during", "after"] for c in ["deck", "source", "add_source", "remove_source"]])
def test_changed_base_cannot_apply(rewrite_input, store, when, change):
    deck, sources, payload, brief = rewrite_input
    store.write_source("rewrite", "unrelated.md", "합성 추가 자료")
    def mutate():
        if change == "deck":
            changed = deck.model_copy(deep=True)
            changed.meta.presenter = "동시 편집"
            store.save_deck("rewrite", changed, snapshot=False)
        elif change == "source":
            store.write_source("rewrite", "unrelated.md", "변경된 자료")
        elif change == "add_source":
            store.write_source("rewrite", "new.md", "새 자료")
        else:
            (store.root / "rewrite" / "sources" / "unrelated.md").unlink()
    provider = StubProvider(payload, effect=mutate if when == "during" else None)
    client = app_client(store, provider)
    response = preview(client, brief)
    if when == "during":
        assert response.status_code == (412 if change == "deck" else 409), response.text
    else:
        assert response.status_code == 200, response.text
        result = response.json()
        mutate()
        changed_etag = store.deck_etag("rewrite")
        response = apply(client, result)
        assert response.status_code == (412 if change == "deck" else 409), response.text
        assert store.deck_etag("rewrite") == changed_etag
    assert store.list_snapshots("rewrite") == []


@pytest.mark.parametrize("defect", ["missing", "duplicate", "invented", "claim", "evidence", "role"])
def test_bad_ai_output_is_retried_once_without_saving(rewrite_input, store, defect):
    deck, sources, payload, brief = rewrite_input
    if defect == "missing": payload["chapters"].pop()
    if defect == "duplicate": payload["chapters"].append(payload["chapters"][0])
    if defect == "invented": payload["chapters"][0]["chapter_id"] = "new"
    if defect == "claim": payload["claims"].append({**deck.structure.story_plan.claims[0].model_dump(), "statement": "도식의 의미를 바꿈"})
    if defect == "evidence": payload["evidence"].append({**deck.structure.story_plan.evidence[0].model_dump(exclude={"source_revision", "excerpt"}), "locator": {"line_start": 2, "line_end": 2}})
    if defect == "role": payload["chapters"][0]["role"] = "divider"
    provider = StubProvider(payload)
    response = preview(app_client(store, provider), brief)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "format_error"
    assert response.json()["deck"] is None
    assert len(provider.calls) == 2
    assert store.load_deck("rewrite") == deck
    assert store.list_snapshots("rewrite") == []


@pytest.mark.parametrize("header,status", [("X-AI-Consent", 428), ("If-Match", 428), ("X-Requested-With", 403)])
def test_preview_requires_all_gates(rewrite_input, store, header, status):
    _, _, payload, brief = rewrite_input
    provider = StubProvider(payload)
    client = app_client(store, provider)
    del client.headers[header]
    assert preview(client, brief).status_code == status
    assert provider.calls == []


@pytest.mark.parametrize("field", ["meta", "slide", "topic", "fingerprint", "review"])
def test_apply_revalidates_candidate(rewrite_input, store, field):
    deck, _, payload, brief = rewrite_input
    client = app_client(store, StubProvider(payload))
    response = preview(client, brief)
    assert response.status_code == 200, response.text
    result = response.json()
    candidate = result["deck"]
    if field == "meta": candidate["meta"]["title"] = "바뀐 제목"
    if field == "slide": candidate["slides"][0]["subtitle"] = "바뀐 편집"
    if field == "topic": candidate["structure"]["chapters"][0]["topic"] = "바뀐 주제"
    if field == "fingerprint": candidate["structure"]["story_plan"]["input_fingerprint"] = "0" * 64
    if field == "review": candidate["structure"]["story_plan"]["rewrite_review"] = None
    response = apply(client, result)
    assert response.status_code in (409, 422), response.text
    assert store.load_deck("rewrite") == deck
    assert store.list_snapshots("rewrite") == []


@pytest.mark.parametrize("filename", ["q2a-story-deck.json", "q2b-story-deck.json", "q2c-derived-deck.json"])
def test_existing_versions_rewrite_and_roundtrip_without_changing_legacy_serialization(filename):
    from slidecaptain.pipeline.rewrite import parse_story_rewrite
    sample = json.loads((Path(__file__).parent / "fixtures" / filename).read_text("utf-8"))
    deck = Deck.model_validate(sample["deck"])
    sources = sample["sources"]
    original = deck.model_dump_json()
    assert "rewrite_review" not in original
    assert Deck.model_validate_json(original).model_dump_json() == original
    plan = deck.structure.story_plan
    payload = {"chapter_order": [ch.id for ch in deck.structure.chapters],
               "evidence": [e.model_dump(exclude={"source_revision", "excerpt"}) for e in plan.evidence],
               "claims": [c.model_dump() for c in plan.claims], "answer_claim_ids": plan.answer_claim_ids,
               "chapters": [c.model_dump() for c in plan.chapters], "unanswered_questions": plan.unanswered_questions,
               "comparisons": [c.model_dump() for c in plan.comparisons], "derivations": [d.model_dump() for d in plan.derivations]}
    brief = plan.brief.model_copy(update={"decision_question": "새 질문으로 재검토", "audience": deck.meta.audience, "report_type": deck.meta.report_type})
    candidate = parse_story_rewrite(payload, deck, brief, sources)
    assert candidate.slides == deck.slides
    assert candidate.structure.story_plan.comparisons == plan.comparisons
    assert candidate.structure.story_plan.derivations == plan.derivations
    require_current_story(candidate, sources)
    assert Deck.model_validate_json(candidate.model_dump_json()) == candidate
    assert deck.model_dump_json() == original


def test_non_diagram_source_may_change_and_new_evidence_is_resolved_from_current_source(store):
    from slidecaptain.pipeline.rewrite import parse_story_rewrite
    sample = json.loads((Path(__file__).parent / "fixtures/q2a-story-deck.json").read_text("utf-8"))
    deck = Deck.model_validate(sample["deck"])
    sources = {"new.md": "신규 운영 근거 42명"}
    plan = deck.structure.story_plan
    payload = {"chapter_order": [ch.id for ch in deck.structure.chapters],
               "evidence": [{"id": "new-e", "source_id": "new.md", "locator": {"line_start": 1, "line_end": 1}, "value": "42"}],
               "claims": [{"id": "new-c", "kind": "fact", "statement": "새 자료의 42명", "evidence_ids": ["new-e"], "caveats": []}],
               "answer_claim_ids": ["new-c"], "chapters": [{"chapter_id": ch.id, "role": "answer", "claim_ids": ["new-c"]} for ch in deck.structure.chapters],
               "unanswered_questions": [], "comparisons": [], "derivations": []}
    candidate = parse_story_rewrite(payload, deck, plan.brief.model_copy(update={"audience": deck.meta.audience, "report_type": deck.meta.report_type}), sources)
    assert candidate.slides == deck.slides
    assert candidate.structure.chapters[0].source_refs == ["new.md"]
    assert candidate.structure.story_plan.evidence[0].excerpt == sources["new.md"]
    require_current_story(candidate, sources)


def test_apply_twice_rejects_second_attempt_and_preserves_one_snapshot(rewrite_input, store):
    _, _, payload, brief = rewrite_input
    client = app_client(store, StubProvider(payload))
    result = preview(client, brief).json()
    assert apply(client, result).status_code == 200
    first_etag = store.deck_etag("rewrite")
    assert apply(client, result).status_code == 412
    assert store.deck_etag("rewrite") == first_etag
    assert len(store.list_snapshots("rewrite")) == 1


def test_preview_stale_or_missing_base_never_calls_provider(rewrite_input, store):
    _, _, payload, brief = rewrite_input
    provider = StubProvider(payload)
    client = app_client(store, provider)
    client.headers["If-Match"] = '"stale"'
    assert preview(client, brief).status_code == 412
    assert provider.calls == []


def test_apply_without_etag_is_rejected(rewrite_input, store):
    _, _, payload, brief = rewrite_input
    client = app_client(store, StubProvider(payload))
    result = preview(client, brief).json()
    del client.headers["If-Match"]
    response = client.post("/api/projects/rewrite/story-plan/rewrite/apply", json={"deck":result["deck"],"sources_fingerprint":result["sources_fingerprint"]})
    assert response.status_code == 428
    assert store.list_snapshots("rewrite") == []


def test_overlong_context_blocks_before_ai(rewrite_input, store):
    deck, _, payload, brief = rewrite_input
    deck.slides[0].subtitle = "가" * 60_001
    store.save_deck("rewrite", deck, snapshot=False)
    provider = StubProvider(payload)
    response = preview(app_client(store, provider), brief)
    assert response.status_code == 422
    assert provider.calls == []


def test_usage_records_rewrite_and_format_retry_without_source_text(rewrite_input, store):
    _, _, payload, brief = rewrite_input
    payload["chapters"].pop()
    provider = StubProvider(payload)
    result = preview(app_client(store, provider), brief).json()
    assert result["usage"]["calls"] == 2
    assert [r["purpose"] for r in result["usage"]["records"]] == ["generate", "format_retry"]
    usage_path = store.root / "rewrite" / "ai-usage.jsonl"
    lines = usage_path.read_text("utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "rewrite"
    assert record["outcome"] == "format_error"
    assert "접수" not in lines[0]


def test_rewrite_prompt_does_not_reassign_existing_chapter_ids(rewrite_input):
    from slidecaptain.pipeline.rewrite import rewrite_prompt
    deck, sources, _, brief = rewrite_input
    prompt = rewrite_prompt(deck, brief, sources, "")
    assert "chapter_id" in prompt
    assert "장 id와 source_refs는 코드가 부여한다" not in prompt
    assert "chapters에는 topic, conclusion, template" not in prompt


def test_rewrite_checks_numbers_in_caveats_and_unanswered_questions(rewrite_input, store):
    _, _, payload, brief = rewrite_input
    payload['claims'].append({'id':'extra','statement':'추가 판단','kind':'inference','evidence_ids':[], 'caveats':['가정 98765명']})
    # 보호 도식의 연결을 바꾸지 않도록 일반 장을 별도로 사용한다.
    base=store.load_deck('rewrite')
    ch=base.structure.chapters[0].model_copy(update={'id':'extra-ch','template':'bullet_box','topic':'추가 판단'})
    base.structure.chapters.append(ch)
    store.save_deck('rewrite',base,snapshot=False)
    payload['chapter_order'].append('extra-ch')
    payload['chapters'].append({'chapter_id':'extra-ch','role':'risk','claim_ids':['extra']})
    payload['unanswered_questions']=['추가 비용 87654원은 얼마인가?']
    result=preview(app_client(store,StubProvider(payload)),brief).json()
    assert result['status']=='ok',result
    assert set(result['unverified_numbers']) >= {'98765','87654'}


def test_new_rewrite_text_is_normalized_but_protected_claim_is_preserved(rewrite_input, store):
    deck, _, payload, brief = rewrite_input
    deck.structure.chapters.append(deck.structure.chapters[0].model_copy(update={'id':'extra-ch','template':'bullet_box','topic':'추가 판단'}))
    store.save_deck('rewrite',deck,snapshot=False)
    payload['claims'].append({'id':'extra','statement':'새  판단\u2014확인','kind':'inference','evidence_ids':[], 'caveats':['조건\u00b7확인']})
    payload['chapter_order'].append('extra-ch')
    payload['chapters'].append({'chapter_id':'extra-ch','role':'risk','claim_ids':['extra']})
    payload['unanswered_questions']=['질문\u2014확인']
    result=preview(app_client(store,StubProvider(payload)),brief).json()
    assert result['status']=='ok',result
    new_plan=result['deck']['structure']['story_plan']
    assert new_plan['claims'][0]==deck.structure.story_plan.claims[0].model_dump()
    generated=json.dumps([new_plan['claims'][-1],new_plan['unanswered_questions']],ensure_ascii=False)
    assert '\u2014' not in generated and '\u00b7' not in generated and '새  판단' not in generated
