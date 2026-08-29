from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


def test_static_ui_served_and_api_precedence(tmp_path):
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<h1>ui</h1>", encoding="utf-8")
    client = TestClient(create_app(FileProjectStore(tmp_path / "projects"), static_dir=ui))
    assert "<h1>ui</h1>" in client.get("/").text
    assert client.get("/api/projects").json() == []  # API 라우트가 정적보다 우선


def test_missing_static_dir_means_api_only(tmp_path):
    client = TestClient(
        create_app(FileProjectStore(tmp_path / "projects"), static_dir=tmp_path / "없는폴더")
    )
    assert client.get("/api/projects").status_code == 200
    assert client.get("/").status_code == 404
