"""작업 API의 요청과 응답 모델 (개정판 D2b-2, 계획서 5.9)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from slidecaptain.models.story import ReportBrief

JobState = Literal["queued", "running", "validating", "succeeded", "failed", "cancel_requested", "cancelled",
                   "interrupted", "remote_completion_unknown"]
CandidateStatus = Literal["none", "held", "delivered", "applied", "stale", "dismissed"]
ErrorClass = Literal["input", "ai_output", "connection", "base_changed", "cancelled", "ledger"]
# 요청 ID는 화면이 버튼을 누를 때 한 번 만든다. 사용자 입력이 아니므로 형식을 좁힌다
REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class StructureJobParams(BaseModel):
    target_chapters: int | None = Field(default=None, ge=1)
    instructions: str = ""
    brief: ReportBrief | None = None


class StructureJobRequest(BaseModel):
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)
    kind: Literal["structure"]
    params: StructureJobParams


JobRequest = StructureJobRequest  # D2b-3과 D2b-4가 종류를 구별 유니언으로 늘린다


class JobError(BaseModel):
    error_class: ErrorClass | None
    status: int | None
    detail: str | None
    code: str | None


class JobView(BaseModel):
    id: str
    project: str
    kind: str
    state: JobState
    candidate_status: CandidateStatus
    outcome: str | None
    owner: Literal["this_instance", "other_instance"]
    created_at: str
    started_at: str | None
    finished_at: str | None
    provider: str | None
    model: str | None
    base_etag: str | None
    current_etag: str | None
    # 결과가 있는 종결 작업에만 조회 때 계산한다. 덱이나 자료를 읽을 수 없으면 ["unknown"]
    stale_reasons: list[str]
    # 취소 요청을 받았는지. 임대 획득 중에는 상태가 아직 queued라 이 값으로 접수를 알린다 (D2b-2 리뷰 R4)
    cancel_requested: bool
    error: JobError | None
    result: dict[str, Any] | None


class ActiveJob(BaseModel):
    """서비스 전체에서 실행 중인 작업 하나의 요약. 409 generation_active 응답에도 같은 모양이 실린다."""

    id: str
    project: str
    kind: str
    target: str | None  # 장 ID나 도식 장. 구조안처럼 대상이 없으면 None
    cancel_requested: bool


class GenerationActiveBody(BaseModel):
    detail: str
    code: Literal["generation_active"]
    active: ActiveJob


class ActiveJobStatus(BaseModel):
    active: ActiveJob | None


class CandidateAction(BaseModel):
    action: Literal["applied", "dismissed"]
