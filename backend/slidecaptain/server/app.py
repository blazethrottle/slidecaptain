"""FastAPI 로컬 서버 (설계서 2.2). 저장소와 단계 1 코어를 조립만 한다.

실행은 CLI의 serve 서브커맨드가 담당하며 127.0.0.1 전용으로 바인딩한다 (로컬 웹앱).
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from slidecaptain.export.exporter import export_deck_data
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset, apply_overrides
from slidecaptain.models.render import RenderPlan
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


def create_app(store: ProjectStore) -> FastAPI:
    app = FastAPI(title="Slide Captain", version="0.2.0")
    metrics = FontMetrics.load_default()  # 앱 수명 동안 1회 로드

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError):
        status = next(code for cls, code in _STATUS_BY_ERROR if isinstance(exc, cls))
        return JSONResponse(status_code=status, content={"detail": str(exc)})

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

    return app
