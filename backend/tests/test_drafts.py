"""충돌 시 미저장본과 생성 결과 보존 (개정판 D2a-2).

보존본은 drafts/에 봉투로 둔다. 덱은 검증하지 않은 원문으로 보존하고 복원할 때 검증한다.
개수 상한은 두지 않고 사용자가 고른 것만 지운다. 자동 삭제는 하지 않는다.
"""

import json

import pytest

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.storage.file_store import (
    DRAFT_MAX_BYTES,
    DeckConflict,
    DraftNotFound,
    DraftTooLarge,
    FileProjectStore,
    StorageError,
)


@pytest.fixture
def store(tmp_path):
    s = FileProjectStore(tmp_path / "projects")
    s.create_project("p1")
    return s


def _deck_json(title="미저장 편집"):
    return json.loads(Deck(meta=DeckMeta(title=title)).model_dump_json())


def test_save_and_list_draft_keeps_envelope_fields(store):
    info = store.save_draft("p1", deck=_deck_json(), reason="conflict", source="editor", base_etag="abc")
    [listed] = store.list_drafts("p1")
    assert listed == info
    assert (info.reason, info.source, info.base_etag) == ("conflict", "editor", "abc")
    envelope = json.loads((store.root / "p1" / "drafts" / f"{info.id}.json").read_text(encoding="utf-8"))
    assert envelope["deck"]["meta"]["title"] == "미저장 편집"


def test_same_content_is_not_saved_twice(store):
    first = store.save_draft("p1", deck=_deck_json(), reason="conflict", source="editor", base_etag="a")
    second = store.save_draft("p1", deck=_deck_json(), reason="conflict", source="editor", base_etag="a")
    assert first.id == second.id
    assert len(store.list_drafts("p1")) == 1


def test_invalid_deck_is_preserved_and_refused_on_restore(store):
    broken = {"meta": {"title": "x"}, "slides": "깨진 값"}
    info = store.save_draft("p1", deck=broken, reason="conflict", source="editor", base_etag=None)
    before = (store.root / "p1" / "deck.json").read_bytes()
    with pytest.raises(StorageError):
        store.restore_draft("p1", info.id)
    assert (store.root / "p1" / "deck.json").read_bytes() == before


def test_too_large_draft_is_refused(store):
    huge = _deck_json()
    huge["meta"]["audience"] = "가" * (DRAFT_MAX_BYTES // 3 + 1)
    with pytest.raises(DraftTooLarge):
        store.save_draft("p1", deck=huge, reason="conflict", source="editor", base_etag=None)
    assert store.list_drafts("p1") == []


def test_no_count_limit_and_no_automatic_deletion(store):
    for i in range(30):
        store.save_draft("p1", deck=_deck_json(f"편집 {i}"), reason="conflict", source="editor", base_etag=None)
    assert len(store.list_drafts("p1")) == 30


def test_restore_checks_etag_and_snapshots_current_deck(store):
    info = store.save_draft("p1", deck=_deck_json("되살릴 내용"), reason="conflict", source="editor", base_etag=None)
    current = store.deck_etag("p1")
    with pytest.raises(DeckConflict):
        store.restore_draft("p1", info.id, expected_etag="다른값")
    before_snapshots = len(store.list_snapshots("p1"))
    deck, etag = store.restore_draft("p1", info.id, expected_etag=current)
    assert deck.meta.title == "되살릴 내용"
    assert etag == store.deck_etag("p1")
    assert len(store.list_snapshots("p1")) == before_snapshots + 1
    assert [d.id for d in store.list_drafts("p1")] == [info.id]  # 복원해도 보존본은 남는다


def test_delete_only_the_chosen_draft(store):
    a = store.save_draft("p1", deck=_deck_json("a"), reason="conflict", source="editor", base_etag=None)
    b = store.save_draft("p1", deck=_deck_json("b"), reason="generation_unsaved", source="structure_approval", base_etag=None)
    store.delete_draft("p1", a.id)
    assert [d.id for d in store.list_drafts("p1")] == [b.id]
    with pytest.raises(DraftNotFound):
        store.delete_draft("p1", a.id)


def test_draft_ids_are_validated(store):
    with pytest.raises(StorageError):
        store.restore_draft("p1", "../deck")
    with pytest.raises(StorageError):
        store.delete_draft("p1", "deck-20260101-000000-000000")


def test_drafts_are_written_atomically(store, monkeypatch):
    import os

    real_replace = os.replace

    def failing(src, dst):
        if "drafts" in str(dst):
            raise OSError("교체 실패 흉내")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", failing)
    with pytest.raises(OSError):
        store.save_draft("p1", deck=_deck_json(), reason="conflict", source="editor", base_etag=None)
    monkeypatch.undo()
    assert [p.name for p in (store.root / "p1" / "drafts").iterdir()] == []


# -- API --------------------------------------------------------------------------------


def test_api_draft_round_trip(client):
    client.post("/api/projects", json={"name": "p1"})
    deck = client.get("/api/projects/p1/deck").json()
    etag = client.get("/api/projects/p1/deck").headers["ETag"]
    deck["meta"]["title"] = "충돌 뒤 편집"
    r = client.post("/api/projects/p1/drafts",
                    json={"reason": "conflict", "source": "editor", "base_etag": etag, "deck": deck})
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]
    [listed] = client.get("/api/projects/p1/drafts").json()
    assert listed["id"] == draft_id
    restored = client.post(f"/api/projects/p1/drafts/{draft_id}/restore", headers={"If-Match": etag})
    assert restored.status_code == 200
    assert restored.json()["meta"]["title"] == "충돌 뒤 편집"
    assert restored.headers["ETag"]
    assert client.delete(f"/api/projects/p1/drafts/{draft_id}").status_code == 200
    assert client.get("/api/projects/p1/drafts").json() == []


