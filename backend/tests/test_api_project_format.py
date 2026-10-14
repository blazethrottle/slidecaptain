"""프로젝트 형식의 API 노출 (개정판 D2a-1)."""

import json

from slidecaptain.storage.project_format import MAX_SUPPORTED_FORMAT


def _set_report_type(client, report_type):
    deck = client.get("/api/projects/p1/deck").json()
    deck["meta"]["report_type"] = report_type
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def _make_newer(store):
    path = store.root / "p1" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["format_version"] = MAX_SUPPORTED_FORMAT + 1
    path.write_text(json.dumps(data), encoding="utf-8")


def test_snapshot_listing_marks_pre_migration_copy(client):
    client.post("/api/projects", json={"name": "p1"})
    _set_report_type(client, "weekly")
    kinds = [s["kind"] for s in client.get("/api/projects/p1/snapshots").json()]
    assert kinds == ["pre_migration"]


def test_newer_format_project_is_listed_and_refused_with_code(client, store):
    client.post("/api/projects", json={"name": "p1"})
    _make_newer(store)
    [info] = client.get("/api/projects").json()
    assert info["status"] == "newer_format"
    for response in (
        client.get("/api/projects/p1/deck"),
        client.get("/api/projects/p1/snapshots"),
        client.get("/api/projects/p1/sources"),
        client.put("/api/projects/p1/sources/a.md", json={"text": "x"}),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "project_format_too_new"


def test_newer_format_refusal_covers_state_changing_routes(client, store):
    """리뷰 R8: 복원, 내보내기, 업로드도 같은 409와 code로 거절한다."""
    client.post("/api/projects", json={"name": "p1"})
    _make_newer(store)
    for response in (
        client.post("/api/projects/p1/snapshots/deck-20260101-000000-000000/restore"),
        client.post("/api/projects/p1/snapshots"),
        client.post("/api/projects/p1/export"),
        client.get("/api/projects/p1/exports"),
        client.post("/api/projects/p1/sources/a.md/upload", files={"file": ("a.md", b"x")}),
    ):
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "project_format_too_new"


def test_unreadable_manifest_is_listed_and_refused_with_its_own_code(client, store):
    client.post("/api/projects", json={"name": "p1"})
    (store.root / "p1" / "manifest.json").write_text("{깨진", encoding="utf-8")
    [info] = client.get("/api/projects").json()
    assert info["status"] == "unreadable_manifest"
    response = client.get("/api/projects/p1/deck")
    assert response.status_code == 409
    assert response.json()["code"] == "project_manifest_unreadable"
