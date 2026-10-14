"""보고 목적 값의 생성 전달 (개정판 D3b-3, 계획 4.4).

구조안, 장 생성(축약 포함), 재작성(수리 포함), 도식 지시문에 핵심 내용, 원하는 결과, 지금 유형의 추가
입력이 지시 부분에 정확히 한 번 들어간다. 재작성 문맥과 수리 검수의 덱 덤프에서는 뺀다. 빈 값은 "미입력"으로
표기하고, 원하는 결과를 명시했을 때만 우선순위 문구를 넣는다. 보고 목적 값의 수치는 미검증 수치로 보지 않는다.
실제 생성 품질은 확인하지 않는다(AI 호출 0회).
"""

import asyncio
import json
from pathlib import Path

import pytest

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.diagram_generation import GenerateDiagramRequest, diagram_prompt
from slidecaptain.pipeline.prompts import build_chapter_prompt, build_condense_prompt, build_structure_prompt
from slidecaptain.pipeline.provider import ProviderResponse
from slidecaptain.pipeline.relevance import chapter_relevance, structure_relevance
from slidecaptain.pipeline.report_types import (
    NOT_ENTERED, OUTCOME_NOT_SELECTED, OUTCOME_PRIORITY_RULE, PURPOSE_HEADER, PURPOSE_RULES, REPORT_TYPE_GUIDES,
    TYPE_MISMATCH, purpose_block,
)
from slidecaptain.pipeline.rewrite import rewrite_prompt
from slidecaptain.pipeline.service import GenerationService
from slidecaptain.pipeline.story import story_fingerprint
from test_diagram_generation import REQUEST as DIAGRAM_REQUEST
from test_diagram_generation import diagram_input  # noqa: F401 (픽스처)
from test_story_plan_rewrite import rewrite_input  # noqa: F401 (픽스처)
from test_story_repair import Provider as RepairProvider
from test_story_repair import execute as execute_repair

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
        assert prompt.count(OUTCOME_PRIORITY_RULE) == 1, name  # 원하는 결과의 우선순위 (리뷰 V14)
        assert prompt.count(PURPOSE_RULES) == 1, name  # 값의 지위와 미입력 규칙 (D3b-3 리뷰 R2, R4)
        assert prompt.count(PURPOSE_HEADER) == 1, name


def test_the_purpose_block_comes_before_the_data():
    """보고 목적 절은 지시 부분에 있다. 첫 자료 표지와 문맥 덤프보다 앞이다 (D3b-3 리뷰 R4)."""
    deck, sources = _purpose_deck(**RICH)
    for name, prompt in _prompts(deck, sources).items():
        data_marks = [prompt.find(mark) for mark in ("=== 자료:", "기존 편집과 보존 계약:") if mark in prompt]
        assert data_marks, name
        assert prompt.index(PURPOSE_HEADER) < min(data_marks), name


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
    assert f"전달할 핵심 내용: {NOT_ENTERED}" in prompt
    # 사용자가 고르지 않은 결과는 기본값을 단정하지 않고, 우선순위 문장도 넣지 않는다 (D3b-3 리뷰 R7)
    assert f"원하는 결과: {OUTCOME_NOT_SELECTED}" in prompt
    assert OUTCOME_PRIORITY_RULE not in prompt
    assert "미지정" not in prompt.split("보고 정보:")[1].split("\n\n")[0]  # 빈 값 표기를 하나로 (리뷰 V16)


def test_blank_audience_says_not_entered_in_the_chapter_prompt_too():
    """장 지시문의 피보고자도 같은 빈 값 표기를 쓴다 (D3b-3 리뷰 R4). brief의 읽기 수준 기본값 "미지정"은
    구성 계획 지문에 들어가므로 이번 범위에서 두었다 (리뷰 R6, 계획 4.4)."""
    deck, sources = _purpose_deck(audience="")
    prompt = build_chapter_prompt(deck, deck.structure.chapters[-1], sources, {}, today="2026-10-12")
    assert f"- 피보고자: {NOT_ENTERED}" in prompt


