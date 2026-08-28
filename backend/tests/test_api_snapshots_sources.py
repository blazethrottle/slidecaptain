import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def _save_title(client, title):
    deck = client.get("/api/projects/p1/deck").json()
    deck["meta"]["title"] = title
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def test_snapshot_list_and_restore(client):
    client.post("/api/projects", json={"name": "p1", "title": "v1"})
    _save_title(client, "v2")
    snaps = client.get("/api/projects/p1/snapshots").json()
    assert len(snaps) == 1 and snaps[0]["saved_at"]
    r = client.post(f"/api/projects/p1/snapshots/{snaps[0]['id']}/restore")
    assert r.status_code == 200
    assert r.json()["meta"]["title"] == "v1"
    assert client.get("/api/projects/p1/deck").json()["meta"]["title"] == "v1"


def test_restore_missing_snapshot_404(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots/deck-19990101-000000-000000/restore")
    assert r.status_code == 404


def test_sources_round_trip(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.put("/api/projects/p1/sources/리서치.md", json={"text": "숫자 42"})
    assert r.status_code == 200
    assert client.get("/api/projects/p1/sources").json() == ["리서치.md"]
    assert client.get("/api/projects/p1/sources/리서치.md").json()["text"] == "숫자 42"


def test_source_missing_404(client):
    client.post("/api/projects", json={"name": "p1"})
    assert client.get("/api/projects/p1/sources/없음.md").status_code == 404


def test_externally_added_source_readable_via_api(client, store):
    client.post("/api/projects", json={"name": "p1"})
    (store.root / "p1" / "sources" / "자료(최종).md").write_text("숫자 42", encoding="utf-8")
    assert "자료(최종).md" in client.get("/api/projects/p1/sources").json()
    r = client.get("/api/projects/p1/sources/자료(최종).md")
    assert r.status_code == 200
    assert r.json()["text"] == "숫자 42"
