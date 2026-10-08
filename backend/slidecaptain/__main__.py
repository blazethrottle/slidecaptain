"""CLI.

- python -m slidecaptain export <deck.json> [--out DIR]
- python -m slidecaptain serve [--data-dir PATH] [--port N] [--model MODEL]
"""

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from slidecaptain.export.exporter import export_deck
from slidecaptain.pipeline.quality import QualityExportBlocked
from slidecaptain.storage.file_store import StorageError, load_source_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slidecaptain")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="deck.json을 PPTX로 내보낸다")
    p_export.add_argument("deck", type=Path)
    p_export.add_argument("--out", type=Path, default=None, help="내보내기 폴더 (기본: 덱 옆 exports/)")
    p_export.add_argument("--final", action="store_true", help="검수 통과를 요구한다 (현재는 검수 미구현으로 거절)")

    p_quality = sub.add_parser("quality", help="AI 호출 없이 사전 점검 결과를 JSON으로 출력한다")
    p_quality.add_argument("deck", type=Path)

    for command, help_text in (("qualification", "내보낸 파일의 현재 제출 조건을 확인한다"),
                               ("render-export", "Windows PowerPoint로 저장된 출력 전체를 렌더한다"),
                               ("import-review", "독립 검수자의 서명된 기록을 검증한다"),
                               ("publish-final", "검수한 PPTX와 같은 바이트를 제출본으로 게시한다")):
        cmd = sub.add_parser(command, help=help_text)
        cmd.add_argument("deck", type=Path)
        cmd.add_argument("export_id")
        cmd.add_argument("--trust", type=Path, default=None, help="등록된 독립 검수자 신뢰 설정 파일")
        if command != "qualification":
            cmd.add_argument("--basis", type=Path, required=True, help="확인한 qualification JSON (ETag/입력/출력 기준)")
        if command == "import-review":
            cmd.add_argument("--receipt", type=Path, required=True, help="서명된 검수 파일")

    p_pilot = sub.add_parser("pilot", help="동일 조건 비교를 눈가림 자료와 사람 판정 폼으로 준비한다")
    pilot_sub = p_pilot.add_subparsers(dest="pilot_command", required=True)
    prepare = pilot_sub.add_parser("prepare", help="비교 계획 JSON으로 새로운 비교 폴더를 만든다")
    prepare.add_argument("spec", type=Path)
    prepare.add_argument("--out", type=Path, required=True)
    report = pilot_sub.add_parser("report", help="사람 판정과 실패/보류를 그대로 집계한다")
    report.add_argument("folder", type=Path)
    report.add_argument("--evaluations", type=Path, default=None)

    p_serve = sub.add_parser("serve", help="로컬 API 서버를 연다 (127.0.0.1 전용)")
    p_serve.add_argument("--data-dir", type=Path, default=Path.home() / "slidecaptain-projects")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--provider", choices=["claude", "chatgpt"], default=None, help="AI 서비스 (저장된 설정 우선, 최초: claude)")
    p_serve.add_argument("--model", default=None, help="AI 생성 모델 (화면에서 선택 가능)")
    return parser


def _unsupported_project_format(deck_path) -> bool:
    """덱 파일이 프로젝트 폴더 안에 있고 그 형식 기록을 이 앱이 다룰 수 없으면 안내하고 True.

    CLI는 저장소를 거치지 않고 deck.json을 직접 읽으므로 같은 차단을 여기서 한다(D2a-1 리뷰 R3).
    프로젝트 폴더 밖의 덱 파일은 형식 기록이 없어 판정하지 않는다.
    """
    from slidecaptain.storage import project_format

    state = project_format.manifest_state(deck_path.resolve().parent)
    if state == "newer":
        print("이 프로젝트는 더 새 버전의 SlideCaptain이 만들었습니다. 이 버전에서는 열 수 없습니다. "
              "파일은 바꾸지 않았습니다.", file=sys.stderr)
        return True
    if state == "unreadable":
        print("이 프로젝트의 형식 기록 파일(manifest.json)을 읽지 못했습니다. 파일은 바꾸지 않았습니다.",
              file=sys.stderr)
        return True
    return False


def _run_export(args) -> int:
    if not args.deck.exists():
        print(f"덱 파일을 찾을 수 없습니다: {args.deck}", file=sys.stderr)
        return 1
    if _unsupported_project_format(args.deck):
        return 1
    out_dir = args.out if args.out is not None else args.deck.parent / "exports"
    if out_dir.exists() and not out_dir.is_dir():
        print(f"내보내기 위치가 폴더가 아닙니다: {out_dir}. 폴더 경로를 지정해 주세요.", file=sys.stderr)
        return 1
    try:
        result = export_deck(args.deck, out_dir, final=args.final)
    except QualityExportBlocked as e:
        print(str(e), file=sys.stderr)
        return 1
    except (OSError, StorageError) as e:
        print(f"내보내기를 수행하지 못했습니다: {e}", file=sys.stderr)
        return 1
    except (ValueError, ValidationError) as e:
        print(f"덱 파일을 읽지 못했습니다: {args.deck}\n원인: {e}", file=sys.stderr)
        return 1
    print(f"검수 전 초안 내보내기 완료: {result}")
    print(f"사전 점검 기록: {result.with_suffix('.quality.json')}")
    print("내용과 시각 품질은 검수되지 않았습니다. PPTX 생성 성공은 제출 승인과 다릅니다.")
    return 0


