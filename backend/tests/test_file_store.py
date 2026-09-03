import threading

import pytest

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.models.preset import Preset
from slidecaptain.storage.file_store import (
    DeckConflict,
    FileProjectStore,
    InvalidName,
    InvalidSourceEncoding,
    ProjectExists,
    ProjectNotFound,
    SnapshotNotFound,
    SourceNotFound,
    StorageError,
)


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _deck(title="테스트 덱"):
    return Deck(meta=DeckMeta(title=title))


def test_create_project_builds_folder_layout(store):
    info = store.create_project("주간보고", title="주간 보고")
    assert info.name == "주간보고"
    assert info.title == "주간 보고"
    root = store.root / "주간보고"
    assert (root / "deck.json").exists()
    assert (root / "sources").is_dir()
    assert (root / "snapshots").is_dir()
    assert (root / "exports").is_dir()


def test_create_duplicate_project_rejected(store):
    store.create_project("p1")
    with pytest.raises(ProjectExists):
        store.create_project("p1")


@pytest.mark.parametrize("bad", ["", "..", "a/b", "a\\b", "CON", "긴이름" * 30, " 앞공백", "이름끝점."])
def test_invalid_project_names_rejected(store, bad):
    with pytest.raises(InvalidName):
        store.create_project(bad)


@pytest.mark.parametrize("bad", ["preset.json", "preset.json.tmp"])
def test_project_name_colliding_with_global_preset_rejected(store, bad):
    # 전역 프리셋 파일과 같은 이름의 프로젝트 폴더가 생기면 load_global_preset의
    # read_text가 디렉터리를 읽으려다 실패한다 (2026-08-29 최종 리뷰 발견)
    with pytest.raises(InvalidName):
        store.create_project(bad)


def test_load_save_round_trip(store):
    store.create_project("p1", title="원래 제목")
    deck = store.load_deck("p1")
    deck.meta.title = "고친 제목"
    store.save_deck("p1", deck)
    assert store.load_deck("p1").meta.title == "고친 제목"


def test_save_makes_snapshot_of_previous_state(store):
    store.create_project("p1", title="v1")
    deck = store.load_deck("p1")
    deck.meta.title = "v2"
    store.save_deck("p1", deck)  # 저장 직전의 v1이 스냅샷으로 남는다
    snaps = store.list_snapshots("p1")
    assert len(snaps) == 1
    restored, _etag = store.restore_snapshot("p1", snaps[0].id)
    assert restored.meta.title == "v1"
    # 복원도 저장이므로 복원 직전 상태(v2)가 다시 스냅샷으로 남는다
    assert len(store.list_snapshots("p1")) == 2


def test_create_project_leaves_no_snapshot(store):
    store.create_project("p1")
    assert store.list_snapshots("p1") == []


