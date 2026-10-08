"""FastAPI 로컬 서버 (설계서 2.2). 저장소와 단계 1 코어를 조립만 한다.

실행은 CLI의 serve 서브커맨드가 담당하며 127.0.0.1 전용으로 바인딩한다 (로컬 웹앱).
"""

import asyncio
import hashlib
import hmac
import logging
import secrets
import threading
import time
import unicodedata
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urlparse

import anyio
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from slidecaptain import __version__
from slidecaptain.export.exporter import export_deck_data
from slidecaptain.export.locking import ExportBusyError
from slidecaptain.export.history import HistoryNotFound, HistoryReadError, read_export_history
from slidecaptain.export.reviews import (
    ReviewConflict, ReviewDeckConflict, ReviewInputs, ReviewPagesError,
    append_export_review, read_export_reviews,
)
from slidecaptain.models.export_history import ExportHistoryDetail, ExportHistoryPage
from slidecaptain.models.export_reviews import ExportReviewRequest, ExportReviews
from slidecaptain.models.export_qualification import (
    ExportQualification, FinalPublication, IndependentReviewRequest, QualificationRequest,
)
from slidecaptain.export.qualification import (
    QualificationConflict, QualificationDeckConflict, append_independent_review,
    publish_final, read_export_qualification, render_export,
)
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.layout.diagram_page import DiagramRenderBlocked
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, Slots
from slidecaptain.models.preset import Preset, apply_overrides
from slidecaptain.models.numeric_review import NumericReviewReport
from slidecaptain.pipeline.numeric_review import assess_numeric_review
from slidecaptain.models.semantic_review import SemanticSuspectReport
from slidecaptain.pipeline.semantic_review import assess_semantic_suspects
from slidecaptain.models.render import RenderPlan
from slidecaptain.pipeline.auth_status import LoginStatus, check_login
from slidecaptain.pipeline.connections import AIConnections, AISelection, AISettings, ConnectionConflict, LoginAttempt, ProviderId
from slidecaptain.pipeline.provider import AIProvider, ProviderError
from slidecaptain.pipeline.quality import QualityExportBlocked, assess_quality
from slidecaptain.models.quality import QualityReport
from slidecaptain.pipeline.service import ChapterResult, DiagramGenerationResult, DiagramGenerationUnsupported, GenerationService, StructureResult, StoryRewriteResult
from slidecaptain.pipeline.diagram_generation import GenerateDiagramRequest, diagram_prompt
from slidecaptain.pipeline.rewrite import ProtectedEvidenceChanged, rewrite_prompt, sources_fingerprint, validate_rewrite
from slidecaptain.pipeline.story_repair import StoryRepairRequest, StoryRepairResult, repair_story
from slidecaptain.models.document_changes import (
    DocumentChangeRequest, DocumentChangeApplyRequest, DocumentChangePreview,
    EvidenceMigrationRequest, EvidenceMigrationApplyRequest,
)
from slidecaptain.pipeline.document_changes import (
    evidence_fingerprint, preview_document_change, apply_document_change,
    preview_evidence_migration, apply_evidence_migration,
)
from slidecaptain.models.story import ChapterRole, ReportBrief
from slidecaptain.pipeline.story import StaleStoryPlan, reconcile_diagram_story_plan
from slidecaptain.sources.xlsx import XlsxTooLarge, XlsxUnreadable, extract_xlsx
from slidecaptain.pipeline.progress import SOURCES_TOTAL_MAX_CHARS, ProjectProgress, project_progress
from slidecaptain.storage.file_store import (
    DeckConflict,
    DraftInfo,
    DraftNotFound,
    DraftTooLarge,
    InvalidName,
    InvalidSourceEncoding,
    ProjectExists,
    ProjectFormatTooNew,
    ProjectManifestUnreadable,
    ProjectNotFound,
    ProjectInfo,
    ProjectStore,
    SnapshotInfo,
    SnapshotNotFound,
    SourceConflict,
    SourceNotFound,
    StorageError,
    decode_source_bytes,
    validate_name,
)

_LOG = logging.getLogger("slidecaptain.server.app")

_STATUS_BY_ERROR = [
    (InvalidName, 422),
    (InvalidSourceEncoding, 422),
    (ProjectNotFound, 404),
    (SnapshotNotFound, 404),
    (DraftNotFound, 404),
    (DraftTooLarge, 413),
    (SourceNotFound, 404),
    (ProjectExists, 409),
    (ProjectFormatTooNew, 409),  # 전용 처리기가 code를 붙인다. 목록에도 StorageError보다 앞에 둔다
    (DeckConflict, 412),  # StorageError보다 앞에 둔다: 목록은 첫 매치를 쓰므로 뒤에 두면 400으로 샌다
    (SourceConflict, 409),  # 마찬가지로 StorageError보다 앞에 둔다
    (StorageError, 400),
]

# 자료 전문이 프롬프트에 동봉되므로 상한을 명시한다 (단계 4 결정 14). 원본은 진행 모델과 같은 값이다
_SOURCES_TOTAL_MAX_CHARS = SOURCES_TOTAL_MAX_CHARS
_TEXT_UPLOAD_EXTENSIONS = {".md", ".txt", ".csv"}  # 업로드로 받는 텍스트 형식 (PDF와 Word는 단계 5 이월)
_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
_XLSX_UPLOAD_MAX_BYTES = 20 * 1024 * 1024  # 엑셀 원본은 텍스트보다 큰 것이 흔하다 (계획서 B2, 가정 4)
_XLSX_EXTRACT_SUFFIX = ".md"  # 추출본 이름: <원본 파일명>.md (설계서 3.1 정정)
_UPLOAD_TOO_LARGE_MESSAGE = "파일이 너무 큽니다(5MB 한도). 필요한 부분만 발췌해 주세요."
_XLSX_UPLOAD_TOO_LARGE_MESSAGE = "엑셀 파일이 너무 큽니다(20MB 한도). 필요한 부분만 발췌해 주세요."
_XLSX_FILENAME_TOO_LONG_MESSAGE = (
    # 추출본 이름은 <원본 파일명>.md 이고 이름 규칙 상한이 80자라, 원본이 78자 이상이면 추출본
    # 이름이 넘친다. 원본 이름 자체를 거절한다(계획서 B2). 72자는 확장자(.xlsx, 5자)를 뺀
    # 길이다: 문구에 이를 명시하지 않으면 확장자까지 포함해 72자로 줄여 필요 이상 짧아질 수
    # 있다 (B2 리뷰 F4)
    "파일 이름이 너무 깁니다. 확장자(.xlsx)를 빼고 72자 이내로 줄여 주세요."
)
_XLS_UNSUPPORTED_MESSAGE = "구버전 엑셀(xls)은 지원하지 않습니다. 엑셀에서 xlsx로 다시 저장해 주세요."
_UNSUPPORTED_EXTENSION_MESSAGE = (
    "지원하지 않는 형식입니다. 지금은 .md, .txt, .csv, .xlsx를 넣을 수 있고, "
    "PDF와 Word, 구버전 xls는 아직 지원하지 않습니다."
)
# 상태를 바꾸는 모든 /api/ 요청(POST, PUT, DELETE 등)은 이 값을 X-Requested-With로 보내야 한다
# (아래 상태 변경 요청 보호 미들웨어). 이 헤더는 브라우저의 단순 요청 허용 목록 밖이라, 다른 Origin의
# 페이지가 붙이면 사전 확인(OPTIONS)이 먼저 가고 이 서버는 CORS 헤더를 내지 않으므로 본 요청이 나가지
# 않는다 (2026-09-01 브랜치 최종 리뷰 반영. 2026-09-04 A2에서 업로드 전용 검사를 공통 미들웨어로 확장.
# TrustedHost는 Host만 보므로 이 경로를 막지 못한다)
_APP_HEADER_VALUE = "SlideCaptain"
_PROTECTION_MESSAGE = "이 요청은 Slide Captain 화면에서만 보낼 수 있습니다."
# AI 전송 고지 관문 (계획서 B3, 가정 5): 생성 3종(구조안, 장 생성과 재생성, 축약)은 이 헤더가 없으면
# 428로 거절한다. 이 검사는 화면 코드가 헤더 부착 자체를 잊는 사고만 막는 안전망이지, 헤더를
# 하드코딩해 동의 절차를 우회하는 코드 버그까지는 막지 못한다 (계획서 명시)
_AI_CONSENT_REQUIRED_MESSAGE = "AI 전송 확인이 필요합니다. 화면의 안내를 확인한 뒤 다시 시도해 주세요."
_ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost"}
_LOGIN_CACHE_SEC = 60.0  # 새로고침마다 CLI 프로세스를 띄우지 않는다

