import json

from slidecaptain.__main__ import main
from slidecaptain.models.deck import Deck, DeckMeta


def _write_deck(tmp_path):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(Deck(meta=DeckMeta(title="덱")).model_dump_json(), encoding="utf-8")
    return deck_path


def test_export_success(tmp_path, capsys):
    deck_path = _write_deck(tmp_path)
    rc = main(["export", str(deck_path), "--out", str(tmp_path / "exports")])
    assert rc == 0
    assert "내보내기 완료" in capsys.readouterr().out


def test_export_missing_file(tmp_path, capsys):
    rc = main(["export", str(tmp_path / "없는파일.json")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "찾을 수 없습니다" in err and "없는파일.json" in err


def test_export_broken_json(tmp_path, capsys):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text("{망가짐", encoding="utf-8")
    rc = main(["export", str(deck_path)])
    assert rc == 1
    assert "덱 파일을 읽지 못했습니다" in capsys.readouterr().err


def test_export_invalid_schema(tmp_path, capsys):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps({"meta": {}}), encoding="utf-8")
    rc = main(["export", str(deck_path)])
    assert rc == 1
    assert "덱 파일을 읽지 못했습니다" in capsys.readouterr().err


def test_export_out_dir_is_file(tmp_path, capsys):
    deck_path = _write_deck(tmp_path)
    blocker = tmp_path / "exports"
    blocker.write_text("파일임", encoding="utf-8")
    rc = main(["export", str(deck_path), "--out", str(blocker)])
    assert rc == 1
    assert "폴더" in capsys.readouterr().err


def test_serve_parser_defaults():
    # 서버를 띄우지 않고 인자 해석만 검증한다
    from slidecaptain.__main__ import build_parser

    args = build_parser().parse_args(["serve"])
    assert args.port == 8765
    assert args.data_dir.name == "slidecaptain-projects"
