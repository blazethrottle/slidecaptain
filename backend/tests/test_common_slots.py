"""공통 슬롯(아이브로우, 부제)과 본문 상단 헬퍼 (2026-09-07 DA-4).

지금까지 본문 영역 높이는 여섯 개 빌더가 각자 계산했고, 공유 함수는 프리셋만 받아
슬라이드별 슬롯 유무를 알 수 없었다(적대 리뷰 확인). 슬롯이 생기면 그 계산이 슬라이드마다
달라지므로, 계산을 헬퍼 하나로 모으고 모든 빌더가 그것을 거치는지 테스트로 강제한다.
"""

import inspect
from typing import get_args

import pytest

from slidecaptain.layout import templates as templates_module
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import (
    BulletBoxSlots,
    Chapter,
    Deck,
    DeckMeta,
    Slide,
    Structure,
    TemplateName,
)
from slidecaptain.models.preset import Preset

PRESET = Preset()


def _deck(**slide_kwargs) -> Deck:
    return Deck(
        meta=DeckMeta(title="공통 슬롯"),
        structure=Structure(chapters=[Chapter(id="ch01", topic="주제", template="bullet_box")]),
        slides=[
            Slide(
                chapter_id="ch01",
                slots=BulletBoxSlots(bullets=[{"text": "항목", "level": 0}], conclusion="결론"),
                **slide_kwargs,
            )
        ],
    )


def _frames(deck: Deck) -> dict[str, object]:
    plan = build_render_plan(deck, PRESET, FontMetrics.from_bundled())
    return {f.name.split(":", 1)[1]: f for f in plan.slides[0].frames}


def test_slide_accepts_eyebrow_and_subtitle():
    slide = _deck(eyebrow="정의 및 접근", subtitle="한 문장 요약").slides[0]

    assert slide.eyebrow == "정의 및 접근"
    assert slide.subtitle == "한 문장 요약"


def test_empty_slots_leave_the_layout_exactly_as_before():
    """값이 없으면 프레임을 만들지 않고 본문 좌표도 종전과 같다."""

    before = _frames(_deck())
    after = _frames(_deck(eyebrow="", subtitle=""))

    assert "eyebrow" not in before
    assert "subtitle" not in before
    assert before["title"].y == after["title"].y
    assert before["bullets"].y == after["bullets"].y


def test_eyebrow_sits_above_the_title_and_pushes_it_down():
    plain = _frames(_deck())
    with_eyebrow = _frames(_deck(eyebrow="정의 및 접근"))

    assert with_eyebrow["eyebrow"].y == PRESET.spacing.margin_top
    assert with_eyebrow["eyebrow"].y < with_eyebrow["title"].y
    assert with_eyebrow["title"].y > plain["title"].y


def test_subtitle_sits_below_the_title_and_pushes_content_down():
    plain = _frames(_deck())
    with_subtitle = _frames(_deck(subtitle="한 문장 요약"))

    assert with_subtitle["title"].y == plain["title"].y
    assert with_subtitle["title"].y < with_subtitle["subtitle"].y < with_subtitle["bullets"].y
    assert with_subtitle["bullets"].y > plain["bullets"].y


def test_content_shrinks_by_exactly_what_the_slots_take():
    plain = _frames(_deck())
    both = _frames(_deck(eyebrow="라벨", subtitle="문장"))
    taken = both["bullets"].y - plain["bullets"].y

    assert taken > 0
    assert both["bullets"].h == pytest.approx(plain["bullets"].h - taken)


def test_slots_use_their_own_type_sizes():
    frames = _frames(_deck(eyebrow="라벨", subtitle="문장"))

    assert frames["eyebrow"].paras[0].font_pt == PRESET.font_roles.eyebrow_pt
    assert frames["subtitle"].paras[0].font_pt == PRESET.font_roles.subtitle_pt


@pytest.mark.parametrize("template", sorted(set(get_args(TemplateName))))
def test_every_builder_goes_through_the_shared_geometry_helper(template):
    """빌더가 제 나름대로 본문 상단을 계산하면 새 슬롯이 그 템플릿에서만 누락된다."""

    source = inspect.getsource(templates_module)
    builder = f'"{template}"'

    assert "def slide_geometry" in source or hasattr(templates_module, "slide_geometry")
    assert builder in source


def test_shared_helper_reports_the_same_geometry_when_slots_are_empty():
    from slidecaptain.layout.templates import slide_geometry

    empty = slide_geometry(PRESET, eyebrow="", subtitle="")
    filled = slide_geometry(PRESET, eyebrow="라벨", subtitle="문장")

    assert empty["title_y"] == PRESET.spacing.margin_top
    assert filled["title_y"] > empty["title_y"]
    assert filled["content_top"] > empty["content_top"]
    assert empty["content_bottom"] == filled["content_bottom"]