def test_multiline_values_stay_inside_their_bullet():
    """여러 줄 값의 둘째 줄은 들여 써서 다른 항목처럼 읽히지 않게 한다 (D3b-3 리뷰 R9)."""
    deck, sources = _purpose_deck(key_message="줄1\n- 원하는 결과: 기타: 가짜")
    prompt = build_structure_prompt(deck.meta, sources)
    assert prompt.count("\n- 원하는 결과:") == 1
    assert "줄1\n  - 원하는 결과: 기타: 가짜" in prompt


def test_a_different_prompt_type_leaves_out_the_detail_lines():
    """지시문의 유형과 메타 유형이 다르면 메타 유형의 추가 입력 칸을 쓰지 않는다 (D3b-3 리뷰 R12)."""
    deck, _ = _purpose_deck(**RICH)
    assert PERIOD in purpose_block(deck.meta, "weekly")
    block = purpose_block(deck.meta, "research")
    assert PERIOD not in block and TYPE_MISMATCH in block and KEY in block


def test_ir_has_a_composition_guide():
    assert "투자 요청" in REPORT_TYPE_GUIDES["ir"]


TABLE_EDITS = {
    "key_message": {"key_message": "새 핵심"},
    "key_blank": {"key_message": "   "},
    "key_multiline": {"key_message": "줄1\n- 원하는 결과: 기타: 가짜"},
    "desired_outcome": {"desired_outcome": "business_plan"},
    "desired_facts": {"desired_outcome": "facts"},
    "desired_outcome_other": {"desired_outcome": "other", "desired_outcome_other": "새 기타"},
    "other_blank": {"desired_outcome": "other", "desired_outcome_other": "  "},
    "current_detail": {"report_details": {"weekly.period": "새 기간"}},
    "current_detail_blank": {"report_details": {"weekly.period": "  "}},
    "hidden_detail": {"report_details": {"ir.investment_stage": "숨은 값"}},
    "hidden_other": {"desired_outcome_other": "기타가 아닐 때의 설명"},
    "report_type_confirmed": {"report_type_confirmed": True},
    "presenter": {"presenter": "다른 보고자"},
}
TABLE_CHANGED = {"key_message", "key_multiline", "desired_outcome", "desired_facts", "desired_outcome_other",
                 "other_blank", "current_detail"}


@pytest.mark.parametrize("base_update", [{}, {"key_message": KEY, "report_details": {"weekly.period": PERIOD}}],
                         ids=["empty_base", "filled_base"])
def test_prompts_hashes_and_story_fingerprint_change_on_the_same_purpose_fields(base_update):
    """칸 하나씩 바꿔 구조안 지시문(brief 없음, 있음), 해시 (가), 구성 계획 지문, 장 지시문, 장 관련 입력이 같은
    칸에서 바뀌는지 본다 (재리뷰 RR12, 가정 2, D3b-2 리뷰 R4, D3b-3 리뷰 R3). 공백만 있는 값도 넣어,
    지시문과 해시가 빈 값을 같게 판정하는지 본다. 값이 채워진 기준에서는 공백으로 지우는 편집도 바뀌어야 한다."""
    deck, sources = _purpose_deck(report_type="weekly", **base_update)
    plan = deck.structure.story_plan
    base_meta = deck.meta
    chapter = deck.structure.chapters[-1]

    def with_meta(meta: DeckMeta) -> Deck:
        return Deck.model_validate({**deck.model_dump(mode="json"), "meta": meta.model_dump(mode="json")})

    def columns(meta: DeckMeta) -> dict:
        current = with_meta(meta)
        return {
            "structure": build_structure_prompt(meta, sources),
            "structure_brief": build_structure_prompt(meta, sources, brief=plan.brief),
            "hash_a": structure_relevance(current)[3:].split("|")[0],
            "story": story_fingerprint(plan, meta, deck.structure.chapters, sources),
            "chapter_prompt": build_chapter_prompt(current, chapter, sources, {}, today="2026-10-12"),
            "chapter_hash": chapter_relevance(current, chapter.id),
        }

    base = columns(base_meta)
    changed: dict[str, set] = {name: set() for name in base}
    for name, update in TABLE_EDITS.items():
        if base_update and name in ("key_message", "current_detail"):
            continue  # 채워진 기준에서는 아래 지우기 편집으로 본다
        merged = {**base_meta.model_dump(mode="json"), **update}
        if "report_details" in update:
            merged["report_details"] = {**base_meta.report_details, **update["report_details"]}
        row = columns(DeckMeta.model_validate(merged))
        for column, value in row.items():
            if value != base[column]:
                changed[column].add(name)
    expected = set(TABLE_CHANGED)
    if base_update:
        expected = (expected - {"key_message", "current_detail"}) | {"key_blank", "current_detail_blank"}
    for column, names in changed.items():
        assert names == expected, column


