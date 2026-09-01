"""FastAPI 로컬 서버 (설계서 2.2). 저장소와 단계 1 코어를 조립만 한다.

실행은 CLI의 serve 서브커맨드가 담당하며 127.0.0.1 전용으로 바인딩한다 (로컬 웹앱).
"""

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PureWindowsPath

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from slidecaptain.export.exporter import export_deck_data
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, Slots
from slidecaptain.models.preset import Preset, apply_overrides
from slidecaptain.models.render import RenderPlan
from slidecaptain.pipeline.auth_status import LoginStatus, check_login
from slidecaptain.pipeline.provider import AIProvider, ProviderError
from slidecaptain.pipeline.service import ChapterResult, GenerationService, StructureResult
from slidecaptain.storage.file_store import (
    InvalidName,
    InvalidSourceEncoding,
    ProjectExists,
    ProjectNotFound,
    ProjectInfo,
    ProjectStore,
    SnapshotInfo,
    SnapshotNotFound,
    SourceNotFound,
    StorageError,
    decode_source_bytes,
)

_STATUS_BY_ERROR = [
    (InvalidName, 422),
    (InvalidSourceEncoding, 422),
    (ProjectNotFound, 404),
    (SnapshotNotFound, 404),
    (SourceNotFound, 404),
    (ProjectExists, 409),
    (StorageError, 400),
]

_SOURCES_TOTAL_MAX_CHARS = 100_000  # 자료 전문이 프롬프트에 동봉되므로 상한을 명시한다 (단계 4 결정 14)
_UPLOAD_EXTENSIONS = {".md", ".txt", ".csv"}  # 업로드로 받는 텍스트 형식 (PDF와 Word는 단계 5 이월)
_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
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


class OkResponse(BaseModel):
    ok: bool = True


class UploadResult(BaseModel):
    filename: str
    chars: int


class AppStatus(BaseModel):
    provider: str  # "subscription" 또는 "none"
    login: LoginStatus
    model: str | None = None
    last_generation_at: str | None = None  # 프로세스 메모리에만 기록, 재시작 시 초기화
    checked_at: str


class ExportResult(BaseModel):
    path: str


class GenerateStructureRequest(BaseModel):
    target_chapters: int | None = Field(default=None, ge=1)
    instructions: str = ""


class GenerateChapterRequest(BaseModel):
    instructions: str = ""