def test_atomic_write_leaves_no_tmp_file(store):
    store.create_project("p1")
    store.save_deck("p1", _deck())
    leftovers = [p for p in (store.root / "p1").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_uses_atomic_replace(store, monkeypatch):
    # 원자성 자체를 고정한다: 저장이 임시 파일 + os.replace 경로를 반드시 거쳐야 한다
    import slidecaptain.storage.file_store as fs

    calls = []
    real_replace = fs.os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(fs.os, "replace", spy)
    store.create_project("p1")
    store.save_deck("p1", _deck())
    deck_writes = [c for c in calls if c[1].endswith("deck.json")]
    assert deck_writes, "deck.json 저장이 os.replace를 거치지 않았습니다"
    assert deck_writes[-1][0].endswith(".tmp")


def test_missing_project_raises(store):
    with pytest.raises(ProjectNotFound):
        store.load_deck("없는프로젝트")


def test_missing_snapshot_raises(store):
    store.create_project("p1")
    with pytest.raises(SnapshotNotFound):
        store.restore_snapshot("p1", "deck-19990101-000000-000000")


def test_corrupted_deck_reports_recovery_hint(store):
    store.create_project("p1")
    (store.root / "p1" / "deck.json").write_text("{망가진 json", encoding="utf-8")
    with pytest.raises(Exception) as exc_info:
        store.load_deck("p1")
    assert "스냅샷" in str(exc_info.value)


def test_list_projects_sorted_with_updated_at(store):
    store.create_project("b프로젝트")
    store.create_project("a프로젝트")
    infos = store.list_projects()
    assert [i.name for i in infos] == ["a프로젝트", "b프로젝트"]
    assert all(i.updated_at for i in infos)


def test_sources_round_trip(store):
    store.create_project("p1")
    store.write_source("p1", "리서치.md", "# 자료\n숫자 42")
    assert store.list_sources("p1") == ["리서치.md"]
    assert "42" in store.read_source("p1", "리서치.md")


def test_source_name_traversal_rejected(store):
    store.create_project("p1")
    with pytest.raises(InvalidName):
        store.write_source("p1", "..\\밖으로.md", "x")
    with pytest.raises(SourceNotFound):
        store.read_source("p1", "없는파일.md")


def test_read_source_accepts_externally_added_filename(store):
    # 탐색기로 넣은 파일은 생성 문법(괄호 금지 등)을 안 지켜도 읽을 수 있어야 한다
    store.create_project("p1")
    (store.root / "p1" / "sources" / "자료(최종).md").write_text("# 최종", encoding="utf-8")
    assert store.read_source("p1", "자료(최종).md") == "# 최종"


@pytest.mark.parametrize(
    "bad", ["", "..", "..\\밖.md", "../밖.md", "a/b.md", "a\\b.md", "C:밖.md", "CON", "이름끝점."]
)
def test_read_source_rejects_escape_names(store, bad):
    store.create_project("p1")
    with pytest.raises(InvalidName):
        store.read_source("p1", bad)


def test_list_sources_hides_tmp_and_hidden_files(store):
    store.create_project("p1")
    store.write_source("p1", "리서치.md", "본문")
    (store.root / "p1" / "sources" / ".tmp-깨진저장.md").write_text("잔재", encoding="utf-8")
    (store.root / "p1" / "sources" / ".숨김").write_text("숨김", encoding="utf-8")
    assert store.list_sources("p1") == ["리서치.md"]


def test_write_source_tmp_does_not_clobber_real_file(store):
    # 정식 자료 이름이 a.md.tmp여도 a.md 저장의 임시 파일과 충돌하면 안 된다
    store.create_project("p1")
    store.write_source("p1", "a.md.tmp", "진짜 자료")
    store.write_source("p1", "a.md", "본문")
    assert store.read_source("p1", "a.md.tmp") == "진짜 자료"


def test_read_source_cp949_fallback(store):
    store.create_project("p1")
    path = store.root / "p1" / "sources" / "옛문서.txt"
    path.write_bytes("한글 자료입니다. 매출 1,234억".encode("cp949"))
    assert "1,234억" in store.read_source("p1", "옛문서.txt")


def test_read_source_utf8_bom_absorbed(store):
    store.create_project("p1")
    path = store.root / "p1" / "sources" / "봄문서.txt"
    path.write_bytes("\ufeff본문 시작".encode("utf-8"))
    assert store.read_source("p1", "봄문서.txt") == "본문 시작"


def test_read_source_binary_rejected_with_guidance(store):
    store.create_project("p1")
    path = store.root / "p1" / "sources" / "그림.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe\xfd")
    with pytest.raises(InvalidSourceEncoding) as exc_info:
        store.read_source("p1", "그림.png")
    assert "텍스트" in str(exc_info.value)


