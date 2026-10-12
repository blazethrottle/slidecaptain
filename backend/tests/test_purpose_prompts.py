"""보고 목적 값의 생성 전달 (개정판 D3b-3, 계획 4.4).

구조안, 장 생성(축약 포함), 재작성(수리 포함), 도식 지시문에 핵심 내용, 원하는 결과, 지금 유형의 추가
입력이 지시 부분에 정확히 한 번 들어간다. 재작성 문맥 덤프에서는 뺀다. 빈 값은 "미입력"으로 표기하고,
원하는 결과의 우선순위 문구를 넣는다. 실제 생성 품질은 확인하지 않는다(AI 호출 0회).
"""

import json
from pathlib import Path

import pytest

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.pipeline.diagram_generation import GenerateDiagramRequest, diagram_prompt
from slidecaptain.pipeline.prompts import build_chapter_prompt, build_condense_prompt, build_structure_prompt
from slidecaptain.pipeline.relevance import structure_relevance
from slidecaptain.pipeline.report_types import REPORT_TYPE_GUIDES
from slidecaptain.pipeline.rewrite import rewrite_prompt
from slidecaptain.pipeline.story import story_fingerprint
from test_diagram_generation import REQUEST as DIAGRAM_REQUEST
from test_diagram_generation import diagram_input  # noqa: F401 (픽스처)

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "핵심 내용 표지 KM7Q"
OTHER = "기타 목적 표지 OT3Z"
PERIOD = "보고 기간 표지 PR5W"
HIDDEN = "숨은 입력 표지 HD9X"


def _purpose_deck(**update) -> tuple[Deck, dict]:
    sample = json.loads((FIXTURES / "q3b-project.json").read_text(encoding="utf-8"))
    payload = sample["deck"]
    payload["meta"].update(update)
    deck = Deck.model_validate(payload)
    plan = deck.structure.story_plan
    plan.brief = plan.brief.model_copy(update={"report_type": deck.meta.report_type, "audience": deck.meta.audience})
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sample["sources"])
    return deck, sample["sources"]


RICH = {"report_type": "weekly", "key_message": KEY, "desired_outcome": "persuasion",
        "report_details": {"weekly.period": PERIOD, "ir.investment_stage": HIDDEN}}


def _prompts(deck: Deck, sources: dict) -> dict[str, str]:
    chapter = deck.structure.chapters[-1]
    chapter_prompt = build_chapter_prompt(deck, chapter, sources, {}, today="2026-10-12")
    return {
        "structure": build_structure_prompt(deck.meta, sources),
        "structure_brief": build_structure_prompt(deck.meta, sources, brief=deck.structure.story_plan.brief),
        "chapter": chapter_prompt,
        "condense": build_condense_prompt(chapter_prompt, [], "{}"),
        "rewrite": rewrite_prompt(deck, deck.structure.story_plan.brief, sources, ""),
    }


def test_every_prompt_carries_the_purpose_values_exactly_once():
    deck, sources = _purpose_deck(**RICH)
    for name, prompt in _prompts(deck, sources).items():
        assert prompt.count(KEY) == 1, name
        assert prompt.count(PERIOD) == 1, name
        assert "투자자 및 의사결정자 설득" in prompt, name
        assert HIDDEN not in prompt, name  # 숨은 입력은 생성에 쓰지 않는다
        assert "유형 규칙의" in prompt and "보다 우선" in prompt, name  # 원하는 결과의 우선순위 (리뷰 V14)


def test_diagram_prompt_carries_the_purpose_values(diagram_input):  # noqa: F811
    deck, sources, _ = diagram_input
    meta = deck.meta.model_copy(update={"key_message": KEY})
    deck = Deck.model_validate({**deck.model_dump(mode="json"), "meta": meta.model_dump(mode="json")})
    plan = deck.structure.story_plan
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)
    prompt, _ = diagram_prompt(deck, GenerateDiagramRequest(**DIAGRAM_REQUEST), sources)
    assert prompt.count(KEY) == 1


def test_other_outcome_shows_the_users_sentence_and_blank_values_say_not_entered():
    deck, sources = _purpose_deck(report_type="weekly", desired_outcome="other", desired_outcome_other=OTHER)
    prompt = build_structure_prompt(deck.meta, sources)
    assert prompt.count(OTHER) == 1
    plain, _ = _purpose_deck()
    prompt = build_structure_prompt(plain.meta, sources)
    assert "전달할 핵심 내용: 미입력(사용자가 정하지 않음)" in prompt
    assert "원하는 결과: 사용자 미선택(기본: 사실 및 데이터 중심)" in prompt
    assert "미지정" not in prompt.split("보고 정보:")[1].split("\n\n")[0]  # 빈 값 표기를 하나로 (리뷰 V16)


def test_ir_has_a_composition_guide():
    assert "투자 요청" in REPORT_TYPE_GUIDES["ir"]


def test_prompt_and_hash_and_story_fingerprint_change_on_the_same_purpose_fields():
    """칸 하나씩 바꿔 구조안 지시문, 해시 (가), 구성 계획 지문이 같은 칸에서 바뀌는지 본다 (재리뷰 RR12, 가정 2)."""
    deck, sources = _purpose_deck(report_type="weekly")
    plan = deck.structure.story_plan
    base_meta = deck.meta
    edits = {
        "key_message": {"key_message": "새 핵심"},
        "desired_outcome": {"desired_outcome": "business_plan"},
        "desired_outcome_other": {"desired_outcome": "other", "desired_outcome_other": "새 기타"},
        "current_detail": {"report_details": {"weekly.period": "새 기간"}},
        "hidden_detail": {"report_details": {"ir.investment_stage": "숨은 값"}},
        "hidden_other": {"desired_outcome_other": "기타가 아닐 때의 설명"},
        "report_type_confirmed": {"report_type_confirmed": True},
        "presenter": {"presenter": "다른 보고자"},
    }

    def part_a(meta: DeckMeta) -> str:
        return structure_relevance(Deck(meta=meta))[3:].split("|")[0]

    changed = {"prompt": set(), "hash": set(), "story": set()}
    for name, update in edits.items():
        meta = DeckMeta.model_validate({**base_meta.model_dump(mode="json"), **update})
        if build_structure_prompt(meta, sources) != build_structure_prompt(base_meta, sources):
            changed["prompt"].add(name)
        if part_a(meta) != part_a(base_meta):
            changed["hash"].add(name)
        if story_fingerprint(plan, meta, deck.structure.chapters, sources) != story_fingerprint(
                plan, base_meta, deck.structure.chapters, sources):
            changed["story"].add(name)
    expected = {"key_message", "desired_outcome", "desired_outcome_other", "current_detail"}
    assert changed["prompt"] == changed["hash"] == changed["story"] == expected


@pytest.mark.parametrize("field", ["key_message", "desired_outcome_other"])
def test_rewrite_context_dump_leaves_out_purpose_values(field):
    """같은 값이 지시와 데이터 두 자리에 다른 지위로 들어가지 않게 한다 (리뷰 V13)."""
    update = {"key_message": KEY} if field == "key_message" else {"desired_outcome": "other", "desired_outcome_other": OTHER}
    deck, sources = _purpose_deck(**update)
    prompt = rewrite_prompt(deck, deck.structure.story_plan.brief, sources, "")
    context = prompt.split("기존 편집과 보존 계약:\n", 1)[1]
    assert KEY not in context and OTHER not in context
