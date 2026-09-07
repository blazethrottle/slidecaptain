"""템플릿 이름의 단일 출처 검사 (2026-09-07 DA-5).

템플릿 이름이 네 곳에 따로 하드코딩돼 있다: 구조안 스키마의 enum, 프롬프트의 슬롯 매핑,
용량 계약 딕셔너리, 글자 수 환산 함수. 여기에 레이아웃 빌더까지 다섯이다.

한 곳이라도 빠뜨리면 그 템플릿을 쓰는 순간 KeyError 나 ValueError 가 나고, 생성 라우트는
이를 잡지 않으므로 사용자에게 500 오류가 간다. 이 테스트는 `TemplateName` 을 단일 출처로
놓고 다섯 곳이 같은 집합인지 확인한다. 새 템플릿을 더하는 모든 작업이 여기에 걸린다.
"""

from typing import get_args

import pytest

from slidecaptain.metrics.capacity import capacity_contract, char_hints
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import TemplateName
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.prompts import _SLOTS_BY_TEMPLATE, structure_response_schema

TEMPLATES = set(get_args(TemplateName))
PRESET = Preset()


def _structure_enum() -> set[str]:
    schema = structure_response_schema()
    properties = schema["properties"]["chapters"]["items"]["properties"]
    return set(properties["template"]["enum"])


def test_declared_templates_are_not_empty():
    assert len(TEMPLATES) >= 7


def test_structure_schema_enum_matches_declared_templates():
    assert _structure_enum() == TEMPLATES


def test_slot_model_map_matches_declared_templates():
    assert set(_SLOTS_BY_TEMPLATE) == TEMPLATES


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_capacity_contract_answers_for_every_template(template):
    assert isinstance(capacity_contract(template, PRESET), dict)


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_char_hints_answers_for_every_template(template):
    metrics = FontMetrics.from_bundled()

    assert isinstance(char_hints(template, PRESET, metrics), dict)


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_layout_builder_answers_for_every_template(template):
    """다섯 번째 자리. 종전 검사는 네 곳만 봐서 빌더 누락이 통과했다 (2026-09-07 최종 리뷰)."""

    from slidecaptain.layout.templates import build_slide
    from slidecaptain.metrics.font_metrics import FontMetrics
    from slidecaptain.models.deck import Chapter

    chapter = Chapter(id="ch01", topic="주제", template=template)
    plan = build_slide(chapter, _minimal_slots(template), 1, PRESET, FontMetrics.from_bundled())

    assert plan.template == template
    assert plan.frames


def _minimal_slots(template: str):
    from slidecaptain.models.deck import (
        BulletBoxSlots,
        CalloutSlots,
        CardsSlots,
        CompareSlots,
        CoverSlots,
        DividerSlots,
        ProcessSlots,
        SummarySlots,
        TableSlots,
    )

    return {
        "cover": lambda: CoverSlots(title="제목", subtitle="부제", date="2026-09-07"),
        "divider": lambda: DividerSlots(section_no="1", section_title="구분"),
        "summary": lambda: SummarySlots(conclusion="결론", points=[{"text": "요점", "level": 0}]),
        "bullet_box": lambda: BulletBoxSlots(bullets=[{"text": "항목", "level": 0}], conclusion="결론"),
        "table": lambda: TableSlots(columns=["구분", "값"], rows=[["A", "1"]]),
        "compare2": lambda: CompareSlots(
            conclusion="결론",
            left={"heading": "A", "bullets": [{"text": "왼쪽", "level": 0}]},
            right={"heading": "B", "bullets": [{"text": "오른쪽", "level": 0}]},
        ),
        "callout": lambda: CalloutSlots(text="핵심 메시지 한 문장"),
        "cards": lambda: CardsSlots(cards=[
            {"heading": "카드 A", "bullets": [{"text": "항목", "level": 0}]},
            {"heading": "카드 B", "bullets": [{"text": "항목", "level": 0}]},
        ]),
        "process": lambda: ProcessSlots(steps=[
            {"heading": f"단계{i}"} for i in range(3)
        ]),
    }[template]()


def test_an_unregistered_template_is_rejected_loudly():
    """검사가 실제로 무엇을 잡는지 고정한다: 등록되지 않은 이름은 조용히 넘어가지 않는다."""

    with pytest.raises(KeyError):
        capacity_contract("does_not_exist", PRESET)
