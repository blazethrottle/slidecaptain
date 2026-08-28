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

    from slidecaptain.fonts.installer import ensure_fonts
    from slidecaptain.server.app import create_app
    from slidecaptain.storage.file_store import FileProjectStore

    try:
        if ensure_fonts() == "installed":
            print("Noto Sans KR 폰트를 사용자 계정에 설치했습니다. PowerPoint가 열려 있었다면 다시 시작해야 새 폰트가 보입니다.")
    except Exception as e:  # 설치 실패는 안내만 하고 계속 간다 (폭 계산은 번들 수치로 동작)
        print(f"폰트 자동 설치에 실패했습니다: {e}\n화면 표시가 다른 폰트로 대체될 수 있습니다. 수동 설치 파일: backend/slidecaptain/fonts/assets", file=sys.stderr)

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