def test_global_preset_default_when_missing(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    assert store.load_global_preset() == Preset()


def test_global_preset_roundtrip(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    preset = Preset()
    preset.font_roles.title_pt = 22.0
    store.save_global_preset(preset)
    assert store.load_global_preset().font_roles.title_pt == 22.0


def test_global_preset_corrupt_file_message(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    (tmp_path / "projects" / "preset.json").write_text("{망가짐", encoding="utf-8")
    with pytest.raises(StorageError) as exc_info:
        store.load_global_preset()
    assert "preset.json" in str(exc_info.value)


def test_save_deck_without_snapshot(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    deck = store.load_deck("p1")
    store.save_deck("p1", deck, snapshot=False)
    assert store.list_snapshots("p1") == []
    store.save_deck("p1", deck)  # 기본값은 여전히 스냅샷을 남긴다
    assert len(store.list_snapshots("p1")) == 1


def test_snapshot_now(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    store.snapshot_now("p1")
    assert len(store.list_snapshots("p1")) == 1


def test_project_without_deck_listed_for_recovery(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    store.save_deck("p1", store.load_deck("p1"))  # 스냅샷 1개를 만든다
    (tmp_path / "projects" / "p1" / "deck.json").unlink()
    infos = store.list_projects()
    assert len(infos) == 1 and infos[0].status == "needs_recovery"
    snaps = store.list_snapshots("p1")  # deck.json 없이도 동작해야 한다
    assert len(snaps) == 1
    deck, _etag = store.restore_snapshot("p1", snaps[0].id)  # 복원이 deck.json을 재생성한다
    assert deck.meta.title == "p1"
    assert store.list_projects()[0].status == "ok"


def test_corrupt_deck_marked_needs_recovery(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    (tmp_path / "projects" / "p1" / "deck.json").write_text("{깨짐", encoding="utf-8")
    assert store.list_projects()[0].status == "needs_recovery"


def test_empty_dir_without_snapshots_not_listed(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    (tmp_path / "projects" / "빈폴더").mkdir(parents=True)
    assert store.list_projects() == []


# -- A1: 저장소 잠금, 고유 임시 파일, 내용 ETag ------------------------------


def test_concurrent_saves_are_serialized_and_leave_no_leftovers(store):
    # 스레드 8개가 각각 다른 제목으로 100회씩 저장한다. 잠금이 없으면 겹친 os.replace가
    # FileNotFoundError를 낸다 (재현 실측 458건).
    store.create_project("p1")
    errors: list[Exception] = []

    def worker(i: int) -> None:
        for j in range(100):
            try:
                store.save_deck("p1", _deck(f"스레드{i}-{j}"))
            except Exception as e:  # noqa: BLE001 - 실패하면 아래 단언에서 드러난다
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    final = store.load_deck("p1")  # 마지막 저장이 완전한 내용으로 파싱된다
    assert final.meta.title.startswith("스레드")
    leftovers = [
        p for p in (store.root / "p1").iterdir() if p.name.startswith(".") and p.name.endswith(".tmp")
    ]
    assert leftovers == []
    assert len(store.list_snapshots("p1")) == 800  # 저장 호출 수와 스냅샷 수가 같다


def test_concurrent_create_project_only_one_succeeds(store):
    results: list[tuple[str, object]] = []
    results_lock = threading.Lock()

    def worker() -> None:
        try:
            info = store.create_project("동시생성")
            outcome = ("ok", info)
        except ProjectExists as e:
            outcome = ("exists", e)
        except FileExistsError as e:  # 이 예외가 새면 안 된다
            outcome = ("leaked", e)
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert [r[0] for r in results].count("ok") == 1
    assert [r[0] for r in results].count("exists") == 4
    assert [r[0] for r in results].count("leaked") == 0


def test_unique_tmp_paths_and_closed_before_replace(store, monkeypatch):
    import slidecaptain.storage.file_store as fs

    store.create_project("p1")
    seen_srcs: list[str] = []
    real_replace = fs.os.replace

    def spy(src, dst):
        # 교체 시점에 이미 닫혀 있어야 새 핸들로 전체 내용을 읽을 수 있다
        # (Windows는 쓰기용으로 열린 핸들이 남아 있으면 교체 자체가 실패한다)
        with open(src, "rb") as f:
            assert f.read()
        seen_srcs.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(fs.os, "replace", spy)
    store.save_deck("p1", _deck("첫 저장"))
    store.save_deck("p1", _deck("둘째 저장"))
    assert len(seen_srcs) == 2
    assert seen_srcs[0] != seen_srcs[1]  # 서로 다른 임시 경로


def test_write_exception_leaves_no_tmp_file(store, monkeypatch):
    import slidecaptain.storage.file_store as fs

    store.create_project("p1")

    def boom(src, dst):
        raise OSError("교체 실패 시뮬레이션")

    monkeypatch.setattr(fs.os, "replace", boom)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck())
    leftovers = [
        p for p in (store.root / "p1").iterdir() if p.name.startswith(".") and p.name.endswith(".tmp")
    ]
    assert leftovers == []


def test_save_deck_returns_etag_matching_deck_etag_and_load_with_etag(store):
    store.create_project("p1")
    deck = store.load_deck("p1")
    etag = store.save_deck("p1", deck)
    assert etag == store.deck_etag("p1")
    loaded_deck, loaded_etag = store.load_deck_with_etag("p1")
    assert loaded_etag == etag
    assert loaded_deck.meta.title == deck.meta.title


def test_save_deck_etag_stable_for_same_content_changes_for_new_content(store):
    store.create_project("p1")
    deck = store.load_deck("p1")
    etag1 = store.save_deck("p1", deck)
    etag2 = store.save_deck("p1", deck)  # 같은 내용, 같은 ETag
    assert etag1 == etag2
    deck.meta.title = "새 제목"
    etag3 = store.save_deck("p1", deck)
    assert etag3 != etag2


def test_save_deck_expected_etag_match_succeeds(store):
    store.create_project("p1")
    deck = store.load_deck("p1")
    etag = store.deck_etag("p1")
    deck.meta.title = "고친 제목"
    new_etag = store.save_deck("p1", deck, expected_etag=etag)
    assert new_etag != etag
    assert store.load_deck("p1").meta.title == "고친 제목"


def test_save_deck_expected_etag_mismatch_raises_and_keeps_file_and_snapshots(store):
    store.create_project("p1")
    deck = store.load_deck("p1")
    stale_etag = store.deck_etag("p1")
    other = store.load_deck("p1")
    other.meta.title = "먼저 저장한 제목"
    store.save_deck("p1", other)  # 실제 ETag를 바꿔 stale_etag를 낡게 만든다
    before = (store.root / "p1" / "deck.json").read_bytes()
    snap_count_before = len(store.list_snapshots("p1"))
    with pytest.raises(DeckConflict):
        store.save_deck("p1", deck, expected_etag=stale_etag)
    assert (store.root / "p1" / "deck.json").read_bytes() == before
    assert len(store.list_snapshots("p1")) == snap_count_before


def test_save_deck_no_expected_etag_always_succeeds(store):
    store.create_project("p1")
    deck = store.load_deck("p1")
    other = store.load_deck("p1")
    other.meta.title = "먼저 저장"
    store.save_deck("p1", other)
    deck.meta.title = "나중 저장(무조건)"
    store.save_deck("p1", deck)  # expected_etag 없으면 검사하지 않는다
    assert store.load_deck("p1").meta.title == "나중 저장(무조건)"


def test_restore_snapshot_returns_new_etag(store):
    store.create_project("p1", title="v1")
    deck = store.load_deck("p1")
    deck.meta.title = "v2"
    store.save_deck("p1", deck)
    snaps = store.list_snapshots("p1")
    restored, etag = store.restore_snapshot("p1", snaps[0].id)
    assert restored.meta.title == "v1"
    assert etag == store.deck_etag("p1")


def test_restore_snapshot_expected_etag_mismatch_raises_and_keeps_file(store):
    store.create_project("p1", title="v1")
    deck = store.load_deck("p1")
    deck.meta.title = "v2"
    store.save_deck("p1", deck)
    snaps = store.list_snapshots("p1")
    before = (store.root / "p1" / "deck.json").read_bytes()
    snap_count_before = len(store.list_snapshots("p1"))
    with pytest.raises(DeckConflict):
        store.restore_snapshot("p1", snaps[0].id, expected_etag="0" * 64)
    assert (store.root / "p1" / "deck.json").read_bytes() == before
    assert len(store.list_snapshots("p1")) == snap_count_before


def test_locked_is_reentrant(store):
    store.create_project("p1")
    with store.locked("p1"):
        with store.locked("p1"):  # 재진입 가능해야 라우트가 잠근 채 저장소 메서드를 불러도 된다
            store.save_deck("p1", _deck("재진입 안쪽 저장"))
    assert store.load_deck("p1").meta.title == "재진입 안쪽 저장"
