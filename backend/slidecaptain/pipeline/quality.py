"""No-AI preflight for the exact in-memory inputs used by the exporter.

Capacity checks do not certify visual quality. Unimplemented checks remain
not_run, with zero evaluated items. Clients cannot supply a passing verdict.
"""

import hashlib
import json

from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset
from slidecaptain.models.quality import QualityCheck, QualityReport
from slidecaptain.models.render import RenderPlan
from slidecaptain.pipeline.numeric_review import assess_numeric_review

_NUMERIC_NOT_RUN = {
    "missing_plan": "보고 계획이 없어 대조하지 않았습니다.",
    "stale_plan": "자료나 보고 계획이 바뀌어 대조하지 않았습니다.",
    "evidence_mismatch": "원문 위치나 발췌가 현재 자료와 달라 대조하지 않았습니다.",
    "no_numeric_fields": "대조할 숫자가 포함된 텍스트 칸이 없습니다. 대상 0개는 통과가 아닙니다.",
    "no_computed_expressions": "연결할 계산 결과가 없어 대조하지 않았습니다.",
}


class QualityExportBlocked(ValueError):
    def __init__(self, report: QualityReport) -> None:
        self.report = report
        reason = (
            "내보낼 슬라이드가 없습니다. 구조안을 승인하고 내용을 생성해 주세요."
            if not report.draft_export_allowed
            else "완성본 내보내기를 허용할 수 없습니다. 내용과 시각 검수가 아직 구현되지 않았습니다. 검수 전 초안으로 내보내거나 검수 기능 구현 후 다시 시도해 주세요."
        )
        super().__init__(reason)


def assess_quality(
    deck: Deck, preset: Preset, plan: RenderPlan, *, sources: dict[str, str] | None = None,
) -> QualityReport:
    """Recompute checks for this draft and source snapshot, never client verdicts."""
    numeric = assess_numeric_review(deck, sources if sources is not None else {})
    render_input = plan.model_dump(mode="json")
    # 새 출력 전용 도식 필드가 비어 있으면 기존 preflight-v2 식별값을 유지한다.
    # 실제 도식이 있으면 전체 내용을 포함하며 무조건 제외하지 않는다.
    for slide in render_input["slides"]:
        if slide.get("diagram") is None:
            slide.pop("diagram", None)
    payload = {
        "gate_version": "preflight-v2",
        "deck": deck.model_dump(mode="json"),
        "preset": preset.model_dump(mode="json"),
        "render_plan": render_input,
        "numeric_review_fingerprint": numeric.input_fingerprint,
    }
    fingerprint = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    expected = [chapter.id for chapter in deck.structure.chapters]
    rendered = {slide.chapter_id for slide in plan.slides}
    missing = [chapter_id for chapter_id in expected if chapter_id not in rendered]
    warning_chapters = [slide.chapter_id for slide in plan.slides if slide.warnings]
    warning_count = sum(len(slide.warnings) for slide in plan.slides)
    checks = [
        QualityCheck(
            name="nonempty_output", status="passed" if plan.slides else "failed",
            evaluated=1, failed=0 if plan.slides else 1,
            detail="내보낼 슬라이드가 있는지 확인합니다. 내용의 충실도를 판정하지 않습니다.",
        ),
        QualityCheck(
            name="chapter_coverage",
            status=("failed" if missing else "passed") if expected else "not_run",
            evaluated=len(expected), failed=len(missing), chapter_ids=missing,
            detail="구조안의 장마다 생성된 슬라이드가 있는지 확인합니다.",
        ),
        QualityCheck(
            name="layout_capacity",
            status=("failed" if warning_chapters else "passed") if plan.slides else "not_run",
            evaluated=len(plan.slides), failed=len(warning_chapters),
            chapter_ids=warning_chapters,
            detail=f"용량 경고 {warning_count}건입니다. 폰트 대체, 실제 줄바꿈, 가독성 검수는 포함하지 않습니다.",
        ),
    ]
    checks.append(QualityCheck(
        name="numeric_expressions",
        status={"matched": "passed", "needs_review": "failed", "not_run": "not_run"}[numeric.status],
        evaluated=numeric.evaluated,
        failed=numeric.unresolved if numeric.evaluated else 0,
        chapter_ids=list(dict.fromkeys(item.chapter_id for item in numeric.items if item.code != "matched")),
        detail=(
            _NUMERIC_NOT_RUN[numeric.reason] if numeric.reason else
            f"숫자 포함 텍스트 칸 {numeric.evaluated}개 중 계산 문구 일치 {numeric.matched}개, "
            f"확인 필요 {numeric.unresolved}개입니다. 자유로운 문장의 의미는 검수하지 않았습니다."
        ),
    ))
    for name, detail in (
        ("narrative", "전체 보고 흐름, 요약과 본문의 정합성 검수를 수행하지 않았습니다."),
        ("evidence", "주장 전체의 근거 타당성과 원문 해석을 검수하지 않았습니다. 계산 문구 대조는 별도 항목입니다."),
        ("representation", "표, 차트, 도식의 적절성과 정보 위계 검수를 수행하지 않았습니다."),
        ("visual", "완성본 화면의 균형, 강조와 가독성 검수를 수행하지 않았습니다."),
        ("target_renderer", "목표 PowerPoint 환경의 실제 표시를 확인하지 않았습니다."),
    ):
        checks.append(QualityCheck(
            name=name, status="not_run", evaluated=0, failed=0, detail=detail,
        ))
    return QualityReport(
        status="needs_revision" if any(check.status == "failed" for check in checks) else "draft",
        input_fingerprint=fingerprint, slide_count=len(plan.slides),
        draft_export_allowed=bool(plan.slides), checks=checks, numeric_review=numeric,
    )


def require_export_allowed(report: QualityReport, *, final: bool = False) -> None:
    if not report.draft_export_allowed or (final and not report.final_export_allowed):
        raise QualityExportBlocked(report)