def _run_quality(args) -> int:
    from slidecaptain.layout.engine import build_render_plan
    from slidecaptain.metrics.font_metrics import FontMetrics
    from slidecaptain.models.deck import Deck
    from slidecaptain.models.preset import Preset, apply_overrides
    from slidecaptain.pipeline.quality import assess_quality

    if _unsupported_project_format(args.deck):
        return 1
    try:
        deck = Deck.model_validate_json(args.deck.read_text(encoding="utf-8"))
        preset = apply_overrides(Preset(), deck.meta.preset_overrides)
        sources = load_source_directory(args.deck.parent / "sources")
        plan = build_render_plan(deck, preset, FontMetrics.load_default(), sources=sources)
        report = assess_quality(deck, preset, plan, sources=sources)
    except (OSError, ValueError, StorageError) as e:
        print(f"사전 점검을 수행하지 못했습니다: {e}", file=sys.stderr)
        return 1
    print(report.model_dump_json(indent=2))
    # 2는 '아직 제출 가능하지 않음'이다. 실행 오류(1)와 구분한다.
    return 0 if report.final_export_allowed else 2


def _find_ui_dir() -> Path | None:
    """Prefer the wheel's UI, then a built frontend in a source checkout."""
    package_dir = Path(__file__).resolve().parent
    for directory in (package_dir / "ui", package_dir.parent.parent / "frontend" / "dist"):
        if (directory / "index.html").is_file():
            return directory
    return None


def _build_serve_app(data_dir: Path, model: str | None, provider: str | None = None, data_dir_lock: str = "none"):
    from slidecaptain.pipeline.connections import AIConnections, AISelection
    from slidecaptain.server.app import create_app
    from slidecaptain.storage.file_store import FileProjectStore

    ui_dir = _find_ui_dir()
    manager = AIConnections(data_dir / "ai-settings.json")
    if provider is not None or model is not None:
        chosen = provider or manager.selection.provider
        if model is None and chosen != manager.selection.provider:
            raise ValueError("서비스를 변경할 때 --model도 지정하거나 화면에서 서비스와 모델을 선택해 주세요.")
        manager.selection = AISelection(provider=chosen, model=model or manager.selection.model)
    return create_app(FileProjectStore(data_dir), ai_connections=manager, static_dir=ui_dir,
                      data_dir_lock=data_dir_lock)


def _run_serve(args) -> int:
    import uvicorn

    from slidecaptain.fonts.installer import _bundled_font_paths, ensure_fonts
    from slidecaptain.storage.service_lock import EXIT_DATA_DIR_IN_USE, DataDirInUse, acquire_service_lock

    # D2a-3: 폰트 설치나 설정 파일 같은 어떤 준비와 쓰기보다 먼저 자료 폴더 잠금을 얻는다.
    # lock은 서버가 끝날 때까지 이 함수가 쥐고 있다(프로세스가 끝나면 OS가 푼다)
    try:
        lock = acquire_service_lock(args.data_dir)
    except DataDirInUse as e:
        since = e.holder.get("started_at")
        print(str(e) + (f" (사용 중인 실행의 시작 시각: {since})" if since else ""), file=sys.stderr)
        return EXIT_DATA_DIR_IN_USE
    if lock.unsupported:
        print("이 자료 폴더는 파일 잠금을 지원하지 않아 잠금 없이 실행합니다. 같은 폴더로 SlideCaptain을 "
              "두 개 실행하지 마세요.", file=sys.stderr)

    # 태스크 D2-5: uvicorn은 루트 로거에 핸들러를 추가하지 않아, 이 호출이 없으면
    # subscription.py의 SDK 사용량 원시 로그(INFO)가 레코드조차 생성되지 않는다(실측).
    # 부수 효과로 SDK 동봉 CLI 안내("Using bundled Claude Code CLI: ...") 같은 다른
    # INFO 로그도 함께 보이지만 내용(프롬프트와 응답)은 아니다.
    logging.basicConfig(level=logging.INFO)

    try:
        if ensure_fonts() == "installed":
            print("Noto Sans KR 폰트를 사용자 계정에 설치했습니다. PowerPoint가 열려 있었다면 다시 시작해야 새 폰트가 보입니다.")
    except Exception as e:  # 설치 실패는 안내만 하고 계속 간다 (폭 계산은 번들 수치로 동작)
        assets_dir = _bundled_font_paths()[0].parent
        print(f"폰트 자동 설치에 실패했습니다: {e}\n화면 표시가 다른 폰트로 대체될 수 있습니다. 수동 설치 파일: {assets_dir}", file=sys.stderr)

    try:
        app = _build_serve_app(args.data_dir, args.model, args.provider, data_dir_lock=lock.state)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if _find_ui_dir() is None:
        print(
            "화면 파일이 아직 없어 API만 제공합니다. "
            "frontend 폴더에서 npm run build를 실행하면 화면이 함께 제공됩니다."
        )
    print(f"프로젝트 폴더: {args.data_dir}")
    print(f"서버 주소: http://127.0.0.1:{args.port} (이 PC에서만 접근 가능)")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        return _run_export(args)
    if args.command == "quality":
        return _run_quality(args)
    if args.command == "pilot":
        return _run_pilot(args)
    if args.command in ("qualification", "render-export", "import-review", "publish-final"):
        return _run_qualification(args)
    return _run_serve(args)