@pytest.mark.parametrize("field", ["key_message", "desired_outcome_other"])
def test_rewrite_context_dump_leaves_out_purpose_values(field):
    """같은 값이 지시와 데이터 두 자리에 다른 지위로 들어가지 않게 한다 (리뷰 V13)."""
    update = {"key_message": KEY} if field == "key_message" else {"desired_outcome": "other", "desired_outcome_other": OTHER}
    deck, sources = _purpose_deck(**update)
    prompt = rewrite_prompt(deck, deck.structure.story_plan.brief, sources, "")
    context = prompt.split("기존 편집과 보존 계약:\n", 1)[1]
    assert KEY not in context and OTHER not in context


class RecordingProvider:
    """받은 지시문을 모두 기록하고 형식이 맞지 않는 응답을 돌려준다. 형식 재시도 지시문까지 기록된다."""

    def __init__(self):
        self.prompts: list[str] = []

    async def complete(self, prompt, schema):
        self.prompts.append(prompt)
        return ProviderResponse({}, "synthetic")


def _assert_purpose_once(prompts: list[str], label: str):
    assert prompts, label
    for index, prompt in enumerate(prompts):
        where = f"{label} {index}"
        assert prompt.count(KEY) == 1, where
        assert HIDDEN not in prompt and OTHER not in prompt, where  # 숨은 입력은 어느 호출에도 없다


def test_every_service_path_sends_the_purpose_values_once_and_no_hidden_input(rewrite_input):  # noqa: F811
    """서비스 함수를 실제로 타서, 형식 재시도와 수리의 독립 검수를 포함한 모든 호출을 본다 (D3b-3 리뷰 R1, R5)."""
    deck, sources, payload, brief = rewrite_input
    hidden = {"key_message": KEY, "desired_outcome": "facts", "desired_outcome_other": OTHER,
              "report_details": {"ir.investment_stage": HIDDEN}}
    deck = Deck.model_validate({**deck.model_dump(mode="json"),
                                "meta": {**deck.meta.model_dump(mode="json"), **hidden}})
    plan = deck.structure.story_plan
    plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)

    paths = {
        "structure": lambda svc: svc.generate_structure(deck.meta, sources, brief=plan.brief),
        "chapter": lambda svc: svc.generate_chapter(deck, "cover", sources, Preset()),
        "rewrite": lambda svc: svc.rewrite_story(deck, brief, sources, "내용 보존"),
        "diagram": lambda svc: svc.generate_diagram(deck, GenerateDiagramRequest(**DIAGRAM_REQUEST), sources),
    }
    for label, run in paths.items():
        provider = RecordingProvider()
        asyncio.run(run(GenerationService(provider, FontMetrics.load_default())))
        assert len(provider.prompts) == 2, label  # 첫 호출과 형식 재시도
        _assert_purpose_once(provider.prompts, label)

    repair = RepairProvider(payload)
    result = execute_repair((deck, sources, payload, brief), repair)
    assert result.status == "reviewed_candidate"
    assert any("독립 검수 역할" in prompt for prompt in repair.calls)
    _assert_purpose_once(repair.calls, "repair")


