"""FastAPI 로컬 서버 (설계서 2.2). 저장소와 단계 1 코어를 조립만 한다.

실행은 CLI의 serve 서브커맨드가 담당하며 127.0.0.1 전용으로 바인딩한다 (로컬 웹앱).
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from slidecaptain.export.exporter import export_deck_data
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, Slots
from slidecaptain.models.preset import Preset, apply_overrides
from slidecaptain.models.render import RenderPlan
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


class CreateProjectRequest(BaseModel):
    name: str
    title: str = ""


class SourceText(BaseModel):
    text: str


class OkResponse(BaseModel):
    ok: bool = True


class ExportResult(BaseModel):
    path: str


class GenerateStructureRequest(BaseModel):
    target_chapters: int | None = None
    instructions: str = ""


class GenerateChapterRequest(BaseModel):
    instructions: str = ""


class CondenseChapterRequest(BaseModel):
    slots: Slots  # 화면이 들고 있는 현재 슬롯 (미저장 수정 포함. 설계 결정 13)
    instructions: str = ""


def _validated_preset(deck: Deck) -> Preset:
    """덱의 preset_overrides를 검증해 프리셋을 만든다.

    사용자가 deck.json 파일을 직접 고쳐 PUT 검증을 우회한 경우에도
    render-plan과 export가 500 대신 같은 422로 답하게 한다.
    """
    try:
        return apply_overrides(Preset(), deck.meta.preset_overrides)
    except ValidationError as e:
        first = e.errors()[0]["msg"]
        raise HTTPException(422, f"프리셋 덮어쓰기 값이 유효하지 않습니다: {first}")


def create_app(store: ProjectStore, provider: AIProvider | None = None) -> FastAPI:
    app = FastAPI(title="Slide Captain", version="0.2.0")
    metrics = FontMetrics.load_default()  # 앱 수명 동안 1회 로드
    service = GenerationService(provider, metrics) if provider is not None else None

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError):
        status = next(code for cls, code in _STATUS_BY_ERROR if isinstance(exc, cls))
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request, exc: ProviderError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

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
        return {f: store.read_source(name, f) for f in files}

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
    def put_deck(name: str, deck: Deck):
        _validated_preset(deck)
        store.save_deck(name, deck)
        return OkResponse()

    @app.get("/api/projects/{name}/render-plan", response_model=RenderPlan)
    def get_render_plan(name: str):
        deck = store.load_deck(name)
        preset = _validated_preset(deck)
        return build_render_plan(deck, preset, metrics)

    @app.post("/api/render-plan", response_model=RenderPlan)
    def measure_deck(deck: Deck):
        """저장 없이 실측만 한다: 편집 중 미리보기와 분량 경고의 공급원 (단계 4 결정 2)."""
        preset = _validated_preset(deck)
        return build_render_plan(deck, preset, metrics)

    @app.post("/api/projects/{name}/export", response_model=ExportResult)
    def export_project(name: str):
        deck = store.load_deck(name)
        _validated_preset(deck)  # 내보내기 전에 overrides부터 검증한다 (파일 직접 수정 대비)
        path = export_deck_data(deck, store.exports_dir(name))
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

    @app.post("/api/projects/{name}/generate/structure", response_model=StructureResult)
    async def generate_structure(name: str, req: GenerateStructureRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        sources = _load_sources(name)
        return await svc.generate_structure(deck.meta, sources, req.target_chapters, req.instructions)

    @app.post("/api/projects/{name}/generate/chapter/{chapter_id}", response_model=ChapterResult)
    async def generate_chapter(name: str, chapter_id: str, req: GenerateChapterRequest):
        svc = _require_service()
        deck = store.load_deck(name)
        if all(ch.id != chapter_id for ch in deck.structure.chapters):
            raise HTTPException(404, f"구조안에 없는 장입니다: {chapter_id}")
        preset = _validated_preset(deck)
        sources = _load_sources(name)
        return await svc.generate_chapter(deck, chapter_id, sources, preset, req.instructions)

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
        preset = _validated_preset(deck)
        sources = _load_sources(name)
        return await svc.condense_chapter(deck, chapter_id, req.slots, sources, preset, req.instructions)

    return app
