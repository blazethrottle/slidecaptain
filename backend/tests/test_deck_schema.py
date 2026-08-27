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
