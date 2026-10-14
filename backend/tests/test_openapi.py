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
        "/api/projects/{name}/sources/{filename}/upload",
        "/api/status",
        "/api/projects/{name}/jobs",
        "/api/projects/{name}/jobs/{job_id}",
        "/api/projects/{name}/jobs/{job_id}/apply",
    ]:
        assert route in paths, f"{route} 경로가 OpenAPI에 없습니다"


def test_wrappers_are_gone_but_result_schemas_stay(schema):
    """동기 생성 래퍼 여섯은 지웠다(D3c-7, 계획 4.9). 화면은 작업 응답의 결과를 이 다섯 타입으로 읽으므로 구성 요소로 남는다."""
    paths = schema["paths"].keys()
    for route in ["generate/structure", "generate/chapter/{chapter_id}", "generate/chapter/{chapter_id}/condense",
                  "generate/diagram", "story-plan/rewrite", "story-plan/repair"]:
        assert f"/api/projects/{{name}}/{route}" not in paths
    names = schema["components"]["schemas"]
    for model in ["ChapterResult", "StructureResult", "DiagramGenerationResult", "StoryRewriteResult", "StoryRepairResult"]:
        assert model in names
    # 기본값 null은 FastAPI처럼 빠진다. 남으면 화면 타입의 선택 칸이 필수가 된다 (계획 재리뷰 RR4)
    assert "default" not in names["ChapterResult"]["properties"]["slots"]