_VALIDATION_TYPE_MESSAGES = {
    "missing": "필수 값이 빠졌습니다",
    "greater_than_equal": "허용된 최솟값보다 작습니다",
    "string_type": "글자여야 합니다",
    "int_type": "정수여야 합니다",
    "bool_type": "참/거짓 값이어야 합니다",
    "list_type": "목록이어야 합니다",
    "model_type": "객체 형식이어야 합니다",
    "literal_error": "허용된 값이 아닙니다",
    "string_pattern_mismatch": "형식에 맞지 않습니다",
}


class CreateProjectRequest(BaseModel):
    name: str
    title: str = ""


class SourceText(BaseModel):
    text: str


class SaveDraftRequest(BaseModel):
    """충돌이나 저장 실패로 반영하지 못한 덱의 보존 요청 (D2a-2). 덱은 원문 그대로 보존하고
    복원할 때 검증한다."""

    reason: Literal["conflict", "generation_unsaved"]
    source: Literal["editor", "structure_approval"]
    base_etag: str | None = None
    deck: dict[str, Any]


class OkResponse(BaseModel):
    ok: bool = True


class UploadResult(BaseModel):
    filename: str
    chars: int
    # 엑셀 추출 요약(계획서 B2). 텍스트 업로드는 None/False/빈 목록을 채워 넣는다: 기본값을 주면
    # 필수가 아니게 되어 OpenAPI가 옵셔널로 내보내고 프런트가 undefined를 다뤄야 한다. 항상 채워
    # 보내므로 필드 자체는 필수로 둔다
    sheets: int | None
    cells: int | None
    truncated: bool
    notes: list[str]


class DataDirStatus(BaseModel):
    """자료 폴더 표시 (D2a-3, 기술 설계 3절의 "발견한 경로 제시"). 폴더를 바꾸는 화면은 D6이다."""

    path: str
    project_count: int
    # held: 이 서비스가 단일 서비스 잠금을 쥐었다. unsupported: 파일 시스템이 잠금을 지원하지 않아
    # 잠금 없이 실행 중이다. none: 잠금을 쓰지 않는 실행(시험, 내장 호출)
    lock: Literal["held", "unsupported", "none"]


class AppStatus(BaseModel):
    provider: Literal["subscription", "none", "claude", "chatgpt"]
    login: LoginStatus
    model: str | None = None
    selection_id: str | None = None
    last_generation_at: str | None = None  # 프로세스 메모리에만 기록, 재시작 시 초기화
    checked_at: str = Field(description="로그인 상태를 마지막으로 확인한 시각 (최대 60초 전 값일 수 있다)")
    data_dir: DataDirStatus | None = None


class ExportResult(BaseModel):
    path: str
    quality_path: str
    quality: QualityReport


class GenerateStructureRequest(BaseModel):
    target_chapters: int | None = Field(default=None, ge=1)
    instructions: str = ""
    brief: ReportBrief | None = None


class GenerateChapterRequest(BaseModel):
    instructions: str = ""


class CondenseChapterRequest(BaseModel):
    slots: Slots  # 화면이 들고 있는 현재 슬롯 (미저장 수정 포함. 설계 결정 13)
    instructions: str = ""


class ReconcileDiagramRequest(BaseModel):
    deck: Deck
    chapter_id: str
    role: ChapterRole
    claim_ids: list[str] = Field(min_length=1)


class RewriteStoryRequest(BaseModel):
    brief: ReportBrief
    instructions: str = Field(default="", max_length=8_000)


class ApplyStoryRewriteRequest(BaseModel):
    deck: Deck
    sources_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class DocumentChangeBasis(BaseModel):
    base_etag: str
    sources_fingerprint: str
    evidence_fingerprints: dict[str, str]


def _require_ai_consent(x_ai_consent: str | None) -> None:
    """생성 3종 라우트 공통 관문 (계획서 B3). 헤더가 없거나 값이 다르면 428로 거절한다."""
    if x_ai_consent != _APP_HEADER_VALUE:
        raise HTTPException(428, _AI_CONSENT_REQUIRED_MESSAGE)


def _validated_preset(deck: Deck, base: Preset | None = None) -> Preset:
    """덱의 preset_overrides를 검증해 프리셋을 만든다.

    사용자가 deck.json 파일을 직접 고쳐 PUT 검증을 우회한 경우에도
    render-plan과 export가 500 대신 같은 422로 답하게 한다.
    """
    try:
        return apply_overrides(base if base is not None else Preset(), deck.meta.preset_overrides)
    except ValidationError as e:
        first = e.errors()[0]["msg"]
        raise HTTPException(422, f"프리셋 덮어쓰기 값이 유효하지 않습니다: {first}")


