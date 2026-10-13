"""No-AI preflight for the exact in-memory inputs used by the exporter.

Capacity checks do not certify visual quality. Unimplemented checks remain
not_run, with zero evaluated items. Clients cannot supply a passing verdict.
"""

import hashlib
import json
import re

from slidecaptain.models.deck import Deck
from slidecaptain.models.direct_edit import EVIDENCE_KEYS, numeric_path_key, role_name
from slidecaptain.models.preset import Preset
from slidecaptain.models.report_purpose import output_dump
from slidecaptain.models.quality import QualityCheck, QualityReport
from slidecaptain.models.render import RenderPlan
from slidecaptain.pipeline.numeric_review import assess_numeric_review, numeric_fields

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


# 순번 배지는 표지 날짜, 구분 번호처럼 순서를 나타내는 숫자라 근거로 보지 않는다. 수치 검토의 대상은 그대로 둔다
# (α 리뷰 A5)
_ORDER_PATH = re.compile(r"^/slots/cards/\d+/badge$")


def _hidden_elements(deck: Deck) -> list[tuple[str, str, bool]]:
    """숨긴 요소(장 ID, 요소 열쇠, 근거 표시인가). 근거 표시는 각주와 표 묶음, 숫자가 든 칸이 있는 요소다 (D3c 계획 4.3, 4.6).

    숫자 칸은 수치 검토의 평가 항목이 아니라 숫자가 든 칸 전체로 정한다. 평가 항목은 구성 계획이 없거나 자료가 바뀌면
    비므로, 같은 숨김이 자료 상태에 따라 잡히기도 하고 빠지기도 했다 (D3c-2 리뷰 F2)."""
    paths: dict[str, list[str]] = {}
    for chapter_id, path, _ in numeric_fields(deck):
        if not _ORDER_PATH.match(path):
            paths.setdefault(chapter_id, []).append(path)
    found: list[tuple[str, str, bool]] = []
    for slide in deck.slides:
        hidden = [key for key, edit in slide.direct_edits.items() if edit.hidden]
        if not hidden:
            continue
        numeric_keys = {numeric_path_key(slide, path) for path in paths.get(slide.chapter_id, [])}
        found.extend((slide.chapter_id, key, key in EVIDENCE_KEYS or key in numeric_keys) for key in hidden)
    return found


def _places(deck: Deck, hidden: list[tuple[str, str]]) -> str:
    """사용자가 찾아갈 수 있게 장 번호와 장 제목, 우리말 요소 이름으로 적는다 (D3c-2 리뷰 F6)."""
    order = {chapter.id: (index, chapter) for index, chapter in enumerate(deck.structure.chapters, 1)}
    templates = {slide.chapter_id: slide.slots.template for slide in deck.slides}
    places = []
    for chapter_id in dict.fromkeys(chapter_id for chapter_id, _ in hidden):
        index, chapter = order[chapter_id]
        names = ", ".join(role_name(key, templates[chapter_id]) for c, key in hidden if c == chapter_id)
        places.append(f"{index}장{f' {chapter.topic}' if chapter.topic.strip() else ''}의 {names}")
    return "; ".join(places)


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
        "deck": output_dump(deck),  # 보고 목적 칸을 뺀다 (D3b-2, 재리뷰 RR4)
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
    # 직접 수정의 글자 크기 경고는 분량 넘침이 아니므로 용량 항목에 세지 않고 따로 보인다 (D3c-2 리뷰 F3)
    capacity = {s.chapter_id: [w for w in s.warnings if w.kind == "capacity"] for s in plan.slides}
    font_size = {s.chapter_id: [w for w in s.warnings if w.kind == "font_size"] for s in plan.slides}
    warning_chapters = [chapter_id for chapter_id, found in capacity.items() if found]
    warning_count = sum(len(found) for found in capacity.values())
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
    font_chapters = [chapter_id for chapter_id, found in font_size.items() if found]
    if font_chapters:
        # 글자 크기 경고가 있을 때만 넣는다. 수정값이 없는 덱의 보고는 그대로다
        count = sum(len(found) for found in font_size.values())
        checks.append(QualityCheck(
            name="font_size", status="failed", evaluated=count, failed=count, chapter_ids=font_chapters,
            detail=f"글자 크기 경고 {count}건입니다. 직접 수정에서 읽기 하한(본문 12pt, 각주 9pt) 아래로 줄였거나 "
                   "PowerPoint가 받는 범위로 맞춘 요소가 있습니다. 읽기에 문제가 없는지 확인해 주세요.",
        ))
    hidden_all = _hidden_elements(deck)
    hidden = [(chapter_id, key) for chapter_id, key, evidence in hidden_all if evidence]
    if hidden:
        # 숨긴 근거 표시가 있을 때만 넣는다. 늘 넣으면 대상 0인 통과가 되거나 모든 덱의 보고가 바뀐다 (D3c-2, 재리뷰 RR11)
        checks.append(QualityCheck(
            name="hidden_evidence", status="failed", evaluated=len(hidden), failed=len(hidden),
            chapter_ids=list(dict.fromkeys(chapter_id for chapter_id, _ in hidden)),
            detail=f"근거 표시(각주, 표, 숫자가 든 문구) {len(hidden)}개를 숨겼습니다: {_places(deck, hidden)}. "
                   "숨긴 채로 내보내도 되는지 확인해 주세요. 숨긴 문구는 계속 검토합니다.",
        ))
    others = [(chapter_id, key) for chapter_id, key, evidence in hidden_all if not evidence]
    if others:
        # 근거가 아닌 요소의 숨김은 자동 판정하지 않고 확인할 항목에 정보로만 보인다. 그래서 미수행으로 둔다 (계획 4.6,
        # α 리뷰 A6)
        checks.append(QualityCheck(
            name="hidden_elements", status="not_run", evaluated=0, failed=0,
            chapter_ids=list(dict.fromkeys(chapter_id for chapter_id, _ in others)),
            detail=f"숨긴 요소 {len(others)}개: {_places(deck, others)}. 내보낸 파일에 그리지 않았습니다.",
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
