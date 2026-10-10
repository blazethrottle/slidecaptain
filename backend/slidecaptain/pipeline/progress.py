"""단계 준비 모델 (개정판 D2a-6, 제품 설계 4절).

다섯 단계(보고 목적, 자료, 구성, 편집, 검토와 내보내기)의 상태를 저장본에서 계산한다. 현재 저장
계약으로 판정할 수 있는 것만 판정하고, 판정할 수 없는 것은 사유 코드로 남긴다. 기본값을 사용자가
확정한 값으로 표시하지 않는다. "변경이 저장됨" 같은 화면 쪽 상태는 화면이 보완한다. 화면 연결은 D3다.
"""

from typing import Any, Literal

from pydantic import BaseModel

from slidecaptain.models.jobs import JobView

from slidecaptain.pipeline.story import story_fingerprint

# 생성에 넣는 자료 합계의 상한 (단계 4 결정 14). server/app.py도 이 값을 쓴다
SOURCES_TOTAL_MAX_CHARS = 100_000

StageName = Literal["purpose", "sources", "structure", "editing", "review"]
StageState = Literal["not_started", "ready", "needs_review"]

# 사유 코드 (개정판 D3a-3, 계획 4.2). 고정 목록으로 두어 OpenAPI와 화면 타입에 나오게 하고, 화면 문구 표가
# 빠짐없이 덮는지 타입 검사로 확인한다. 조합 사유(artifact_, input_, review_)는 원천 상태 목록에서
# 준비됨에 해당하는 값을 뺀 것이다(export_history.py의 artifact_status와 input_status, export_reviews.py의
# 범주 상태). 원천 값이 늘면 이 목록에 없는 사유를 만들어 응답 검증이 실패하므로 시험이 먼저 깨진다
ProgressReason = Literal[
    "title_missing", "report_type_unconfirmed",
    "sources_unreadable", "sources_missing", "sources_over_limit", "extraction_review_unavailable",
    "chapters_missing", "plan_missing", "stale_story_plan",
    "chapters_unwritten",
    "no_export", "artifact_mismatch", "artifact_missing", "artifact_unreadable", "artifact_unverified",
    "input_stale", "input_legacy", "input_unavailable",
    "quality_needs_revision", "draft_checks_only",
    "review_records_unreadable", "manual_pass_not_final",
    "review_not_run", "review_needs_revision", "review_stale", "review_unavailable",
    "export_history_unreadable",
    # 검토와 내보내기 단계 수준 사유 (C20): 세 부분이 섞인 확인 필요 상태에서 준비되지 않은 부분
    "auto_checks_pending", "human_review_pending", "file_pending",
]


class ReviewPart(BaseModel):
    name: Literal["auto_checks", "human_review", "file"]
    state: StageState
    reasons: list[ProgressReason] = []


class StageProgress(BaseModel):
    stage: StageName
    state: StageState
    reasons: list[ProgressReason] = []
    written_chapters: int | None = None  # 편집 단계만 쓴다
    total_chapters: int | None = None
    parts: list[ReviewPart] | None = None  # 검토와 내보내기는 한 상태로 합치지 않는다


class ProjectProgress(BaseModel):
    project_status: Literal["ok", "needs_recovery", "newer_format", "unreadable_manifest"]
    stages: list[StageProgress] | None = None
    # 생성 작업과 장별 실패. D2b의 작업 원장이 채운다. 그 전까지 항상 null이다
    jobs: list[JobView] | None = None  # D2b-2가 원장으로 채운다. 화면 연결은 D3


def _purpose(deck) -> StageProgress:
    if not deck.meta.title.strip():
        return StageProgress(stage="purpose", state="not_started", reasons=["title_missing"])
    # 보고 유형은 기본값(research)과 사용자의 명시 선택을 구별할 기록이 없다(D3에서 다룬다)
    return StageProgress(stage="purpose", state="needs_review", reasons=["report_type_unconfirmed"])


def _sources(sources: dict[str, str] | None, sources_error: str | None) -> StageProgress:
    if sources is None:
        return StageProgress(stage="sources", state="needs_review", reasons=["sources_unreadable"])
    if not sources:
        return StageProgress(stage="sources", state="not_started", reasons=["sources_missing"])
    if sum(len(text) for text in sources.values()) > SOURCES_TOTAL_MAX_CHARS:
        return StageProgress(stage="sources", state="needs_review", reasons=["sources_over_limit"])
    # 부분 추출 경고와 이번 생성에 넣을 자료의 선택은 저장되지 않는다(D5)
    return StageProgress(stage="sources", state="ready", reasons=["extraction_review_unavailable"])


