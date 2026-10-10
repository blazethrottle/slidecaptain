"""작업 API의 요청과 응답 모델 (개정판 D2b-2, 계획서 5.9)."""

from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, Field, model_validator

from slidecaptain.models.deck import Slots
from slidecaptain.models.story import ReportBrief
from slidecaptain.pipeline.diagram_generation import GenerateDiagramRequest
from slidecaptain.pipeline.story_repair import StoryRepairRequest

JobState = Literal["queued", "running", "validating", "succeeded", "failed", "cancel_requested", "cancelled",
                   "interrupted", "remote_completion_unknown"]
CandidateStatus = Literal["none", "held", "delivered", "applied", "stale", "dismissed"]
# 원인 분류 (D2b-1, D3a-4). storage(저장과 적용 실패)와 internal(예기치 않은 오류)은 D3a-4가 더했다.
# 원장 쓰기 검사(storage/job_ledger.py의 ERROR_CLASSES)와 같은 집합이어야 한다(시험이 확인한다)
ErrorClass = Literal["input", "ai_output", "connection", "base_changed", "cancelled", "ledger", "storage", "internal"]
_ERROR_CLASSES = frozenset(get_args(ErrorClass))
# 요청 ID는 화면이 버튼을 누를 때 한 번 만든다. 사용자 입력이 아니므로 형식을 좁힌다
REQUEST_ID_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class StructureJobParams(BaseModel):
    target_chapters: int | None = Field(default=None, ge=1)
    instructions: str = ""
    brief: ReportBrief | None = None


class ChapterJobParams(BaseModel):
    chapter_id: str
    instructions: str = ""


class CondenseJobParams(BaseModel):
    chapter_id: str
    slots: Slots  # 화면이 들고 있는 현재 슬롯 (미저장 수정 포함. 설계 결정 13)
    instructions: str = ""


class RewriteJobParams(BaseModel):
    brief: ReportBrief
    instructions: str = Field(default="", max_length=8_000)


class ChaptersJobParams(BaseModel):
    """장 생성 묶음 (D2b-4). 화면이 승인 반영 PUT 뒤의 ETag를 If-Match로 주어 등록한다."""

    chapter_ids: list[str] = Field(min_length=1)


class _JobRequestBase(BaseModel):
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)


class StructureJobRequest(_JobRequestBase):
    kind: Literal["structure"]
    params: StructureJobParams


class ChapterJobRequest(_JobRequestBase):
    kind: Literal["chapter"]
    params: ChapterJobParams


class CondenseJobRequest(_JobRequestBase):
    kind: Literal["condense"]
    params: CondenseJobParams


class DiagramJobRequest(_JobRequestBase):
    kind: Literal["diagram"]
    params: GenerateDiagramRequest


class RewriteJobRequest(_JobRequestBase):
    kind: Literal["rewrite"]
    params: RewriteJobParams


class RepairJobRequest(_JobRequestBase):
    kind: Literal["repair"]
    params: StoryRepairRequest


class ChaptersJobRequest(_JobRequestBase):
    kind: Literal["chapters"]
    params: ChaptersJobParams


# 도식, 재작성, 수리, 장 생성 묶음은 If-Match 헤더로 기준 저장본을 받는다
JobRequest = Annotated[
    Union[StructureJobRequest, ChapterJobRequest, CondenseJobRequest, DiagramJobRequest, RewriteJobRequest,
          RepairJobRequest, ChaptersJobRequest],
    Field(discriminator="kind"),
]


class JobError(BaseModel):
    error_class: ErrorClass | None
    status: int | None
    detail: str | None
    code: str | None
    # 원장 행의 원인 분류가 이 빌드가 모르는 값이면(다른 빌드가 같은 자료 폴더에 쓴 값) internal로 읽고 원래 값을
    # 여기 남긴다. 모르는 값 한 행이 작업 조회, 작업 목록, 진행 API 전체를 500으로 만들지 않게 한다 (D3a-4, 사실 17)
    raw_error_class: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _tolerate_unknown_class(cls, data: Any) -> Any:
        if isinstance(data, dict):
            value = data.get("error_class")
            if value is not None and value not in _ERROR_CLASSES:
                return {**data, "error_class": "internal", "raw_error_class": str(value)}
        return data


class ChapterView(BaseModel):
    """장 생성 묶음의 장 하나 (D2b-4, α 묶음 리뷰 A8)."""

    chapter_id: str
    position: int
    state: JobState
    candidate_status: CandidateStatus
    error: JobError | None
    result: dict[str, Any] | None
    started_at: str | None
    finished_at: str | None


class JobView(BaseModel):
    id: str
    project: str
    kind: str
    state: JobState
    # 화면이 자기 대상의 후보를 고르는 데 쓴다(장 ID, 도식 장). 매개변수는 등록 때 보낸 값이다 (D2b-3 리뷰 R3)
    target: str | None
    params: dict[str, Any]
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
    # 장 재생성과 축약의 관련 입력 "템플릿|장 정의|구성 계획과 보고 정보"(계획서 5.8). 축약의 슬롯 비교는 화면이 한다
    relevance_hash: str | None
    # 결과가 있는 종결 작업에만 조회 때 계산한다. 덱이나 자료를 읽을 수 없으면 unknown_deck, unknown_sources
    stale_reasons: list[str]
    # 취소 요청을 받았는지. 임대 획득 중에는 상태가 아직 queued라 이 값으로 접수를 알린다 (D2b-2 리뷰 R4)
    cancel_requested: bool
    error: JobError | None
    result: dict[str, Any] | None
    chapters: list[ChapterView]  # 묶음이 아니면 빈 목록


class ActiveJob(BaseModel):
    """서비스 전체에서 실행 중인 작업 하나의 요약. 409 generation_active 응답에도 같은 모양이 실린다."""

    id: str
    project: str
    kind: str
    target: str | None  # 장 ID나 도식 장. 구조안처럼 대상이 없으면 None
    stage: Literal["queued", "running", "cancel_requested"]  # queued는 임대 대기
    created_at: str
    cancel_requested: bool


class GenerationActiveBody(BaseModel):
    detail: str
    code: Literal["generation_active"]
    active: ActiveJob


class ActiveJobStatus(BaseModel):
    active: ActiveJob | None
    # 원장을 열 수 없으면 거짓이다. 화면은 생성 버튼을 누르기 전에 안내를 보일 수 있다 (α 묶음 리뷰 A14)
    ledger_available: bool


class CandidateAction(BaseModel):
    action: Literal["applied", "dismissed"]
    # 묶음의 장 후보를 처분할 때 그 장 (D2b-4 리뷰 R5). 장 후보는 버리기만 한다
    chapter_id: str | None = None
