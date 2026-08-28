import pytest
from pydantic import ValidationError

from slidecaptain.models.deck import (
    SCHEMA_VERSION,
    Bullet,
    BulletBoxSlots,
    Chapter,
    Deck,
    DeckMeta,
    Slide,
    Structure,
    TableSlots,
)


def _minimal_deck() -> Deck:
    return Deck(
        meta=DeckMeta(title="시장 조사 보고"),
        structure=Structure(
            chapters=[
                Chapter(id="ch01", topic="조사 개요", conclusion="조사 범위는 3개국", template="bullet_box"),
            ]
        ),
        slides=[
            Slide(
                chapter_id="ch01",
                slots=BulletBoxSlots(
                    bullets=[Bullet(text="대상: 3개국 주요 사업자"), Bullet(text="기간: 4주", level=1)],
                    conclusion="조사 범위는 3개국 주요 사업자",
                ),
            )
        ],
    )


def test_deck_roundtrip():
    deck = _minimal_deck()
    restored = Deck.model_validate_json(deck.model_dump_json())
    assert restored == deck
    assert restored.schema_version == SCHEMA_VERSION


def test_slots_discriminated_by_template():
    deck = _minimal_deck()
    data = deck.model_dump()
    parsed = Deck.model_validate(data)
    assert isinstance(parsed.slides[0].slots, BulletBoxSlots)


def test_unknown_template_rejected():
    deck = _minimal_deck().model_dump()
    deck["slides"][0]["slots"]["template"] = "fancy_chart"
    with pytest.raises(ValidationError):
        Deck.model_validate(deck)


def test_table_row_width_must_match_columns():
    with pytest.raises(ValidationError):
        TableSlots(columns=["항목", "내용"], rows=[["하나"]])


def test_bullet_level_limited():
    with pytest.raises(ValidationError):
        Bullet(text="깊은 불릿", level=2)


def test_report_type_restricted():
    with pytest.raises(ValidationError):
        DeckMeta(title="x", report_type="poem")


def test_empty_table_columns_rejected():
    with pytest.raises(ValidationError):
        TableSlots(columns=[], rows=[])


def test_duplicate_chapter_id_rejected():
    with pytest.raises(ValidationError):
        Deck(
            meta=DeckMeta(title="테스트"),
            structure=Structure(
                chapters=[
                    Chapter(id="ch01", topic="A", template="bullet_box"),
                    Chapter(id="ch01", topic="B", template="table"),
                ]
            ),
        )


def test_slide_template_mismatches_chapter_template_rejected():
    with pytest.raises(ValidationError):
        Deck(
            meta=DeckMeta(title="테스트"),
            structure=Structure(
                chapters=[
                    Chapter(id="ch01", topic="A", template="bullet_box"),
                ]
            ),
            slides=[
                Slide(chapter_id="ch01", slots=TableSlots(columns=["열"], rows=[["값"]])),
            ],
        )


def test_ghost_chapter_id_rejected():
    # 구조안에 없는 장을 가리키는 슬라이드는 모델 검증에서 막는다 (저장 후 500 방지)
    with pytest.raises(ValidationError) as exc_info:
        Deck(
            meta=DeckMeta(title="테스트"),
            structure=Structure(
                chapters=[
                    Chapter(id="ch01", topic="A", template="bullet_box"),
                ]
            ),
            slides=[
                Slide(
                    chapter_id="유령장",
                    slots=BulletBoxSlots(bullets=[Bullet(text="가")], conclusion="결론"),
                ),
            ],
        )
    assert "구조안에 없는 장" in str(exc_info.value)
    assert "유령장" in str(exc_info.value)


def test_unsupported_schema_version_rejected():
    with pytest.raises(ValidationError) as exc_info:
        Deck.model_validate({"schema_version": 99, "meta": {"title": "t"}})
    assert "스키마 버전" in str(exc_info.value)
    assert "99" in str(exc_info.value)


def test_current_schema_version_accepted():
    deck = Deck.model_validate({"schema_version": 1, "meta": {"title": "t"}})
    assert deck.schema_version == 1


def test_duplicate_slide_for_same_chapter_rejected():
    with pytest.raises(ValidationError) as exc_info:
        Deck.model_validate({
            "meta": {"title": "t"},
            "structure": {"chapters": [{"id": "c1", "topic": "주제", "template": "bullet_box"}]},
            "slides": [
                {"chapter_id": "c1", "slots": {"template": "bullet_box", "conclusion": "결론"}},
                {"chapter_id": "c1", "slots": {"template": "bullet_box", "conclusion": "결론2"}},
            ],
        })
    assert "슬라이드" in str(exc_info.value)


def test_table_cell_newline_rejected():
    with pytest.raises(ValidationError) as exc_info:
        Deck.model_validate({
            "meta": {"title": "t"},
            "structure": {"chapters": [{"id": "c1", "topic": "주제", "template": "table"}]},
            "slides": [{"chapter_id": "c1", "slots": {
                "template": "table", "columns": ["항목"], "rows": [["첫 줄\n둘째 줄"]],
            }}],
        })
    assert "줄바꿈" in str(exc_info.value)
