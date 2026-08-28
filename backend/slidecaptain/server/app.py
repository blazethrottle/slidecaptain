"""FastAPI 로컬 서버 (설계서 2.2). 저장소와 단계 1 코어를 조립만 한다.

실행은 CLI의 serve 서브커맨드가 담당하며 127.0.0.1 전용으로 바인딩한다 (로컬 웹앱).
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset, apply_overrides
from slidecaptain.storage.file_store import (
    InvalidName,
    ProjectExists,
    ProjectNotFound,
    ProjectInfo,
    ProjectStore,
    SnapshotNotFound,
    SourceNotFound,
    StorageError,
)

_STATUS_BY_ERROR = [
    (InvalidName, 422),
    (ProjectNotFound, 404),
    (SnapshotNotFound, 404),
    (SourceNotFound, 404),
    (ProjectExists, 409),
    (StorageError, 400),
]


class CreateProjectRequest(BaseModel):
    name: str
    title: str = ""


class OkResponse(BaseModel):
    ok: bool = True


def create_app(store: ProjectStore) -> FastAPI:
    app = FastAPI(title="Slide Captain", version="0.2.0")

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
        try:
            apply_overrides(Preset(), deck.meta.preset_overrides)
        except ValidationError as e:
            first = e.errors()[0]["msg"]
            raise HTTPException(422, f"프리셋 덮어쓰기 값이 유효하지 않습니다: {first}")
        store.save_deck(name, deck)
        return OkResponse()

    return app