def test_api_restore_conflict_and_missing(client):
    client.post("/api/projects", json={"name": "p1"})
    deck = client.get("/api/projects/p1/deck").json()
    draft_id = client.post("/api/projects/p1/drafts",
                           json={"reason": "conflict", "source": "editor", "deck": deck}).json()["id"]
    assert client.post(f"/api/projects/p1/drafts/{draft_id}/restore",
                       headers={"If-Match": '"other"'}).status_code == 412
    assert client.post("/api/projects/p1/drafts/draft-20260101-000000-000000/restore").status_code == 404


def test_api_draft_routes_require_app_header(store):
    from fastapi.testclient import TestClient

    from slidecaptain.server.app import create_app

    bare = TestClient(create_app(store))
    store.create_project("p2")
    body = {"reason": "conflict", "source": "editor", "deck": {}}
    assert bare.post("/api/projects/p2/drafts", json=body).status_code == 403
    # 헤더를 붙이면 같은 요청이 성공해야 라우트가 실제로 있다는 뜻이다 (리뷰 R13)
    created = bare.post("/api/projects/p2/drafts", json=body, headers={"X-Requested-With": "SlideCaptain"})
    assert created.status_code == 201
    draft_id = created.json()["id"]
    assert bare.post(f"/api/projects/p2/drafts/{draft_id}/restore").status_code == 403
    assert bare.delete(f"/api/projects/p2/drafts/{draft_id}").status_code == 403



def test_same_content_with_different_reason_is_a_separate_draft(store):
    a = store.save_draft("p1", deck=_deck_json(), reason="conflict", source="editor", base_etag="e1")
    b = store.save_draft("p1", deck=_deck_json(), reason="generation_unsaved", source="structure_approval", base_etag="e2")
    assert a.id != b.id
    assert (b.reason, b.source, b.base_etag) == ("generation_unsaved", "structure_approval", "e2")


def test_unknown_reason_from_a_later_version_is_listed_and_does_not_break_saving(store):
    info = store.save_draft("p1", deck=_deck_json(), reason="conflict", source="editor", base_etag=None)
    path = store.root / "p1" / "drafts" / f"{info.id}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["reason"] = "later_reason"
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    assert [d.reason for d in store.list_drafts("p1")] == ["later_reason"]
    again = store.save_draft("p1", deck=_deck_json(), reason="conflict", source="editor", base_etag=None)
    assert again.id != info.id


def test_same_microsecond_drafts_are_listed_in_creation_order(store):
    drafts = store.root / "p1" / "drafts"
    drafts.mkdir()
    for stem in ("draft-20261008-100000-000001", "draft-20261008-100000-000001-1"):
        drafts.joinpath(f"{stem}.json").write_text(json.dumps({
            "id": stem, "saved_at": "2026-10-08T10:00:00+09:00", "reason": "conflict", "source": "editor",
            "base_etag": None, "content_sha256": stem, "deck": {}}), encoding="utf-8")
    assert [d.id for d in store.list_drafts("p1")] == [
        "draft-20261008-100000-000001", "draft-20261008-100000-000001-1"]


def test_size_is_measured_on_compact_json_and_after_project_checks(store):
    from slidecaptain.storage.file_store import ProjectNotFound

    big = _deck_json()
    big["meta"]["audience"] = "x" * (DRAFT_MAX_BYTES - 1000)
    with pytest.raises(ProjectNotFound):
        store.save_draft("없음", deck=big, reason="conflict", source="editor", base_etag=None)
    compact = len(json.dumps(big, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert compact <= DRAFT_MAX_BYTES
    store.save_draft("p1", deck=big, reason="conflict", source="editor", base_etag=None)
