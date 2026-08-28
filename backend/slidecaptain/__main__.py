"""CLI.

- python -m slidecaptain export <deck.json> [--out DIR]
- python -m slidecaptain serve [--data-dir PATH] [--port N]
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from slidecaptain.export.exporter import export_deck


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slidecaptain")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="deck.json을 PPTX로 내보낸다")
    p_export.add_argument("deck", type=Path)
    p_export.add_argument("--out", type=Path, default=None, help="내보내기 폴더 (기본: 덱 옆 exports/)")

    p_serve = sub.add_parser("serve", help="로컬 API 서버를 연다 (127.0.0.1 전용)")
    p_serve.add_argument("--data-dir", type=Path, default=Path.home() / "slidecaptain-projects")
    p_serve.add_argument("--port", type=int, default=8765)
    return parser


def _run_export(args) -> int:
    if not args.deck.exists():
        print(f"덱 파일을 찾을 수 없습니다: {args.deck}", file=sys.stderr)
        return 1
    out_dir = args.out if args.out is not None else args.deck.parent / "exports"
    if out_dir.exists() and not out_dir.is_dir():
        print(f"내보내기 위치가 폴더가 아닙니다: {out_dir}. 폴더 경로를 지정해 주세요.", file=sys.stderr)
        return 1
    try:
        result = export_deck(args.deck, out_dir)
    except (ValueError, ValidationError) as e:
        print(f"덱 파일을 읽지 못했습니다: {args.deck}\n원인: {e}", file=sys.stderr)
        return 1
    print(f"내보내기 완료: {result}")
    return 0


def _run_serve(args) -> int:
    import uvicorn

    from slidecaptain.server.app import create_app
    from slidecaptain.storage.file_store import FileProjectStore

    app = create_app(FileProjectStore(args.data_dir))
    print(f"프로젝트 폴더: {args.data_dir}")
    print(f"서버 주소: http://127.0.0.1:{args.port} (이 PC에서만 접근 가능)")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        return _run_export(args)
    return _run_serve(args)


if __name__ == "__main__":
    sys.exit(main())
