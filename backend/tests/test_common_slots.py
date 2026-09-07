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
    CalloutSlots,
    CardsSlots,
    CompareSlots,
    CoverSlots,
    DividerSlots,
    MatrixSlots,
    ProcessSlots,
    SummarySlots,
    TableSlots,
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


def _deck_for(template: str, **slide_kwargs) -> Deck:
    """템플릿별 최소 덱. 공통 슬롯 검증을 bullet_box 하나가 아니라 전 템플릿에 건다."""

    slots = {
        "cover": CoverSlots(title="제목", subtitle="부제", date="2026-09-07"),
        "divider": DividerSlots(section_no="1", section_title="구분"),
        "summary": SummarySlots(conclusion="결론", points=[{"text": "요점", "level": 0}]),
        "bullet_box": BulletBoxSlots(bullets=[{"text": "항목", "level": 0}], conclusion="결론"),
        "table": TableSlots(columns=["구분", "값"], rows=[["A", "1"]]),
        "compare2": CompareSlots(
            conclusion="결론",
            left={"heading": "A", "bullets": [{"text": "왼쪽", "level": 0}]},
            right={"heading": "B", "bullets": [{"text": "오른쪽", "level": 0}]},
        ),
        "callout": CalloutSlots(text="핵심 메시지"),
        "cards": CardsSlots(cards=[
            {"heading": "A", "bullets": [{"text": "왼쪽", "level": 0}]},
            {"heading": "B", "bullets": [{"text": "오른쪽", "level": 0}]},
        ]),
        "process": ProcessSlots(steps=[{"heading": f"단계{i}"} for i in range(3)]),
        "matrix": MatrixSlots(rows=[{"category": f"분류{i}"} for i in range(3)]),
    }[template]
    return Deck(
        meta=DeckMeta(title="공통 슬롯"),
        structure=Structure(chapters=[Chapter(id="ch01", topic="주제", template=template)]),
        slides=[Slide(chapter_id="ch01", slots=slots, **slide_kwargs)],
    )


CONTENT_TEMPLATES = [
    "summary", "bullet_box", "table", "compare2", "callout", "cards", "process", "matrix",
]


@pytest.mark.parametrize("template", CONTENT_TEMPLATES)
def test_every_content_template_moves_its_body_down_for_the_slots(template):
    """텍스트 매칭이 아니라 좌표로 검증한다. 종전 검사는 빌더가 헬퍼를 안 써도 통과했다."""

    plain = _frames(_deck_for(template))
    shifted = _frames(_deck_for(template, eyebrow="라벨", subtitle="문장"))
    body = {
        "summary": "points", "bullet_box": "bullets", "table": "table",
        "compare2": "left_card", "callout": "text", "cards": "card0", "process": "step0",
        "matrix": "row0_category",
    }[template]

    assert shifted[body].y > plain[body].y


@pytest.mark.parametrize("template", CONTENT_TEMPLATES)
def test_body_never_overlaps_the_footer_elements_when_slots_are_present(template):
    """카드 위치만 내려가고 높이가 그대로면 아래 요소를 침범한다 (2026-09-07 최종 리뷰 critical)."""

    frames = _frames(_deck_for(template, eyebrow="라벨", subtitle="문장"))
    body = {
        "summary": "points", "bullet_box": "bullets", "table": "table",
        "compare2": "left_card", "callout": "text", "cards": "card0", "process": "step0",
        "matrix": "row0_category",
    }[template]
    body_frame = frames[body]
    bottom = body_frame.y + body_frame.h
    # 세로로 겹치는지는 가로가 겹치는 것끼리만 따진다. compare2 의 두 카드는 나란히 있다.
    # summary 는 결론 상자가 본문 위에 있으므로 아래에서 시작하는 것만 본다
    def overlaps_horizontally(other):
        return other.x < body_frame.x + body_frame.w and body_frame.x < other.x + other.w

    below = [
        f for f in frames.values()
        if f is not body_frame and f.y >= body_frame.y and overlaps_horizontally(f)
    ]

    for other in below:
        assert bottom <= other.y + 0.01, f"{template}: 본문 바닥 {bottom} 이 {other.name} 상단 {other.y} 를 침범"


@pytest.mark.parametrize("template", ["cover", "divider"])
def test_title_slides_ignore_the_common_slots(template):
    """표지와 간지는 그 자체가 제목 슬라이드라 공통 슬롯을 그리지 않는다."""

    plain = _frames(_deck_for(template))
    with_slots = _frames(_deck_for(template, eyebrow="라벨", subtitle="문장"))

    # 표지에는 자기 슬롯의 subtitle 프레임이 원래 있으므로 이름이 아니라 구성으로 본다
    assert sorted(plain) == sorted(with_slots)
    assert "eyebrow" not in with_slots
    for name, frame in plain.items():
        assert frame.y == with_slots[name].y


def test_capacity_contract_accounts_for_the_common_slots():
    """계약이 슬롯을 모르면 계약대로 채운 슬라이드가 값을 넣는 순간 초과 경고를 받는다."""

    from slidecaptain.metrics.capacity import capacity_contract

    plain = capacity_contract("bullet_box", PRESET)
    shifted = capacity_contract("bullet_box", PRESET, eyebrow="라벨", subtitle="문장")

    assert shifted["bullets_max_lines"] < plain["bullets_max_lines"]


