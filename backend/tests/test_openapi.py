import json
from pathlib import Path

import pytest

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def schema(tmp_path):
    return create_app(FileProjectStore(tmp_path / "projects")).openapi()


def test_openapi_contains_core_schemas(schema):
    names = schema["components"]["schemas"].keys()
    for required in ["Deck", "RenderPlan", "RenderStyle", "ProjectInfo", "SnapshotInfo"]:
        assert required in names, f"{required} 스키마가 OpenAPI에 없습니다"


def test_committed_openapi_json_matches_live_app(schema):
    path = Path(__file__).resolve().parent.parent / "openapi.json"
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed == schema, (
        "커밋된 openapi.json이 앱과 다릅니다. scripts/dump_openapi.py로 재생성해 주세요"
    )


def test_openapi_contains_all_routes(schema):
    paths = schema["paths"].keys()
    for route in [
        "/api/preset",
        "/api/projects",
        "/api/projects/{name}/deck",
        "/api/projects/{name}/render-plan",
        "/api/render-plan",
        "/api/projects/{name}/export",
        "/api/projects/{name}/snapshots",
        "/api/projects/{name}/snapshots/{snapshot_id}/restore",
        "/api/projects/{name}/sources",
        "/api/projects/{name}/sources/{filename}",
        "/api/projects/{name}/generate/structure",
        "/api/projects/{name}/generate/chapter/{chapter_id}",
        "/api/projects/{name}/generate/chapter/{chapter_id}/condense",
    ]:
        assert route in paths, f"{route} 경로가 OpenAPI에 없습니다"
