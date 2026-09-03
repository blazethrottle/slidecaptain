# client, store 픽스처는 backend/tests/conftest.py 참조 (A2에서 통합, 기본 헤더 X-Requested-With 포함)


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


def test_read_binary_source_returns_422(client, store):
    client.post("/api/projects", json={"name": "p1"})
    (store.root / "p1" / "sources" / "그림.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe")
    r = client.get("/api/projects/p1/sources/그림.png")
    assert r.status_code == 422
    assert "텍스트" in r.json()["detail"]


def test_restore_returns_quoted_etag_matching_new_content(client):
    client.post("/api/projects", json={"name": "p1", "title": "v1"})
    _save_title(client, "v2")
    snaps = client.get("/api/projects/p1/snapshots").json()
    r = client.post(f"/api/projects/p1/snapshots/{snaps[0]['id']}/restore")
    assert r.status_code == 200
    restore_etag = r.headers["etag"]
    assert restore_etag.startswith('"') and restore_etag.endswith('"')
    assert restore_etag == client.get("/api/projects/p1/deck").headers["etag"]


def test_restore_with_matching_if_match_succeeds(client):
    client.post("/api/projects", json={"name": "p1", "title": "v1"})
    _save_title(client, "v2")
    snaps = client.get("/api/projects/p1/snapshots").json()
    etag = client.get("/api/projects/p1/deck").headers["etag"]
    r = client.post(f"/api/projects/p1/snapshots/{snaps[0]['id']}/restore", headers={"If-Match": etag})
    assert r.status_code == 200
    assert r.json()["meta"]["title"] == "v1"


def test_restore_with_stale_if_match_conflict_412(client):
    client.post("/api/projects", json={"name": "p1", "title": "v1"})
    _save_title(client, "v2")
    snaps = client.get("/api/projects/p1/snapshots").json()
    stale_etag = '"' + "0" * 64 + '"'
    r = client.post(f"/api/projects/p1/snapshots/{snaps[0]['id']}/restore", headers={"If-Match": stale_etag})
    assert r.status_code == 412
    assert "먼저 저장" in r.json()["detail"]
    # 충돌이면 v2 그대로다 (복원되지 않는다)
    assert client.get("/api/projects/p1/deck").json()["meta"]["title"] == "v2"