class CondenseChapterRequest(BaseModel):
    slots: Slots  # 화면이 들고 있는 현재 슬롯 (미저장 수정 포함. 설계 결정 13)
    instructions: str = ""


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
) -> FastAPI:
    app = FastAPI(title="Slide Captain", version="0.2.0")
    metrics = FontMetrics.load_default()  # 앱 수명 동안 1회 로드
    service = GenerationService(provider, metrics) if provider is not None else None
    checker = login_checker or check_login
    # 앱 상태 (계획서 2026-09-01 태스크 4): 로그인 확인 캐시와 마지막 생성 성공 시각. 파일에 남기지 않는다
    status_state: dict = {"login": None, "login_at_mono": 0.0, "checked_at": "", "last_generation_at": None}

    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _record_success(result) -> None:
        """구조안 생성, 장별 생성, 축약이 status == "ok"로 끝나면 마지막 성공 시각을 갱신한다."""
        if getattr(result, "status", None) == "ok":
            status_state["last_generation_at"] = _now_iso()

    # DNS 리바인딩 방지. testserver는 TestClient의 기본 Host라 허용한다 (브라우저가 보낼 수 없는 값)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError):
        status = next(code for cls, code in _STATUS_BY_ERROR if isinstance(exc, cls))
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request, exc: ProviderError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

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

    def _load_sources(name: str) -> dict[str, str]:
        files = store.list_sources(name)
        if not files:
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
    def get_deck(name: str):
        return store.load_deck(name)

    @app.put("/api/projects/{name}/deck", response_model=OkResponse)
    def put_deck(name: str, deck: Deck, snapshot: bool = True):
        _preset_for(deck)
        store.save_deck(name, deck, snapshot=snapshot)
        return OkResponse()

    @app.post("/api/projects/{name}/snapshots", response_model=OkResponse, status_code=201)
    def create_snapshot(name: str):
        store.snapshot_now(name)
        return OkResponse()

    @app.get("/api/projects/{name}/render-plan", response_model=RenderPlan)
    def get_render_plan(name: str):
        deck = store.load_deck(name)
        preset = _preset_for(deck)
        return build_render_plan(deck, preset, metrics)

    @app.post("/api/render-plan", response_model=RenderPlan)
    def measure_deck(deck: Deck):
        """저장 없이 실측만 한다: 편집 중 미리보기와 분량 경고의 공급원 (단계 4 결정 2)."""
        preset = _preset_for(deck)
        return build_render_plan(deck, preset, metrics)

    @app.post("/api/projects/{name}/export", response_model=ExportResult)
    def export_project(name: str):
        deck = store.load_deck(name)
        _preset_for(deck)  # 내보내기 전에 overrides부터 검증한다 (파일 직접 수정 대비)
        path = export_deck_data(deck, store.exports_dir(name), global_preset=store.load_global_preset())
        return ExportResult(path=str(path))

    @app.get("/api/projects/{name}/snapshots", response_model=list[SnapshotInfo])
    def list_snapshots(name: str):
        return store.list_snapshots(name)

    @app.post("/api/projects/{name}/snapshots/{snapshot_id}/restore", response_model=Deck)
    def restore_snapshot(name: str, snapshot_id: str):
        return store.restore_snapshot(name, snapshot_id)

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
    async def upload_source(name: str, filename: str, request: Request, overwrite: bool = False):
        """파일 본문을 원시 바이트로 받아 텍스트로 해석해 자료로 저장한다 (계획서 2026-09-01 태스크 2).

        멀티파트를 쓰지 않는 이유: 파일 1개씩만 받으므로 원시 본문이면 충분하고, 파싱 의존성이 필요 없다.
        """
        # 브라우저나 OS가 붙인 경로 조각은 벗기고 이름만 쓴다 (Windows 역슬래시 포함, OS 무관하게 처리)
        filename = PureWindowsPath(filename).name
        if Path(filename).suffix.lower() not in _UPLOAD_EXTENSIONS:
            raise HTTPException(
                422,
                "지원하지 않는 형식입니다. 지금은 .md, .txt, .csv 텍스트 파일만 넣을 수 있고, "
                "PDF와 Word는 아직 지원하지 않습니다.",
            )
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > _UPLOAD_MAX_BYTES:
            raise HTTPException(422, "파일이 너무 큽니다(5MB 한도). 필요한 부분만 발췌해 주세요.")
        data = await request.body()
        if len(data) > _UPLOAD_MAX_BYTES:
            raise HTTPException(422, "파일이 너무 큽니다(5MB 한도). 필요한 부분만 발췌해 주세요.")
        # 이름 규칙 위반은 422, 프로젝트 부재는 404로 저장소 예외 매핑을 탄다
        if store.source_exists(name, filename) and not overwrite:
            raise HTTPException(409, f"같은 이름의 자료가 이미 있습니다: {filename}")
        text = decode_source_bytes(data, filename)  # 해석 실패는 InvalidSourceEncoding(422)
        store.write_source(name, filename, text)  # 저장 시점에 UTF-8로 정규화된다
        return UploadResult(filename=filename, chars=len(text))

    @app.get("/api/status", response_model=AppStatus)
    def get_status():
        # 동기 함수라 스레드풀에서 실행된다: CLI 프로세스 대기가 이벤트 루프를 막지 않는다
        now = time.monotonic()
        if status_state["login"] is None or now - status_state["login_at_mono"] > _LOGIN_CACHE_SEC:
            status_state["login"] = checker()
            status_state["login_at_mono"] = now
            status_state["checked_at"] = _now_iso()
        return AppStatus(
            provider="subscription" if provider is not None else "none",
            login=status_state["login"],
            model=getattr(provider, "model", None),
            last_generation_at=status_state["last_generation_at"],
            checked_at=status_state["checked_at"],
        )

    @app.post("/api/projects/{name}/generate/structure", response_model=StructureResult)
    async def generate_structure(name: str, req: GenerateStructureRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        sources = _load_sources(name)
        result = await svc.generate_structure(deck.meta, sources, req.target_chapters, req.instructions)
        _record_success(result)
        return result

    @app.post("/api/projects/{name}/generate/chapter/{chapter_id}", response_model=ChapterResult)
    async def generate_chapter(name: str, chapter_id: str, req: GenerateChapterRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        if all(ch.id != chapter_id for ch in deck.structure.chapters):
            raise HTTPException(404, f"구조안에 없는 장입니다: {chapter_id}")
        preset = _preset_for(deck)
        sources = _load_sources(name)
        result = await svc.generate_chapter(deck, chapter_id, sources, preset, req.instructions)
        _record_success(result)
        return result

    @app.post(
        "/api/projects/{name}/generate/chapter/{chapter_id}/condense",
        response_model=ChapterResult,
    )
    async def condense_chapter(name: str, chapter_id: str, req: CondenseChapterRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        chapter = next((ch for ch in deck.structure.chapters if ch.id == chapter_id), None)
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
        result = await svc.condense_chapter(deck, chapter_id, req.slots, sources, preset, req.instructions)
        _record_success(result)
        return result

    if static_dir is not None and static_dir.is_dir():
        # 빌드된 화면을 같은 주소에서 서빙한다 (결정 7). API 라우트가 먼저 등록되어 우선한다
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")

    return app
