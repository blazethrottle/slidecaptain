"""CLI: python -m slidecaptain export <deck.json> [--out <dir>]"""

import argparse
import sys
from pathlib import Path

from slidecaptain.export.exporter import export_deck


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slidecaptain")
    sub = parser.add_subparsers(dest="command", required=True)
    p_export = sub.add_parser("export", help="deck.json을 PPTX로 내보낸다")
    p_export.add_argument("deck", type=Path)
    p_export.add_argument("--out", type=Path, default=None, help="내보내기 폴더 (기본: 덱 옆 exports/)")
    args = parser.parse_args(argv)

    out_dir = args.out if args.out is not None else args.deck.parent / "exports"
    result = export_deck(args.deck, out_dir)
    print(f"내보내기 완료: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