def _structure(deck, sources: dict[str, str] | None) -> StageProgress:
    chapters = deck.structure.chapters
    if not chapters:
        return StageProgress(stage="structure", state="not_started", reasons=["chapters_missing"])
    plan = deck.structure.story_plan
    if plan is None:
        return StageProgress(stage="structure", state="needs_review", reasons=["plan_missing"])
    if sources is None:
        return StageProgress(stage="structure", state="needs_review", reasons=["sources_unreadable"])
    # 생성 관문(require_current_story)과 같은 계약이다. 제목, 피보고자, 보고 유형, 장 제목과 결론,
    # 자료가 바뀌면 낡은 것으로 본다
    if plan.input_fingerprint != story_fingerprint(plan, deck.meta, chapters, sources):
        return StageProgress(stage="structure", state="needs_review", reasons=["stale_story_plan"])
    return StageProgress(stage="structure", state="ready")


def _editing(deck) -> StageProgress:
    ids = [c.id for c in deck.structure.chapters]
    written = len({s.chapter_id for s in deck.slides if s.chapter_id in ids})
    base = dict(stage="editing", written_chapters=written, total_chapters=len(ids))
    if not ids or written == 0:
        return StageProgress(**base, state="not_started")
    if written < len(ids):
        return StageProgress(**base, state="needs_review", reasons=["chapters_unwritten"])
    return StageProgress(**base, state="ready")


def _file_part(item) -> ReviewPart:
    if item is None:
        return ReviewPart(name="file", state="not_started", reasons=["no_export"])
    reasons = []
    if item.artifact_status != "matched":
        reasons.append(f"artifact_{item.artifact_status}")
    if item.input_status != "current":
        reasons.append(f"input_{item.input_status}")
    return ReviewPart(name="file", state="needs_review" if reasons else "ready", reasons=reasons)


def _auto_part(item) -> ReviewPart:
    if item is None or item.quality_status is None:
        return ReviewPart(name="auto_checks", state="not_started")
    if item.quality_status == "needs_revision":
        return ReviewPart(name="auto_checks", state="needs_review", reasons=["quality_needs_revision"])
    # 사전 점검을 통과한 초안이다. 의미와 시각 품질의 통과가 아니다
    return ReviewPart(name="auto_checks", state="ready", reasons=["draft_checks_only"])


def _human_part(reviews, reviews_error: str | None) -> ReviewPart:
    if reviews_error is not None:
        return ReviewPart(name="human_review", state="needs_review", reasons=["review_records_unreadable"])
    if reviews is None or all(c.status == "not_run" for c in reviews.categories):
        return ReviewPart(name="human_review", state="not_started")
    statuses = {c.status for c in reviews.categories}
    if statuses == {"passed"}:
        # 사람의 수동 통과 기록이다. 독립 검수나 제출 승인과 다르다(Q4a, Q4b)
        return ReviewPart(name="human_review", state="ready", reasons=["manual_pass_not_final"])
    return ReviewPart(name="human_review", state="needs_review",
                      reasons=sorted(f"review_{s}" for s in statuses - {"passed"}))


def _review(item, reviews, reviews_error, export_error) -> StageProgress:
    if export_error is not None:
        # 이력을 읽지 못했다. "아직 없음"으로 잘못 안내하지 않는다
        unreadable = ["export_history_unreadable"]
        parts = [ReviewPart(name="auto_checks", state="needs_review", reasons=unreadable),
                 ReviewPart(name="human_review", state="needs_review", reasons=unreadable),
                 ReviewPart(name="file", state="needs_review", reasons=unreadable)]
    else:
        parts = [_auto_part(item), _human_part(reviews, reviews_error), _file_part(item)]
    states = {p.state for p in parts}
    reasons: list = []
    if states == {"not_started"}:
        state: StageState = "not_started"
    elif states == {"ready"}:
        state = "ready"
    else:
        state = "needs_review"
        # 단계 목록은 단계 수준 사유로 무엇이 남았는지 말한다 (C20). 이력을 읽지 못하면 그 사유 하나만 둔다
        if export_error is not None:
            reasons = ["export_history_unreadable"]
        else:
            reasons = [f"{p.name}_pending" for p in parts if p.state != "ready"]
    return StageProgress(stage="review", state=state, reasons=reasons, parts=parts)


def project_progress(
    deck,
    *,
    sources: dict[str, str] | None,
    sources_error: str | None = None,
    latest_export=None,
    reviews=None,
    reviews_error: str | None = None,
    export_error: str | None = None,
) -> ProjectProgress:
    """저장본(덱, 자료, 최신 내보내기 기록 1건과 그 검수 기록)에서 단계 상태를 계산한다."""
    return ProjectProgress(project_status="ok", stages=[
        _purpose(deck),
        _sources(sources, sources_error),
        _structure(deck, sources),
        _editing(deck),
        _review(latest_export, reviews, reviews_error, export_error),
    ])
