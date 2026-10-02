"""보고 목적 선택이 저장과 각 생성 단계에 전달되는지 합성 자료로 검증한다."""
import json
from pathlib import Path

import pytest

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.models.story import ReportBrief
from slidecaptain.pipeline.prompts import build_structure_prompt, build_chapter_prompt
from slidecaptain.pipeline.rewrite import rewrite_prompt, parse_story_rewrite
from slidecaptain.pipeline.story import story_fingerprint, require_current_story, StaleStoryPlan


CASES = [
    ("weekly", "주간 업무", "다음 주"),
    ("business", "일반 업무", "업무 현황"),
    ("monthly", "월간", "전월"),
    ("data", "데이터 설명", "분모"),
    ("research", "리서치 결과", "조사 방법"),
    ("project", "프로젝트", "마일스톤"),
    ("results", "결과 보고", "평가 기준"),
    ("approval", "승인요청형", "대안 비교"),
    ("strategy", "전략기획형", "전략 방향"),
]


@pytest.mark.parametrize("kind,label,focus", CASES)
def test_report_type_roundtrip_and_generation_context(client, kind, label, focus):
    sample = json.loads((Path(__file__).parent / "fixtures/q3b-project.json").read_text("utf-8"))
    deck = Deck.model_validate(sample["deck"])
    sources = sample["sources"]
    deck.meta.report_type = DeckMeta(title="합성 보고", report_type=kind).report_type
    plan = deck.structure.story_plan
    plan.brief = ReportBrief(decision_question="어떤 내용을 공유해야 하나요?", report_type=kind,
                             audience=deck.meta.audience)
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)
    assert client.post("/api/projects", json={"name": "purpose"}).status_code == 201
    response = client.put("/api/projects/purpose/deck", json=deck.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    restored = Deck.model_validate(client.get("/api/projects/purpose/deck").json())
    assert restored.meta.report_type == kind
    assert restored.structure.story_plan.brief.report_type == kind
    require_current_story(restored, sources)

    for brief in (None, plan.brief):
        prompt = build_structure_prompt(restored.meta, sources, brief=brief)
        assert label in prompt and focus in prompt
    chapter_prompt = build_chapter_prompt(restored, restored.structure.chapters[0], sources, {}, "2026-10-02")
    assert label in chapter_prompt and focus in chapter_prompt
    assert "지정한 한 장" in chapter_prompt
    prompt = rewrite_prompt(restored, plan.brief, sources, "기존 편집 보존")
    assert label in prompt and focus in prompt
    assert "보존 계약을 우선" in prompt

    payload = {"chapter_order": ["synthetic-flow", "cover"], "evidence": [], "claims": [],
               "answer_claim_ids": plan.answer_claim_ids,
               "chapters": [{"chapter_id": "cover", "role": "cover", "claim_ids": []}],
               "unanswered_questions": [], "comparisons": [], "derivations": []}
    candidate = parse_story_rewrite(payload, restored, plan.brief, sources)
    assert candidate.slides == restored.slides
    assert candidate.meta == restored.meta
    assert candidate.structure.story_plan.evidence == plan.evidence
    require_current_story(candidate, sources)
    candidate.meta.report_type = "approval" if kind != "approval" else "weekly"
    with pytest.raises(StaleStoryPlan):
        require_current_story(candidate, sources)
