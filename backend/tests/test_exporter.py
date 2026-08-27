import json
from pathlib import Path

from pptx import Presentation

from slidecaptain.export.exporter import export_deck
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    Chapter,
    Deck,
    DeckMeta,
    Slide,
    Structure,
)


def _write_deck(path: Path, title: str = "내보내기 테스트") -> Deck:
    deck = Deck(
        meta=DeckMeta(title=title),
        structure=Structure(chapters=[Chapter(id="ch01", topic="개요", template="bullet_box")]),
        slides=[
            Slide(chapter_id="ch01", slots=BulletBoxSlots(bullets=[Bullet(text="항목")], conclusion="결론"))
        ],
    )
    path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    return deck


def test_export_creates_versioned_file(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path)
    out_dir = tmp_path / "exports"
    first = export_deck(deck_path, out_dir)
    second = export_deck(deck_path, out_dir)
    assert first.name == "내보내기 테스트_v001.pptx"
    assert second.name == "내보내기 테스트_v002.pptx"
    assert first.exists() and second.exists()  # 기존 파일을 덮어쓰지 않는다


def test_export_leaves_deck_json_untouched(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path)
    before = deck_path.read_bytes()
    export_deck(deck_path, tmp_path / "exports")
    assert deck_path.read_bytes() == before


def test_exported_file_opens_and_has_slides(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path)
    out = export_deck(deck_path, tmp_path / "exports")
    prs = Presentation(str(out))
    assert len(prs.slides) == 1


def test_title_with_invalid_filename_chars_sanitized(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path, title="검토: 결과/요약")
    out = export_deck(deck_path, tmp_path / "exports")
    assert out.exists()
    assert ":" not in out.name


def test_export_works_from_non_ascii_paths(tmp_path):
    korean_dir = tmp_path / "한글 폴더"
    korean_dir.mkdir()
    deck_path = korean_dir / "deck.json"
    _write_deck(deck_path, title="한글 경로 덱")
    out = export_deck(deck_path, korean_dir / "내보내기")
    assert out.exists()
    assert Presentation(str(out))


def test_preset_overrides_from_meta_applied(tmp_path):
    deck_path = tmp_path / "deck.json"
    deck = _write_deck(deck_path)
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    data["meta"]["preset_overrides"] = {"font_roles": {"title_pt": 22.0}}
    deck_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = export_deck(deck_path, tmp_path / "exports")
    prs = Presentation(str(out))
    title_shape = next(s for s in prs.slides[0].shapes if s.name == "ch01:title")
    assert title_shape.text_frame.paragraphs[0].runs[0].font.size.pt == 22.0