def _run_pilot(args):
    import json
    from slidecaptain.pipeline.blind_pilot import prepare_blind_pilot, read_blind_pilot_report
    try:
        if args.pilot_command == "prepare":
            folder = prepare_blind_pilot(json.loads(args.spec.read_text(encoding="utf-8")), args.out)
            print(f"비교 자료와 사람 판정 폼을 준비했습니다: {folder / 'index.html'}")
            print("실제 품질 판정은 수행하지 않았습니다. 원래 출력은 보존했습니다.")
        else:
            judgments = json.loads(args.evaluations.read_text(encoding="utf-8")) if args.evaluations else None
            print(json.dumps(read_blind_pilot_report(args.folder, judgments), ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"비교 기록을 처리하지 못했습니다: {exc}", file=sys.stderr)
        return 1


def _run_qualification(args):
    import json
    from slidecaptain.export.qualification import read_export_qualification, render_export, append_independent_review, publish_final
    from slidecaptain.export.reviews import ReviewInputs
    from slidecaptain.models.export_qualification import QualificationRequest, IndependentReviewRequest
    from slidecaptain.models.deck import Deck
    from slidecaptain.models.preset import Preset, apply_overrides
    from slidecaptain.metrics.font_metrics import FontMetrics
    from slidecaptain.layout.engine import build_render_plan
    from slidecaptain.pipeline.quality import assess_quality
    from slidecaptain.storage.file_store import FileProjectStore
    try:
        # Use the same project lock as the web application, then exports' OS lock.
        if args.deck.name != "deck.json":
            raise ValueError("제출 관문에는 프로젝트의 deck.json 경로를 지정해야 합니다.")
        store = FileProjectStore(args.deck.resolve().parent.parent)
        project = args.deck.resolve().parent.name
        with store.locked(project):
            # 형식 확인을 내보내기 폴더 쓰기보다 먼저 한다: 더 새 형식이면 여기서 거절된다 (D2a-1)
            store.deck_etag(project)
            def get_inputs():
                deck, etag = store.load_deck_with_etag(project)
                sources = load_source_directory(args.deck.resolve().parent / "sources")
                preset = apply_overrides(store.load_global_preset(), deck.meta.preset_overrides)
                plan = build_render_plan(deck, preset, FontMetrics.load_default(), sources=sources)
                quality = assess_quality(deck, preset, plan, sources=sources)
                return ReviewInputs(f'"{etag}"', quality.input_fingerprint, None)
            directory = args.deck.resolve().parent / "exports"
            trust = args.trust or store.root / "review-trust.json"
            if args.command == "qualification":
                result = read_export_qualification(directory, args.export_id, get_inputs(), trust)
            else:
                basis = json.loads(args.basis.read_text(encoding="utf-8"))
                request = {"expected_input_fingerprint": basis["input_fingerprint"], "expected_artifact_sha256": basis["artifact_sha256"]}
                etag = basis["base_etag"]
                if not etag:
                    raise ValueError("확인한 저장본의 기준이 없습니다.")
                if args.command == "import-review":
                    signed = json.loads(args.receipt.read_text(encoding="utf-8"))
                    result = append_independent_review(directory, args.export_id,
                        IndependentReviewRequest.model_validate({**signed, **request}), etag, get_inputs, trust)
                else:
                    operation = render_export if args.command == "render-export" else publish_final
                    result = operation(directory, args.export_id, QualificationRequest.model_validate(request), etag, get_inputs, trust)
            print(result.model_dump_json(indent=2))
            if args.command == "qualification":
                return 0 if result.final_export_allowed else 2
            if args.command == "render-export":
                return 0 if result.render_status == "rendered" else 2
            if args.command == "import-review":
                return 0 if result.independent_review_status == "passed" else 2
            return 0
    except (OSError, ValueError, StorageError, KeyError, TypeError) as exc:
        print(f"제출 조건을 처리하지 못했습니다: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