def test_contract_lines_still_fit_after_the_slots_push_content_down():
    """계약과 실측의 왕복: 계약대로 채우면 넘침 경고가 없어야 한다."""

    from slidecaptain.metrics.capacity import capacity_contract

    contract = capacity_contract("bullet_box", PRESET, eyebrow="라벨", subtitle="문장")
    bullets = [{"text": f"항목 {i}", "level": 0} for i in range(contract["bullets_max_lines"])]
    deck = Deck(
        meta=DeckMeta(title="계약 왕복"),
        structure=Structure(chapters=[Chapter(id="ch01", topic="주제", template="bullet_box")]),
        slides=[Slide(chapter_id="ch01", eyebrow="라벨", subtitle="문장",
                      slots=BulletBoxSlots(bullets=bullets, conclusion="결론"))],
    )
    plan = build_render_plan(deck, PRESET, FontMetrics.from_bundled())

    assert plan.slides[0].warnings == []


def test_long_common_slot_text_raises_an_overflow_warning():
    """제목과 각주에는 있는 넘침 경고가 이 두 슬롯에만 없었다 (2026-09-07 최종 리뷰 major)."""

    long_text = "긴 아이브로우 문구를 넣어 한 줄을 넘기게 만든다 " * 6
    deck = _deck_for("bullet_box", eyebrow=long_text)
    plan = build_render_plan(deck, PRESET, FontMetrics.from_bundled())

    assert any(w.slot == "eyebrow" for w in plan.slides[0].warnings)


def test_shared_helper_reports_the_same_geometry_when_slots_are_empty():
    from slidecaptain.layout.templates import slide_geometry

    empty = slide_geometry(PRESET, eyebrow="", subtitle="")
    filled = slide_geometry(PRESET, eyebrow="라벨", subtitle="문장")

    assert empty["title_y"] == PRESET.spacing.margin_top
    assert filled["title_y"] > empty["title_y"]
    assert filled["content_top"] > empty["content_top"]
    assert empty["content_bottom"] == filled["content_bottom"]


# 본문 글자 크기 단계 (계획서 "이 계획이 틀렸을 가능성" 5번의 실측. 2026-09-07 DB 회차)

# 제목 영역의 계층: 제목 20.0 위아래에 아이브로우 10.5 와 부제 14.0 이 붙는다. 이 셋은 본문이
# 아니므로 본문 크기 일관성 검사에서 뺀다. 계획서 위험 5 는 "슬롯을 본문 영역 밖에 둔다" 를
# 선택지로 명시했고, 실측 결과 이것이 맞았다: 이 셋을 넣고 세면 8종 중 7종이 3단계가 되어
# 검사가 늘 실패하지만, 빼고 세면 본문은 전 템플릿에서 12.0 하나로 일관된다.
_TITLE_AREA_SUFFIXES = (":title", ":page_number", ":eyebrow", ":subtitle")


def _body_font_sizes(template: str, eyebrow: str, subtitle: str) -> set[float]:
    slide = build_render_plan(
        _deck_for(template, eyebrow=eyebrow, subtitle=subtitle), PRESET, FontMetrics.from_bundled()
    ).slides[0]
    return {
        p.font_pt
        for f in slide.frames
        if not f.name.endswith(_TITLE_AREA_SUFFIXES)
        for p in f.paras
    }


@pytest.mark.parametrize("template", CONTENT_TEMPLATES)
@pytest.mark.parametrize("eyebrow,subtitle", [("", ""), ("분류", ""), ("", "한 문장 부제"), ("분류", "한 문장 부제")])
def test_body_font_sizes_stay_within_two_steps_for_every_template_and_slot_combination(
    template, eyebrow, subtitle
):
    """본문 글자 크기는 어느 템플릿에서도, 공통 슬롯이 붙어도 두 단계를 넘지 않는다.

    종전 검사는 슬롯이 없는 bullet_box 한 경우만 보아서 새 템플릿도 슬롯 조합도 재지 않았다
    (test_layout_engine.py 의 같은 이름 테스트). 계획서가 위험으로 예고한 항목이라 여기서 전수로 잰다.
    """
    assert len(_body_font_sizes(template, eyebrow, subtitle)) <= 2


def test_the_font_step_check_actually_counts_body_sizes():
    """위 검사가 공허하지 않음을 보인다.

    본문 계열 크기를 프리셋에서 벌리면 세는 단계 수가 늘어야 한다. 이 테스트가 없으면 위 검사가
    늘 통과하는 이유가 규칙이 지켜져서인지 아무것도 세지 않아서인지 구분할 수 없다.
    """
    metrics = FontMetrics.from_bundled()
    roles = PRESET.font_roles
    widened = PRESET.model_copy(
        update={"font_roles": roles.model_copy(update={"box_pt": roles.body_pt + 6})}
    )

    def steps(preset):
        slide = build_render_plan(_deck_for("bullet_box"), preset, metrics).slides[0]
        return {p.font_pt for f in slide.frames if not f.name.endswith(_TITLE_AREA_SUFFIXES) for p in f.paras}

    assert len(steps(widened)) > len(steps(PRESET))
