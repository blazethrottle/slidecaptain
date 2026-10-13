"""작업 API의 요청과 응답 모델 (개정판 D2b-2, 계획서 5.9)."""

from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from slidecaptain.models.deck import Slide, Slots
from slidecaptain.models.render import CapacityWarning, RenderStyle, SlidePlan
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


# 후보의 낡음 사유. deck_changed_elsewhere는 알리기만 하고 반영을 막지 않는다(server/jobs.py의 NOTICE_REASONS)
StaleReason = Literal[
    "unknown_deck", "deck_changed", "unknown_sources", "sources_changed",
    "chapter_missing", "template_changed", "chapter_changed", "story_plan_changed",
    "structure_input_changed", "structure_applied_basis_changed", "deck_changed_elsewhere",
]


def _no_default(schema: dict) -> None:
    schema.pop("default", None)

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
    # 관련 입력 해시 (pipeline/relevance.py). 장과 축약은 "c1:템플릿|장 정의|구성 계획과 보고 정보", 구조안은
    # "s1:지시문 입력|반영 기준"(D3b-2). 표지가 없으면 이전 빌드가 쓴 행이다. 축약의 슬롯 비교는 화면이 한다
    relevance_hash: str | None
    # 결과가 있는 종결 작업에만 조회 때 계산한다. 덱이나 자료를 읽을 수 없으면 unknown_deck, unknown_sources.
    # 고정 목록이라 화면의 문구 표가 모든 값을 덮는지 타입 검사가 지킨다 (D3b-2, 리뷰 V9)
    stale_reasons: list[StaleReason]
    # 취소 요청을 받았는지. 임대 획득 중에는 상태가 아직 queued라 이 값으로 접수를 알린다 (D2b-2 리뷰 R4)
    cancel_requested: bool
    error: JobError | None
    result: dict[str, Any] | None
    chapters: list[ChapterView]  # 묶음이 아니면 빈 목록
    # 실행 단계: 아래 ActiveJob의 같은 세 칸과 뜻이 같다 (D3b-4, 계획 4.8)
    step: Literal["connecting", "generating", "retrying_format"] | None = Field(default=None, json_schema_extra=_no_default)
    step_started_at: str | None = Field(default=None, json_schema_extra=_no_default)
    elapsed_seconds: int | None = Field(default=None, json_schema_extra=_no_default)


class ActiveJob(BaseModel):
    """서비스 전체에서 실행 중인 작업 하나의 요약. 409 generation_active 응답에도 같은 모양이 실린다."""

    id: str
    project: str
    kind: str
    target: str | None  # 장 ID나 도식 장. 구조안처럼 대상이 없으면 None
    stage: Literal["queued", "running", "cancel_requested"]  # queued는 임대 대기
    created_at: str
    cancel_requested: bool
    # 실행 단계 (D3b-4, 계획 4.8). 단계는 이 실행기의 끝나지 않은 구조안 작업만, 경과 초는 이 실행기의 끝나지 않은
    # 모든 작업에 값이 있다(D3b-4 리뷰 R4). 경과 초는 등록 때부터 센 서버 값이다(화면은 이 값을 받은 뒤 스스로
    # 센다. 두 시계 차이로 값이 튀지 않게). 스키마에 기본값을 적지 않아 화면 타입에서 없을 수 있는 칸이 된다
    step: Literal["connecting", "generating", "retrying_format"] | None = Field(default=None, json_schema_extra=_no_default)
    step_started_at: str | None = Field(default=None, json_schema_extra=_no_default)
    elapsed_seconds: int | None = Field(default=None, json_schema_extra=_no_default)


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


class CandidateApplyRequest(BaseModel):
    """장 후보 적용과 미리 보기의 본문 (D3c-5, 계획 4.8). 칸을 비우면(null) 서버가 기본 선택을 쓴다: 다시 생성은 "직접 고친
    문구" 단위만 지금 문구, 장 축약은 모두 새 문구, 요소 수정은 길이가 바뀐 목록의 순번 요소만 지운다. 응답은 실제로 쓴 선택을
    돌려준다(계획 4.8에 없던 확장, D3c-5 기록)."""

    model_config = ConfigDict(extra="forbid")

    chapter_id: str | None = None  # 묶음 행이면 그 장. 단독 행은 비우거나 작업의 장과 같아야 한다
    keep_current: list[str] | None = None  # 지금 문구로 둘 반영 단위
    drop_edits: list[str] | None = None  # 지울 요소 수정의 열쇠
    unhide: list[str] | None = None  # 숨김을 풀 요소의 열쇠


class CandidateApplyPreview(BaseModel):
    """적용 미리 보기. 저장하지 않는다. 판정이 막아도 비교는 보이도록 200으로 돌려주고 blocked_reasons에 이유를 담는다."""

    job_id: str
    chapter_id: str
    kind: Literal["chapter", "condense"]
    base_etag: str  # 판정에 쓴 덱 ETag. 적용 요청의 If-Match로 보낸다
    blocked_reasons: list[str]  # 반영을 막는 이유(낡음 사유 목록의 값). 비면 반영할 수 있다
    notices: list[str]  # 막지 않고 알리기만 하는 이유(deck_changed_elsewhere)
    units: list[str]  # 이 템플릿의 반영 단위
    # 마지막으로 반영된 AI 결과와 지금 문구가 다른 단위. null이면 기준이 없어 표시하지 않는다(계획 4.1)
    edited_units: list[str] | None
    keep_current: list[str]  # 이 미리 보기에 쓴 선택
    drop_edits: list[str]
    unhide: list[str]
    length_changed_units: list[str]  # 새 내용의 항목 수가 다른 목록 단위
    current: Slide | None  # 지금 슬라이드. 장에 내용이 없으면 null
    merged: Slide | None  # 합친 슬라이드. 장이 없거나 템플릿이 바뀌어 합칠 수 없으면 null
    warnings: list[CapacityWarning]  # 합친 슬라이드의 분량과 글자 크기 경고
    removed_edits: list[str]  # 수정이 모두 사라지는 요소
    unhidden: list[str]  # 숨김이 풀리는 요소
    removed_spans: int  # 지워지는 부분 강조 수
    removed_chart: bool  # 비교 차트가 지워지는가
    already_applied: bool  # 지금 슬라이드가 합친 결과와 같다. 반영하면 덱을 다시 쓰지 않고 처분만 정리한다
    # 비교 화면의 좌우 미리보기 (D3c-6). 서버가 경고를 내려고 렌더한 계획을 함께 돌려준다. 보이는 것과 저장될 것이 같다
    page_width_pt: float
    page_height_pt: float
    style: RenderStyle
    current_plan: SlidePlan | None  # 지금 덱의 이 장. 내용이 없으면 null
    merged_plan: SlidePlan | None  # 합친 덱의 이 장. 합칠 수 없으면 null