def test_numbers_in_the_purpose_values_are_not_unverified():
    """보고 목적 값은 사용자가 직접 적은 보고 정보라 표지에 옮겨 쓸 수 있다 (D3b-3 리뷰 R2, 계획 4.4)."""
    deck, sources = _purpose_deck(report_type="ir", key_message="시리즈 A 30억 원 유치를 설득한다",
                                  desired_outcome="persuasion",
                                  report_details={"ir.ask_and_use": "시리즈 A 30억 원, 개발 60퍼센트"})

    class CoverProvider:
        async def complete(self, prompt, schema):
            return ProviderResponse({"template": "cover", "title": "투자 제안",
                                     "subtitle": "시리즈 A 30억 원 투자 요청, 77개 기관", "date": "2026-10-12"},
                                    "synthetic")

    result = asyncio.run(GenerationService(CoverProvider(), FontMetrics.load_default())
                         .generate_chapter(deck, "cover", sources, Preset()))
    assert result.status == "ok"
    assert result.unverified_numbers == ["77"]  # 보고 목적 값에 없는 수치는 그대로 잡는다


def test_surrounding_whitespace_changes_nothing_downstream():
    """자동 저장이 입력 중의 끝 공백이나 줄바꿈을 저장해도 지시문, 판정 해시, 구성 계획 지문, 장 관련 입력이
    그대로다. 같은 내용인데 승인한 계획과 보류 후보가 낡지 않게 한다 (α 묶음 리뷰 A5)."""
    deck, sources = _purpose_deck(report_type="weekly", key_message=KEY, report_details={"weekly.period": PERIOD})
    plan = deck.structure.story_plan
    chapter = deck.structure.chapters[-1]

    def observed(meta: DeckMeta) -> tuple:
        current = Deck.model_validate({**deck.model_dump(mode="json"), "meta": meta.model_dump(mode="json")})
        return (build_structure_prompt(meta, sources, brief=plan.brief), structure_relevance(current),
                story_fingerprint(plan, meta, deck.structure.chapters, sources),
                build_chapter_prompt(current, chapter, sources, {}, today="2026-10-12"),
                chapter_relevance(current, chapter.id))

    padded = deck.meta.model_copy(update={"key_message": f"  {KEY}\n", "report_details": {"weekly.period": f" {PERIOD} "}})
    assert observed(padded) == observed(deck.meta)


INVESTMENT = "시리즈 A 30억 원 유치를 설득한다"
QUOTED = "시리즈 A 30억 원, 43개 기관"  # 30은 보고 목적 값에 있고 43은 없다


def _with_key(deck: Deck, sources: dict) -> Deck:
    deck = Deck.model_validate({**deck.model_dump(mode="json"),
                                "meta": {**deck.meta.model_dump(mode="json"), "key_message": INVESTMENT}})
    plan = deck.structure.story_plan
    if plan is not None:
        plan.input_fingerprint = story_fingerprint(plan, deck.meta, deck.structure.chapters, sources)
    return deck


class FixedProvider:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, prompt, schema):
        return ProviderResponse(self.payload, "synthetic")


@pytest.mark.parametrize("path", ["structure", "rewrite", "diagram"])
def test_purpose_numbers_are_allowed_in_every_generation_path(request, path):
    """구조안, 재작성, 도식의 미검증 수치 검사도 보고 목적 값을 허용한다 (D3b-3 리뷰 R2, α 묶음 리뷰 A2)."""
    if path == "structure":
        deck, sources = _purpose_deck()
        deck = _with_key(deck, sources)
        payload = {"chapters": [{"topic": "투자 제안", "conclusion": QUOTED, "template": "cover", "source_refs": []}]}
        run = lambda svc: svc.generate_structure(deck.meta, sources)  # noqa: E731
    elif path == "rewrite":
        deck, sources, payload, brief = request.getfixturevalue("rewrite_input")
        deck = _with_key(deck, sources)
        payload = {**payload, "unanswered_questions": [f"{QUOTED}의 출처는 무엇인가?"]}
        run = lambda svc: svc.rewrite_story(deck, brief, sources, "")  # noqa: E731
    else:
        deck, sources, payload = request.getfixturevalue("diagram_input")
        deck = _with_key(deck, sources)
        payload = json.loads(json.dumps(payload))
        payload["nodes"][0]["content"] += f" {QUOTED}"
        run = lambda svc: svc.generate_diagram(deck, GenerateDiagramRequest(**DIAGRAM_REQUEST), sources)  # noqa: E731
    result = asyncio.run(run(GenerationService(FixedProvider(payload), FontMetrics.load_default())))
    assert result.status == "ok", result
    assert result.unverified_numbers == ["43"]