def create_app(
    store: ProjectStore,
    provider: AIProvider | None = None,
    static_dir: Path | None = None,
    login_checker: Callable[[], LoginStatus] | None = None,
    ai_connections: AIConnections | None = None,
    desktop_session_token: str | None = None,
    desktop_instance_id: str | None = None,
    data_dir_lock: Literal["held", "unsupported", "none"] = "none",
) -> FastAPI:
    if desktop_session_token is not None or desktop_instance_id is not None:
        if (not isinstance(desktop_session_token, str) or len(desktop_session_token) != 64
                or any(c not in "0123456789abcdef" for c in desktop_session_token)
                or not isinstance(desktop_instance_id, str) or len(desktop_instance_id) != 32
                or any(c not in "0123456789abcdef" for c in desktop_instance_id)):
            raise ValueError("Invalid desktop session configuration")
    @asynccontextmanager
    async def lifespan(app):
        yield
        if ai_connections is not None:
            await asyncio.to_thread(ai_connections.close)

    app = FastAPI(title="Slide Captain", version=__version__, lifespan=lifespan)
    metrics = FontMetrics.load_default()  # 앱 수명 동안 1회 로드
    # requested_model은 프로바이더가 실제로 요청한 별칭이다(응답에 담긴 실제 모델과 다른 축.
    # 단계 5A 묶음 C 가정 1과 6, 태스크 C3). SubscriptionProvider 외의 프로바이더가 model 속성이
    # 없어도 getattr 기본값으로 안전하다.
    service = (
        GenerationService(provider, metrics, requested_model=getattr(provider, "model", None))
        if provider is not None
        else None
    )
    checker = login_checker or check_login
    # 앱 상태 (계획서 2026-09-01 태스크 4): 로그인 확인 캐시와 마지막 생성 성공 시각. 파일에 남기지 않는다
    status_state: dict = {"login": None, "login_at_mono": 0.0, "checked_at": "", "last_generation_at": None}
    generation_success: dict[tuple[str, str], str] = {}
    # Restart invalidates pending confirmations. Never expose/save signing keys.
    document_change_secret = secrets.token_bytes(32)
    status_lock = threading.Lock()  # 동기 라우트가 스레드풀에서 겹쳐도 CLI를 한 번만 띄운다

    @asynccontextmanager
    async def generation_service(selection_id):
        if ai_connections is None:
            yield _require_service()
            return
        lease = ai_connections.generation(selection_id)
        acquiring = asyncio.create_task(asyncio.to_thread(lease.__enter__))
        try:
            selected_provider = await asyncio.shield(acquiring)
        except asyncio.CancelledError:
            # Status checks run in a worker. Cancelling this request must not
            # leave a lease acquired later by that worker permanently busy.
            # Middleware's AnyIO scope repeats cancellation at await points;
            # asyncio.shield alone protects the worker, not this cleanup.
            with anyio.CancelScope(shield=True):
                try:
                    await asyncio.shield(acquiring)
                except Exception:
                    pass
                else:
                    await asyncio.to_thread(lease.__exit__, None, None, None)
            raise
        try:
            yield GenerationService(selected_provider, metrics, requested_model=ai_connections.selection.model)
        finally:
            with anyio.CancelScope(shield=True):
                await asyncio.to_thread(lease.__exit__, None, None, None)

    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _record_success(result) -> None:
        """구조안 생성, 장별 생성, 축약이 status == "ok"로 끝나면 마지막 성공 시각을 갱신한다."""
        if getattr(result, "status", None) == "ok":
            status_state["last_generation_at"] = _now_iso()
            if ai_connections is not None:
                selection = ai_connections.selection
                generation_success[(selection.provider, selection.model)] = status_state["last_generation_at"]

    def _append_usage(name: str, record) -> None:
        """생성 서비스의 on_usage 콜백 (단계 5A 묶음 C 태스크 C3, 가정 4와 5).

        기록 쓰기 실패는 사용자 관점에서 부가 기능이므로 경고 로그만 남기고 생성 결과를
        막지 않는다 (service._emit_usage도 콜백 예외를 삼키지만, 여기서도 한 번 더 잡아
        원인 위치가 분명한 로그를 남긴다).
        """
        try:
            store.append_usage(name, record.model_dump_json())
        except Exception:
            _LOG.warning("AI 사용량 기록(ai-usage.jsonl) 쓰기 실패: 프로젝트 %s", name, exc_info=True)

    # DNS 리바인딩 방지. testserver는 TestClient의 기본 Host라 허용한다 (브라우저가 보낼 수 없는 값)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def require_app_header(request: Request, call_next):
        """상태 변경 요청 보호 (계획서 A2, 가정 3). GET, HEAD, OPTIONS와 /api/ 밖 경로는 그대로 둔다.

        여기서 HTTPException을 던지지 않고 JSONResponse를 직접 돌려주는 이유: 사용자 미들웨어는
        예외 처리기(@app.exception_handler) 바깥에 있어 던지면 500이 된다 (적대 리뷰 실측).
        나중에 add_middleware로 등록한 것이 먼저 실행되므로, 이 미들웨어는 TrustedHostMiddleware보다
        바깥에서 돈다: 나쁜 Host와 헤더 없음이 겹치면 이 403이 먼저 나간다.
        """
        if desktop_session_token is not None:
            supplied = request.headers.get("x-slidecaptain-session", "")
            # Reject non-ASCII input before compare_digest (which accepts ASCII strings).
            if not supplied.isascii() or not hmac.compare_digest(supplied, desktop_session_token):
                return JSONResponse(status_code=403, content={"detail": "앱 실행 세션을 확인하지 못했습니다."})
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            if request.headers.get("x-requested-with") != _APP_HEADER_VALUE:
                return JSONResponse(status_code=403, content={"detail": _PROTECTION_MESSAGE})
            origin = request.headers.get("origin")
            if origin is not None and urlparse(origin).hostname not in _ALLOWED_ORIGIN_HOSTS:
                return JSONResponse(status_code=403, content={"detail": _PROTECTION_MESSAGE})
        response = await call_next(request)
        parts = request.url.path.split("/")
        is_history = len(parts) >= 5 and parts[1:3] == ["api", "projects"] and parts[4] == "exports"
        if desktop_session_token is not None or request.url.path == "/api/status" or request.url.path.startswith("/api/ai/") or is_history:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError):
        status = next(code for cls, code in _STATUS_BY_ERROR if isinstance(exc, cls))
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.exception_handler(ProjectFormatTooNew)
    async def project_format_error_handler(request, exc: ProjectFormatTooNew):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": exc.code})

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request, exc: ProviderError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(ConnectionConflict)
    async def connection_conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(QualityExportBlocked)
    @app.exception_handler(DiagramRenderBlocked)
    @app.exception_handler(DiagramGenerationUnsupported)
    async def quality_export_error_handler(request, exc: QualityExportBlocked):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(StaleStoryPlan)
    async def stale_story_handler(request, exc: StaleStoryPlan):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": "stale_story_plan"})

    @app.exception_handler(ProtectedEvidenceChanged)
    async def protected_evidence_error(request: Request, exc: ProtectedEvidenceChanged):
        return JSONResponse(status_code=409, content={"detail": str(exc), "code": "rewrite_protected_evidence"})

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request, exc: RequestValidationError):
        e = exc.errors()[0]
        if e["type"] == "value_error":
            # 모델 validator의 한국어 메시지를 그대로 살린다 (예: "구조안에 없는 장을 가리킵니다")
            message = str(e["msg"]).removeprefix("Value error, ")
        else:
            loc = ".".join(str(p) for p in e["loc"] if p != "body")
            message = f"{loc}: {_VALIDATION_TYPE_MESSAGES.get(e['type'], '입력 형식이 맞지 않습니다')}"
        return JSONResponse(status_code=422, content={"detail": message})

    def _preset_for(deck: Deck) -> Preset:
        return _validated_preset(deck, store.load_global_preset())

    def _require_service() -> GenerationService:
        if service is None:
            # 오류 문구는 비개발자가 수행할 수 있는 행동으로 (2026-08-28 적대 리뷰 반영)
            raise HTTPException(
                503, "AI 생성 기능을 사용할 수 없는 상태입니다. 앱을 다시 시작해 주세요."
            )
        return service

    def _load_sources(name: str, *, allow_empty: bool = False) -> dict[str, str]:
        files = store.list_sources(name)
        if not files and not allow_empty:
            raise HTTPException(
                422,
                "입력 자료가 없습니다. 자료 화면에서 파일을 추가하거나, "
                "프로젝트 폴더의 sources에 텍스트 파일을 넣어 주세요.",
            )
        texts = {f: store.read_source(name, f) for f in files}
        total = sum(len(t) for t in texts.values())
        if total > _SOURCES_TOTAL_MAX_CHARS:
            raise HTTPException(
                422,
                f"자료가 너무 큽니다(합계 {total:,}자, 한도 {_SOURCES_TOTAL_MAX_CHARS:,}자). "
                "필요한 부분만 발췌해 주세요.",
            )
        return texts

    @app.get("/api/preset", response_model=Preset)
    def get_preset():
        return store.load_global_preset()

    @app.put("/api/preset", response_model=OkResponse)
    def put_preset(preset: Preset):
        store.save_global_preset(preset)
        return OkResponse()

    @app.get("/api/projects", response_model=list[ProjectInfo])
    def list_projects():
        return store.list_projects()

    @app.post("/api/projects", response_model=ProjectInfo, status_code=201)
    def create_project(req: CreateProjectRequest):
        return store.create_project(req.name, req.title)

    @app.get("/api/projects/{name}/deck", response_model=Deck)
    def get_deck(name: str, response: Response):
        deck, etag = store.load_deck_with_etag(name)
        response.headers["ETag"] = f'"{etag}"'
        return deck

    @app.put("/api/projects/{name}/deck", response_model=OkResponse)
    def put_deck(
        name: str,
        deck: Deck,
        response: Response,
        snapshot: bool = True,
        if_match: str | None = Header(default=None),
    ):
        _preset_for(deck)
        expected_etag = if_match.strip('"') if if_match is not None else None
        etag = store.save_deck(name, deck, snapshot=snapshot, expected_etag=expected_etag)
        response.headers["ETag"] = f'"{etag}"'
        return OkResponse()

    @app.post("/api/projects/{name}/snapshots", response_model=OkResponse, status_code=201)
    def create_snapshot(name: str):
        store.snapshot_now(name)
        return OkResponse()

    @app.get("/api/projects/{name}/render-plan", response_model=RenderPlan)
    def get_render_plan(name: str):
        deck = store.load_deck(name)
        preset = _preset_for(deck)
        return build_render_plan(deck, preset, metrics, sources=_load_sources(name, allow_empty=True))

    @app.post("/api/projects/{name}/render-plan", response_model=RenderPlan)
    def measure_project_deck(name: str, deck: Deck):
        with store.locked(name):
            return build_render_plan(deck, _preset_for(deck), metrics, sources=_load_sources(name, allow_empty=True))

    @app.post("/api/render-plan", response_model=RenderPlan)
    def measure_deck(deck: Deck):
        """저장 없이 실측만 한다: 편집 중 미리보기와 분량 경고의 공급원 (단계 4 결정 2)."""
        preset = _preset_for(deck)
        return build_render_plan(deck, preset, metrics)

    @app.post("/api/projects/{name}/story-plan/diagram", response_model=Deck)
    def reconcile_diagram(
        name: str,
        req: ReconcileDiagramRequest,
        response: Response,
        if_match: str | None = Header(default=None),
    ):
        """도식 장과 기존 보고 계획을 확인만 한다. 저장과 AI 호출은 하지 않는다."""
        with store.locked(name):
            current, etag = store.load_deck_with_etag(name)
            expected_etag = if_match.strip('"') if if_match is not None else None
            if expected_etag is not None and expected_etag != etag:
                raise DeckConflict("다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요.")
            sources = _load_sources(name)
            try:
                reconciled = reconcile_diagram_story_plan(
                    req.deck, req.chapter_id, req.role, req.claim_ids, sources, base_deck=current,
                )
            except StaleStoryPlan:
                raise
            except ValidationError as exc:
                message = exc.errors(include_input=False, include_url=False)[0]["msg"]
                raise HTTPException(422, message.removeprefix("Value error, ")) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            response.headers["ETag"] = f'"{etag}"'
            return reconciled

    def _rewrite_base(name: str, if_match: str | None):
        if not if_match:
            raise HTTPException(428, "재작성 기준 저장본을 확인해야 합니다. 프로젝트를 다시 열어 주세요.")
        deck, etag = store.load_deck_with_etag(name)
        if if_match.strip('"') != etag:
            raise DeckConflict("다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요.")
        return deck, etag

    def _rewrite_invalid(exc: ValueError):
        if isinstance(exc, (ProtectedEvidenceChanged, StaleStoryPlan)):
            raise exc
        message = exc.errors(include_input=False, include_url=False)[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(422, message.removeprefix("Value error, ")) from exc

    def _document_basis(name: str, if_match: str | None, expected_sources: str | None = None):
        deck, etag = _rewrite_base(name, if_match)
        sources = _load_sources(name, allow_empty=True)
        revision = sources_fingerprint(sources)
        if expected_sources is not None and expected_sources != revision:
            raise HTTPException(409, "자료가 확인한 기준과 다릅니다. 입력을 보존하고 변경 기준을 다시 확인해 주세요.")
        project_scope = unicodedata.normalize("NFC", name).encode("utf-8")
        key = hmac.new(document_change_secret, b"document-change-project-v1\0" + project_scope, hashlib.sha256).digest()
        return deck, etag, sources, revision, key

    @app.get("/api/projects/{name}/document-changes/basis", response_model=DocumentChangeBasis)
    def get_document_change_basis(name: str, response: Response, if_match: str | None = Header(default=None)):
        with store.locked(name):
            deck, etag, sources, revision, key = _document_basis(name, if_match)
            response.headers["Cache-Control"] = "no-store"
            return DocumentChangeBasis(base_etag=f'"{etag}"', sources_fingerprint=revision,
                evidence_fingerprints={e.id: evidence_fingerprint(e) for e in deck.structure.story_plan.evidence}
                    if deck.structure.story_plan else {})

    def _check_document_render(candidate, sources):
        build_render_plan(candidate, _preset_for(candidate), metrics, sources=sources)

    def _check_document_sources(name, revision):
        if sources_fingerprint(_load_sources(name, allow_empty=True)) != revision:
            raise HTTPException(409, "변경 확인 중 자료가 바뀌었습니다. 후보를 보존하고 변경 기준을 다시 확인해 주세요.")

    @app.post("/api/projects/{name}/document-changes/preview", response_model=DocumentChangePreview)
    def preview_document(name: str, req: DocumentChangeRequest, if_match: str | None = Header(default=None)):
        with store.locked(name):
            base, etag, sources, revision, key = _document_basis(name, if_match, req.expected_source_fingerprint)
            try:
                result = preview_document_change(base, req.candidate, sources, key)
                _check_document_render(result.candidate, sources)
                _check_document_sources(name, revision)
                return result
            except ValueError as exc:
                _rewrite_invalid(exc)

    @app.post("/api/projects/{name}/document-changes/apply", response_model=Deck)
    def apply_document(name: str, req: DocumentChangeApplyRequest, response: Response, if_match: str | None = Header(default=None)):
        with store.locked(name):
            base, etag, sources, revision, key = _document_basis(name, if_match, req.expected_source_fingerprint)
            try:
                candidate = apply_document_change(base, req.candidate, sources, key, req.confirmation_token, req.acknowledged_loss_ids)
                _check_document_render(candidate, sources)
            except ValueError as exc:
                _rewrite_invalid(exc)
            _check_document_sources(name, revision)
            saved = store.save_deck(name, candidate, snapshot=True, expected_etag=etag)
            response.headers["ETag"] = f'"{saved}"'
            return candidate

    @app.post("/api/projects/{name}/evidence-migrations/preview", response_model=DocumentChangePreview)
    def preview_migration(name: str, req: EvidenceMigrationRequest, if_match: str | None = Header(default=None)):
        with store.locked(name):
            base, etag, sources, revision, key = _document_basis(name, if_match, req.expected_source_fingerprint)
            try:
                result = preview_evidence_migration(base, req, sources, key)
                _check_document_render(result.candidate, sources)
                _check_document_sources(name, revision)
                return result
            except ValueError as exc:
                _rewrite_invalid(exc)

    @app.post("/api/projects/{name}/evidence-migrations/apply", response_model=Deck)
    def apply_migration(name: str, req: EvidenceMigrationApplyRequest, response: Response, if_match: str | None = Header(default=None)):
        with store.locked(name):
            base, etag, sources, revision, key = _document_basis(name, if_match, req.expected_source_fingerprint)
            try:
                selection_request = EvidenceMigrationRequest.model_validate(req.model_dump(exclude={"confirmation_token", "acknowledged_loss_ids"}))
                candidate = apply_evidence_migration(base, selection_request, sources, key, req.confirmation_token, req.acknowledged_loss_ids)
                _check_document_render(candidate, sources)
            except ValueError as exc:
                _rewrite_invalid(exc)
            _check_document_sources(name, revision)
            saved = store.save_deck(name, candidate, snapshot=True, expected_etag=etag)
            response.headers["ETag"] = f'"{saved}"'
            return candidate

    @app.post("/api/projects/{name}/story-plan/rewrite", response_model=StoryRewriteResult)
    async def preview_story_rewrite(
        name: str, req: RewriteStoryRequest, if_match: str | None = Header(default=None),
        x_ai_consent: str | None = Header(default=None), x_ai_selection: str | None = Header(default=None),
    ):
        _require_ai_consent(x_ai_consent)
        with store.locked(name):
            deck, etag = _rewrite_base(name, if_match)
            sources = _load_sources(name, allow_empty=True)
            try:
                rewrite_prompt(deck, req.brief, sources, req.instructions)
            except ValueError as exc:
                _rewrite_invalid(exc)
            revision = sources_fingerprint(sources)
        # threading.RLock을 AI await 너머로 유지하지 않는다.
        async with generation_service(x_ai_selection) as svc:
            result = await svc.rewrite_story(deck, req.brief, sources, req.instructions,
                                            on_usage=lambda rec: _append_usage(name, rec))
            with store.locked(name):
                _rewrite_base(name, etag)
                if sources_fingerprint(_load_sources(name, allow_empty=True)) != revision:
                    raise HTTPException(409, "재작성 중 자료가 바뀌었습니다. 현재 자료로 다시 작성해 주세요.")
            _record_success(result)
        result.base_etag = f'"{etag}"'
        result.sources_fingerprint = revision
        return result

    @app.post("/api/projects/{name}/story-plan/rewrite/apply", response_model=Deck)
    def apply_story_rewrite(
        name: str, req: ApplyStoryRewriteRequest, response: Response,
        if_match: str | None = Header(default=None),
    ):
        with store.locked(name):
            base, etag = _rewrite_base(name, if_match)
            sources = _load_sources(name, allow_empty=True)
            if sources_fingerprint(sources) != req.sources_fingerprint:
                raise HTTPException(409, "미리보기 이후 자료가 바뀌었습니다. 현재 자료로 다시 작성해 주세요.")
            try:
                validate_rewrite(base, req.deck, sources)
                _preset_for(req.deck)
            except ValueError as exc:
                _rewrite_invalid(exc)
            saved = store.save_deck(name, req.deck, snapshot=True, expected_etag=etag)
            response.headers["ETag"] = f'"{saved}"'
            return req.deck

    @app.post("/api/projects/{name}/story-plan/repair", response_model=StoryRepairResult)
    async def preview_story_repair(
        name: str, req: StoryRepairRequest, request: Request,
        if_match: str | None = Header(default=None),
        x_ai_consent: str | None = Header(default=None), x_ai_selection: str | None = Header(default=None),
    ):
        _require_ai_consent(x_ai_consent)
        with store.locked(name):
            deck, etag = _rewrite_base(name, if_match)
            sources = _load_sources(name)
            try:
                rewrite_prompt(deck, req.brief, sources, req.instructions)
            except ValueError as exc:
                _rewrite_invalid(exc)
            revision = sources_fingerprint(sources)
        cancelled = [False]
        def unchanged():
            try:
                with store.locked(name):
                    current, current_etag = store.load_deck_with_etag(name)
                    return current_etag == etag and sources_fingerprint(_load_sources(name)) == revision and (
                        ai_connections is None or ai_connections.selection_id == x_ai_selection)
            except (StorageError, HTTPException):
                return False
        async with generation_service(x_ai_selection) as svc:
            running = asyncio.create_task(repair_story(deck, sources, req, svc._provider, metrics,
                base_etag=f'"{etag}"', source_revision=revision, unchanged=unchanged,
                cancelled=lambda: cancelled[0], on_usage=lambda rec: _append_usage(name, rec)))
            async def watch_disconnect():
                while not running.done():
                    if await request.is_disconnected():
                        cancelled[0] = True
                        running.cancel()
                        return
                    await asyncio.sleep(0.2)
            watcher = asyncio.create_task(watch_disconnect())
            try:
                result = await running
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            # A late change cannot make an old candidate applicable. Keep it for review.
            if not unchanged() and result.status != "stopped":
                result.status = "stopped"
                result.reason = "기준 저장본·자료·모델 선택이 바뀌었습니다. 후보를 적용하지 마세요."
            return result

    @app.post("/api/projects/{name}/export", response_model=ExportResult)
    def export_project(name: str, final: bool = False):
        # 이 프로세스의 편집과 입력 읽기를 직렬화한다. 웹/CLI 간 버전 선택과
        # 두 파일 게시의 공통 잠금은 exporter가 맡는다. 잠금 순서를 뒤집지 않는다.
        with store.locked(name):
            deck = store.load_deck(name)
            _preset_for(deck)  # 내보내기 전에 overrides부터 검증한다 (파일 직접 수정 대비)
            sources = {filename: store.read_source(name, filename) for filename in store.list_sources(name)}
            try:
                path = export_deck_data(
                    deck, store.exports_dir(name), global_preset=store.load_global_preset(),
                    final=final, sources=sources,
                )
            except ExportBusyError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except OSError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="내보내기 파일을 저장하지 못했습니다. 출력 폴더의 권한과 여유 공간을 확인하고 "
                           "문제가 계속되면 로컬 디스크의 다른 폴더에서 다시 시도해 주세요.",
                ) from exc
            quality_path = path.with_suffix(".quality.json")
            quality = QualityReport.model_validate_json(quality_path.read_text(encoding="utf-8"))
        return ExportResult(path=str(path), quality_path=str(quality_path), quality=quality)

    @app.get("/api/projects/{name}/snapshots", response_model=list[SnapshotInfo])
    def list_snapshots(name: str):
        return store.list_snapshots(name)

    def _export_history(name: str, *, export_id: str | None = None, offset: int = 0, limit: int = 20):
        with store.locked(name):
            directory = store.export_history_dir(name)
            fingerprint = error = None
            try:
                deck = store.load_deck(name)
                preset = apply_overrides(store.load_global_preset(), deck.meta.preset_overrides)
                sources = {filename: store.read_source(name, filename) for filename in store.list_sources(name)}
                plan = build_render_plan(deck, preset, metrics, sources=sources)
                fingerprint = assess_quality(deck, preset, plan, sources=sources).input_fingerprint
            except (StorageError, OSError, ValueError):
                error = "현재 저장된 덱, 프리셋 또는 자료를 읽지 못해 현재 입력과 대조하지 못했습니다. 과거 기록은 그대로 표시합니다."
            try:
                return read_export_history(
                    directory, current_fingerprint=fingerprint, current_error=error,
                    export_id=export_id, offset=offset, limit=limit,
                )
            except HistoryNotFound as exc:
                raise HTTPException(404, str(exc)) from exc
            except HistoryReadError as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.get("/api/projects/{name}/exports", response_model=ExportHistoryPage)
    def list_export_history(name: str, response: Response, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        response.headers["Cache-Control"] = "no-store"
        return _export_history(name, offset=offset, limit=limit)

    @app.get("/api/projects/{name}/exports/{export_id}", response_model=ExportHistoryDetail)
    def get_export_history(name: str, export_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return _export_history(name, export_id=export_id)

    def _review_inputs(name: str) -> ReviewInputs:
        # ETag and fingerprint come from the same loaded Deck, under the caller's
        # project lock. Broken current inputs never hide immutable review history.
        base_etag = None
        try:
            deck, etag = store.load_deck_with_etag(name)
            base_etag = f'"{etag}"'
            preset = apply_overrides(store.load_global_preset(), deck.meta.preset_overrides)
            sources = {filename: store.read_source(name, filename) for filename in store.list_sources(name)}
            plan = build_render_plan(deck, preset, metrics, sources=sources)
            fingerprint = assess_quality(deck, preset, plan, sources=sources).input_fingerprint
            return ReviewInputs(base_etag, fingerprint, None)
        except (StorageError, OSError, ValueError):
            return ReviewInputs(base_etag, None, "현재 저장된 덱, 프리셋 또는 자료를 읽지 못해 검수 기준을 확인하지 못했습니다. 과거 기록은 그대로 표시합니다.")

    @app.get("/api/projects/{name}/exports/{export_id}/reviews", response_model=ExportReviews)
    def get_export_reviews(name: str, export_id: str):
        with store.locked(name):
            directory = store.export_history_dir(name)
            try:
                return read_export_reviews(directory, export_id, _review_inputs(name))
            except HistoryNotFound as exc:
                raise HTTPException(404, str(exc)) from exc
            except HistoryReadError as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.get("/api/projects/{name}/progress", response_model=ProjectProgress)
    def get_progress(name: str):
        """단계 준비 상태 (D2a-6). 복구 필요와 더 새 형식도 200으로 상태를 돌려준다. 화면 연결은 D3다."""
        try:
            deck = store.load_deck(name)
        except ProjectManifestUnreadable:
            return ProjectProgress(project_status="unreadable_manifest")
        except ProjectFormatTooNew:
            return ProjectProgress(project_status="newer_format")
        except ProjectNotFound:
            if any(p.name == unicodedata.normalize("NFC", name) and p.status == "needs_recovery"
                   for p in store.list_projects()):
                return ProjectProgress(project_status="needs_recovery")
            raise
        except StorageError:
            return ProjectProgress(project_status="needs_recovery")
        sources: dict[str, str] | None
        sources_error = None
        try:
            sources = {f: store.read_source(name, f) for f in store.list_sources(name)}
        except (StorageError, OSError) as exc:
            sources, sources_error = None, str(exc)
        item = reviews = None
        reviews_error = export_error = None
        try:
            page = _export_history(name, limit=1)  # 최신 기록 1건만 읽는다(전체 이력의 파일 해시를 다시 계산하지 않는다)
            item = page.items[0] if page.items else None
        except (HTTPException, StorageError, OSError) as exc:
            export_error = str(exc)
        if item is not None:
            try:
                with store.locked(name):
                    reviews = read_export_reviews(store.export_history_dir(name), item.id, _review_inputs(name))
            except (HTTPException, StorageError, OSError, ValueError) as exc:
                reviews_error = str(exc)
        return project_progress(deck, sources=sources, sources_error=sources_error, latest_export=item,
                                reviews=reviews, reviews_error=reviews_error, export_error=export_error)

    @app.post("/api/projects/{name}/exports/{export_id}/reviews", response_model=ExportReviews)
    def create_export_review(
        name: str, export_id: str, req: ExportReviewRequest, if_match: str | None = Header(default=None),
    ):
        if if_match is None:
            raise HTTPException(428, "검수를 시작한 덱의 기준이 필요합니다. 검수 기록을 다시 조회해 주세요.")
        # Lock order matches export: project first, cross-process output lock next.
        with store.locked(name):
            directory = store.export_history_dir(name)
            try:
                return append_export_review(directory, export_id, req, if_match, lambda: _review_inputs(name))
            except HistoryNotFound as exc:
                raise HTTPException(404, str(exc)) from exc
            except ReviewDeckConflict as exc:
                raise HTTPException(412, str(exc)) from exc
            except ReviewPagesError as exc:
                raise HTTPException(422, str(exc)) from exc
            except HistoryReadError as exc:
                # Invalid path syntax is a validation error; unsafe stored files
                # also fail closed without returning local path or OS details.
                raise HTTPException(422, str(exc)) from exc
            except (ReviewConflict, ExportBusyError) as exc:
                raise HTTPException(409, str(exc)) from exc
            except OSError as exc:
                raise HTTPException(409, "검수 기록을 안전하게 저장하지 못했습니다. 입력을 보존한 뒤 다시 조회해 주세요.") from exc

    def _qualification_trust_path():
        root = getattr(store, 'root', None)
        return Path(root) / 'review-trust.json' if root is not None else None

    def _qualification_action(name, export_id, action, request=None, if_match=None):
        if request is not None and if_match is None:
            raise HTTPException(428, '검수를 시작한 덱의 기준이 필요합니다. 제출 관문을 다시 조회해 주세요.')
        with store.locked(name):
            directory = store.export_history_dir(name)
            try:
                if request is None:
                    return read_export_qualification(directory, export_id, _review_inputs(name), _qualification_trust_path())
                return action(directory, export_id, request, if_match, lambda: _review_inputs(name), _qualification_trust_path())
            except HistoryNotFound as exc:
                raise HTTPException(404, str(exc)) from exc
            except QualificationDeckConflict as exc:
                raise HTTPException(412, str(exc)) from exc
            except (QualificationConflict, ExportBusyError) as exc:
                raise HTTPException(409, str(exc)) from exc
            except HistoryReadError as exc:
                raise HTTPException(422, str(exc)) from exc
            except OSError as exc:
                raise HTTPException(409, '제출 증거를 안전하게 저장하지 못했습니다. 입력을 보존한 뒤 다시 조회해 주세요.') from exc

    @app.get('/api/projects/{name}/exports/{export_id}/qualification', response_model=ExportQualification)
    def get_qualification(name: str, export_id: str):
        return _qualification_action(name, export_id, None)

    @app.post('/api/projects/{name}/exports/{export_id}/render', response_model=ExportQualification)
    def create_native_render(name: str, export_id: str, req: QualificationRequest, if_match: str | None = Header(default=None)):
        return _qualification_action(name, export_id, render_export, req, if_match)

    @app.post('/api/projects/{name}/exports/{export_id}/independent-reviews', response_model=ExportQualification)
    def create_independent_review(name: str, export_id: str, req: IndependentReviewRequest, if_match: str | None = Header(default=None)):
        return _qualification_action(name, export_id, append_independent_review, req, if_match)

    @app.post('/api/projects/{name}/exports/{export_id}/publish-final', response_model=FinalPublication)
    def create_final_publication(name: str, export_id: str, req: QualificationRequest, if_match: str | None = Header(default=None)):
        return _qualification_action(name, export_id, publish_final, req, if_match)

    @app.post("/api/projects/{name}/snapshots/{snapshot_id}/restore", response_model=Deck)
    def restore_snapshot(
        name: str,
        snapshot_id: str,
        response: Response,
        if_match: str | None = Header(default=None),
    ):
        expected_etag = if_match.strip('"') if if_match is not None else None
        deck, etag = store.restore_snapshot(name, snapshot_id, expected_etag=expected_etag)
        response.headers["ETag"] = f'"{etag}"'
        return deck

    @app.post("/api/projects/{name}/drafts", response_model=DraftInfo, status_code=201)
    def save_draft(name: str, req: SaveDraftRequest):
        base = req.base_etag.strip('"') if req.base_etag is not None else None
        return store.save_draft(name, deck=req.deck, reason=req.reason, source=req.source, base_etag=base)

    @app.get("/api/projects/{name}/drafts", response_model=list[DraftInfo])
    def list_drafts(name: str):
        return store.list_drafts(name)

    @app.post("/api/projects/{name}/drafts/{draft_id}/restore", response_model=Deck)
    def restore_draft(
        name: str,
        draft_id: str,
        response: Response,
        if_match: str | None = Header(default=None),
    ):
        expected_etag = if_match.strip('"') if if_match is not None else None
        deck, etag = store.restore_draft(name, draft_id, expected_etag=expected_etag)
        response.headers["ETag"] = f'"{etag}"'
        return deck

    @app.delete("/api/projects/{name}/drafts/{draft_id}", response_model=OkResponse)
    def delete_draft(name: str, draft_id: str):
        store.delete_draft(name, draft_id)
        return OkResponse()

    @app.get("/api/projects/{name}/sources", response_model=list[str])
    def list_sources(name: str):
        return store.list_sources(name)

    @app.get("/api/projects/{name}/sources/{filename}", response_model=SourceText)
    def read_source(name: str, filename: str):
        return SourceText(text=store.read_source(name, filename))

    @app.put("/api/projects/{name}/sources/{filename}", response_model=OkResponse)
    def write_source(name: str, filename: str, body: SourceText):
        store.write_source(name, filename, body.text)
        return OkResponse()

    @app.post("/api/projects/{name}/sources/{filename}/upload", response_model=UploadResult)
    async def upload_source(
        name: str,
        filename: str,
        request: Request,
        overwrite: bool = False,
    ):
        """파일 본문을 원시 바이트로 받아 저장한다 (계획서 2026-09-01 태스크 2, 2026-09-04 B2로 XLSX 확장).

        텍스트(.md/.txt/.csv)는 UTF-8로 해석해 sources/에만 저장한다. XLSX는 원본을 uploads/에
        그대로 보존하고, openpyxl로 추출한 UTF-8 텍스트를 sources/<원본 파일명>.md 로 저장한다
        (설계서 3.1, 가정 1). 멀티파트를 쓰지 않는 이유: 파일 1개씩만 받으므로 원시 본문이면
        충분하고, 파싱 의존성이 필요 없다. 표식 헤더 검사는 A2에서 공통 미들웨어로 옮겨 여기서는
        하지 않는다.
        """
        # 브라우저나 OS가 붙인 경로 조각은 벗기고 이름만 쓴다 (Windows 역슬래시 포함, OS 무관하게 처리)
        filename = PureWindowsPath(filename).name
        suffix = Path(filename).suffix.lower()
        if suffix == ".xls":
            raise HTTPException(422, _XLS_UNSUPPORTED_MESSAGE)
        is_xlsx = suffix == ".xlsx"
        if not is_xlsx and suffix not in _TEXT_UPLOAD_EXTENSIONS:
            raise HTTPException(422, _UNSUPPORTED_EXTENSION_MESSAGE)

        if is_xlsx:
            # macOS Finder가 주는 NFD(자모 분리) 한글 파일명도 다른 이름 처리 진입점(A4)과 같은
            # 관례로 여기서 NFC(완성형)로 맞춘다: 정규화 전에 아래 길이와 패턴 검사를 하면 코드
            # 포인트 수가 늘어나 실제로는 규칙 이내인 이름이 잘못 거절된다 (계획서 B2 리뷰 F2)
            filename = unicodedata.normalize("NFC", filename)
        extract_name = filename + _XLSX_EXTRACT_SUFFIX if is_xlsx else None
        # 두 이름(원본, 추출본)을 먼저 계산하고 검증한다: 무거운 추출(openpyxl)을 시작하기 전에
        # 이름 규칙 위반(정규식, Windows 예약어 등)과 추출본 이름 80자 상한을 모두 거절한다
        # (계획서 B2, 리뷰 F3)
        if is_xlsx:
            validate_name(filename, "자료 파일")
            if len(extract_name) > 80:
                raise HTTPException(422, _XLSX_FILENAME_TOO_LONG_MESSAGE)

        max_bytes = _XLSX_UPLOAD_MAX_BYTES if is_xlsx else _UPLOAD_MAX_BYTES
        too_large_message = _XLSX_UPLOAD_TOO_LARGE_MESSAGE if is_xlsx else _UPLOAD_TOO_LARGE_MESSAGE
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            raise HTTPException(422, too_large_message)
        data = await request.body()
        if len(data) > max_bytes:
            raise HTTPException(422, too_large_message)

        if is_xlsx:
            try:
                extraction = extract_xlsx(data, filename)
            except XlsxTooLarge as e:
                raise HTTPException(422, str(e)) from e
            except XlsxUnreadable as e:
                raise HTTPException(422, str(e)) from e
            # 확인과 쓰기를 잠금 안에서 함께 수행한다 (텍스트 분기와 같은 이유). 중복 판정은
            # 추출본 이름으로 한다: 사용자가 손으로 같은 이름의 자료를 만들어 뒀어도 그것을
            # 엑셀 추출본으로 교체하는 의미다 (계획서 B2)
            with store.locked(name):
                if store.source_exists(name, extract_name) and not overwrite:
                    raise HTTPException(409, f"같은 이름의 자료가 이미 있습니다: {filename}")
                # 되돌리기용으로 기존 원본을 먼저 백업한다: 신규 업로드면 None이라 실패 시 지우면
                # 되지만, 이미 정상이던 원본을 overwrite 하던 중이면 그냥 지우면 "새 원본만 지운
                # 것"이 아니라 "이전에 있던 정상 원본까지 함께 사라지는" 데이터 손실이 된다
                # (계획서 B2 리뷰 F1)
                previous_upload = store.read_upload(name, filename)
                store.write_upload(name, filename, data)
                try:
                    store.write_source(name, extract_name, extraction.text)
                except Exception:
                    # 추출본 쓰기가 실패하면 원본만 남는 상태를 만들지 않는다 (계획서 B2): 신규
                    # 업로드였으면 지우고, 기존 원본을 덮어쓰던 중이었으면 그 이전 바이트로 복원한다
                    if previous_upload is None:
                        store.delete_upload(name, filename)
                    else:
                        store.write_upload(name, filename, previous_upload)
                    raise
            return UploadResult(
                filename=filename,
                chars=len(extraction.text),
                sheets=extraction.sheets,
                cells=extraction.cells,
                truncated=extraction.truncated,
                notes=extraction.notes,
            )

        text = decode_source_bytes(data, filename)  # 해석 실패는 InvalidSourceEncoding(422)
        # 확인(source_exists)과 쓰기를 잠금 안에서 함께 수행한다: 잠금 밖이면 같은 새 이름의
        # 두 업로드가 둘 다 확인을 통과해 나중 것이 조용히 덮어쓸 수 있다 (적대 리뷰 재현)
        with store.locked(name):
            # 이름 규칙 위반은 422, 프로젝트 부재는 404로 저장소 예외 매핑을 탄다
            if store.source_exists(name, filename) and not overwrite:
                raise HTTPException(409, f"같은 이름의 자료가 이미 있습니다: {filename}")
            store.write_source(name, filename, text)  # 저장 시점에 UTF-8로 정규화된다
        return UploadResult(filename=filename, chars=len(text), sheets=None, cells=None, truncated=False, notes=[])

    @app.get("/api/health")
    def get_health():
        # Launchers check app identity and UI readiness without invoking AI login.
        health = {
            "product": "slidecaptain",
            "version": __version__,
            "ui_ready": static_dir is not None and (static_dir / "index.html").is_file(),
        }
        if desktop_instance_id is not None:
            health["desktop_instance_id"] = desktop_instance_id
        return health

    def _data_dir_status() -> DataDirStatus | None:
        root = getattr(store, "root", None)
        if root is None:
            return None
        try:
            count = len(store.list_projects())
        except OSError:
            count = 0
        return DataDirStatus(path=str(root), project_count=count, lock=data_dir_lock)

    @app.get("/api/status", response_model=AppStatus)
    def get_status():
        if ai_connections is not None:
            selection, selection_id, login = ai_connections.selected_status()
            return AppStatus(provider=selection.provider, model=selection.model, login=login,
                             selection_id=selection_id, checked_at=_now_iso(),
                             last_generation_at=generation_success.get((selection.provider, selection.model)),
                             data_dir=_data_dir_status())
        # 동기 함수라 스레드풀에서 실행된다: CLI 프로세스 대기가 이벤트 루프를 막지 않는다
        with status_lock:
            now = time.monotonic()
            if status_state["login"] is None or now - status_state["login_at_mono"] > _LOGIN_CACHE_SEC:
                try:
                    status_state["login"] = checker()
                except Exception as e:  # 주입된 checker가 던져도 표시용 조회는 200으로 답한다
                    status_state["login"] = LoginStatus(error=f"로그인 상태를 확인하는 중 오류가 났습니다: {e}")
                status_state["login_at_mono"] = now
                status_state["checked_at"] = _now_iso()
        return AppStatus(
            provider="subscription" if provider is not None else "none",
            login=status_state["login"],
            model=getattr(provider, "model", None),
            last_generation_at=status_state["last_generation_at"],
            checked_at=status_state["checked_at"],
            data_dir=_data_dir_status(),
        )

    def connections():
        if ai_connections is None:
            raise HTTPException(503, "연결 설정을 사용할 수 없습니다. 최신 앱을 실행해 주세요.")
        return ai_connections

    @app.get("/api/ai/settings", response_model=AISettings)
    def get_ai_settings():
        return connections().settings()

    @app.put("/api/ai/selection", response_model=AISelection)
    def select_ai(selection: AISelection):
        try:
            return connections().select(selection)
        except ConnectionConflict:
            raise
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except OSError:
            raise HTTPException(503, "AI 연결 설정을 저장하지 못했습니다. 폴더 권한을 확인해 주세요.") from None

    @app.post("/api/ai/providers/{provider_id}/login", response_model=LoginAttempt)
    def start_ai_login(provider_id: ProviderId):
        return connections().start_login(provider_id)

    @app.get("/api/ai/providers/{provider_id}/login", response_model=LoginAttempt)
    def get_ai_login(provider_id: ProviderId):
        return connections().login_status(provider_id)

    @app.delete("/api/ai/providers/{provider_id}/login", response_model=LoginAttempt)
    def cancel_ai_login(provider_id: ProviderId):
        return connections().cancel_login(provider_id)

    @app.post("/api/projects/{name}/review/numbers", response_model=NumericReviewReport)
    def review_numbers(name: str, deck: Deck):
        # Read the current editor draft without saving or replacing it.
        sources = _load_sources(name)
        return assess_numeric_review(deck, sources)

    @app.post("/api/projects/{name}/review/semantics", response_model=SemanticSuspectReport)
    def review_semantics(name: str, deck: Deck):
        with store.locked(name):
            return assess_semantic_suspects(deck, _load_sources(name, allow_empty=True))

    def _diagram_base(name: str, if_match: str | None):
        if not if_match:
            raise HTTPException(428, "도식 초안의 기준 저장본을 확인해야 합니다. 프로젝트를 다시 열어 주세요.")
        deck, etag = store.load_deck_with_etag(name)
        if if_match.strip('"') != etag:
            raise DeckConflict("다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요.")
        return deck, etag

    @app.post("/api/projects/{name}/generate/diagram", response_model=DiagramGenerationResult)
    async def generate_diagram(
        name: str, req: GenerateDiagramRequest, if_match: str | None = Header(default=None),
        x_ai_consent: str | None = Header(default=None), x_ai_selection: str | None = Header(default=None),
    ):
        _require_ai_consent(x_ai_consent)
        with store.locked(name):
            deck, etag = _diagram_base(name, if_match)
            sources = _load_sources(name, allow_empty=True)
            try:
                diagram_prompt(deck, req, sources)
            except ValueError as exc:
                _rewrite_invalid(exc)
            revision = sources_fingerprint(sources)

        def require_unchanged_base():
            with store.locked(name):
                try:
                    current_etag = store.deck_etag(name)
                except (StorageError, OSError) as exc:
                    raise DeckConflict("도식 생성 중 기준 저장본을 읽을 수 없게 되었습니다. 프로젝트를 다시 열어 주세요.") from exc
                if current_etag != etag:
                    raise DeckConflict("다른 창이나 프로그램에서 먼저 저장되었습니다. 최신 덱을 다시 읽어 주세요.")
                try:
                    current_revision = sources_fingerprint(_load_sources(name, allow_empty=True))
                except (StorageError, OSError, HTTPException) as exc:
                    raise HTTPException(409, "도식 생성 중 자료를 읽을 수 없게 되었습니다. 자료를 확인한 뒤 다시 작성해 주세요.") from exc
                if current_revision != revision:
                    raise HTTPException(409, "도식 생성 중 자료가 바뀌었습니다. 현재 자료로 다시 작성해 주세요.")

        # The lease may await login status. Recheck both after acquiring it and after generation.
        # Never hold the file-store RLock across either await.
        async with generation_service(x_ai_selection) as svc:
            require_unchanged_base()
            result = await svc.generate_diagram(deck, req, sources, on_usage=lambda rec: _append_usage(name, rec))
            require_unchanged_base()
            _record_success(result)
        result.base_etag = f'"{etag}"'
        result.sources_fingerprint = revision
        return result

    @app.post("/api/projects/{name}/generate/structure", response_model=StructureResult)
    async def generate_structure(
        name: str, req: GenerateStructureRequest, x_ai_consent: str | None = Header(default=None),
        x_ai_selection: str | None = Header(default=None),
    ):
        _require_ai_consent(x_ai_consent)
        deck = store.load_deck(name)
        if any(ch.template == "diagram" for ch in deck.structure.chapters):
            raise DiagramGenerationUnsupported()
        async with generation_service(x_ai_selection) as svc:
            sources = _load_sources(name)
            result = await svc.generate_structure(
                deck.meta, sources, req.target_chapters, req.instructions,
                on_usage=lambda rec: _append_usage(name, rec),
                brief=req.brief,
            )
            _record_success(result)
            return result

    @app.post("/api/projects/{name}/generate/chapter/{chapter_id}", response_model=ChapterResult)
    async def generate_chapter(
        name: str, chapter_id: str, req: GenerateChapterRequest,
        x_ai_consent: str | None = Header(default=None),
        x_ai_selection: str | None = Header(default=None),
    ):
        _require_ai_consent(x_ai_consent)
        deck = store.load_deck(name)
        chapter = next((ch for ch in deck.structure.chapters if ch.id == chapter_id), None)
        if chapter is not None and chapter.template == "diagram":
            raise DiagramGenerationUnsupported()
        async with generation_service(x_ai_selection) as svc:
            if all(ch.id != chapter_id for ch in deck.structure.chapters):
                raise HTTPException(404, f"구조안에 없는 장입니다: {chapter_id}")
            preset = _preset_for(deck)
            sources = _load_sources(name)
            result = await svc.generate_chapter(
                deck, chapter_id, sources, preset, req.instructions,
                on_usage=lambda rec: _append_usage(name, rec),
            )
            _record_success(result)
            return result

    @app.post(
        "/api/projects/{name}/generate/chapter/{chapter_id}/condense",
        response_model=ChapterResult,
    )
    async def condense_chapter(
        name: str, chapter_id: str, req: CondenseChapterRequest,
        x_ai_consent: str | None = Header(default=None),
        x_ai_selection: str | None = Header(default=None),
    ):
        _require_ai_consent(x_ai_consent)
        deck = store.load_deck(name)
        chapter = next((ch for ch in deck.structure.chapters if ch.id == chapter_id), None)
        if req.slots.template == "diagram" or (chapter is not None and chapter.template == "diagram"):
            raise DiagramGenerationUnsupported()
        async with generation_service(x_ai_selection) as svc:
            if chapter is None:
                raise HTTPException(404, f"구조안에 없는 장입니다: {chapter_id}")
            if req.slots.template != chapter.template:
                raise HTTPException(
                    422,
                    f"이 장의 템플릿({chapter.template})과 보낸 내용의 템플릿({req.slots.template})이 "
                    "다릅니다. 화면을 새로고침한 뒤 다시 시도해 주세요.",
                )
            preset = _preset_for(deck)
            sources = _load_sources(name)
            result = await svc.condense_chapter(
                deck, chapter_id, req.slots, sources, preset, req.instructions,
                on_usage=lambda rec: _append_usage(name, rec),
            )
            _record_success(result)
            return result

    if static_dir is not None and static_dir.is_dir():
        # 빌드된 화면을 같은 주소에서 서빙한다 (결정 7). API 라우트가 먼저 등록되어 우선한다
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")

    return app
