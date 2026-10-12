"""보고 목적 저장 계약과 형식 등급 (개정판 D3b-1, 계획 4.2).

새 항목(유형 확인 표시, 핵심 내용, 원하는 결과와 기타 설명, 유형별 추가 입력)은 덱 메타에만 두고,
기본값이면 직렬화하지 않는다. 형식 등급은 "어느 앱이 읽는가"다: 1은 0.2.0, 2는 개정판 중간 빌드
(D2a~D3a), 3은 D3b 이후만 읽는다. 등급 3 덱은 schema_version 2이고 manifest 형식 번호 3이다.
"""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.models.report_purpose import (
    DETAIL_MAX, KEY_MESSAGE_MAX, OUTCOME_OTHER_MAX, REPORT_DETAIL_FIELDS, is_blank,
)
from slidecaptain.pipeline.progress import _purpose as purpose_progress
from slidecaptain.storage import project_format
from slidecaptain.storage.file_store import FileProjectStore
from slidecaptain.storage.project_format import MAX_SUPPORTED_FORMAT, deck_format, read_manifest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _deck(**meta):
    meta.setdefault("title", "보고")
    return Deck(meta=DeckMeta(**meta))


def _manifest(store, name="p1"):
    return read_manifest(store.root / name)


def _deck_bytes(store, name="p1") -> bytes:
    return (store.root / name / "deck.json").read_bytes()


def _write_legacy_bytes(store, data: bytes, name="p1"):
    """0.2.0이나 다른 프로그램이 manifest를 건드리지 않고 deck.json만 바꾼다."""
    (store.root / name / "deck.json").write_bytes(data)


# -- 모델: 기본값 생략, 비어 있음, 버전 결정 ---------------------------------------------

def test_new_fields_are_omitted_when_default_so_existing_decks_keep_their_bytes():
    for fixture in ("q2a-story-deck.json", "q3b-project.json"):
        payload = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
        payload = payload.get("deck", payload)
        deck = Deck.model_validate(payload)
        dumped = json.loads(deck.model_dump_json())
        for key in ("report_type_confirmed", "key_message", "desired_outcome", "desired_outcome_other",
                    "report_details"):
            assert key not in dumped["meta"]
        assert dumped["schema_version"] == 1


def test_new_fields_round_trip_and_raise_the_schema_version():
    deck = _deck(report_type="approval", report_type_confirmed=True, key_message="예산 증액을 승인받는다",
                 desired_outcome="persuasion", report_details={"approval.decision_question": "증액 여부"})
    again = Deck.model_validate_json(deck.model_dump_json())
    assert again.meta.key_message == "예산 증액을 승인받는다"
    assert again.meta.desired_outcome == "persuasion"
    assert again.meta.report_details == {"approval.decision_question": "증액 여부"}
    assert again.schema_version == 2


def test_blank_values_do_not_raise_the_level():
    assert is_blank("  \n") and is_blank("") and not is_blank(" a ")
    for meta in ({"key_message": "   "}, {"report_details": {"weekly.period": " "}},
                 {"desired_outcome_other": "  "}, {"report_type_confirmed": True}):
        deck = _deck(report_type="research", **meta)
        assert deck_format(deck) == 1, meta
        assert deck.schema_version == 1, meta
    # 빈 값 키는 검증에서 버린다
    assert _deck(report_details={"weekly.period": " "}).meta.report_details == {}


def test_hidden_inputs_still_count_for_the_level():
    """지금 유형이 아닌 유형의 추가 입력과 기타가 아닐 때의 기타 설명도 데이터라 센다 (계획 4.2, 리뷰 S7)."""
    assert deck_format(_deck(report_type="research", report_details={"weekly.period": "10월 둘째 주"})) == 3
    # 원하는 결과 선택이 없을 때의 기타 설명만으로도 등급 3이다 (D3b-1 리뷰 R6, M18)
    assert deck_format(_deck(report_type="research", desired_outcome_other="옛 설명")) == 3
    # 원하는 결과를 고른 것만으로도 사용자 입력이다 (M17)
    assert deck_format(_deck(report_type="research", desired_outcome="facts")) == 3


def test_schema_version_input_is_ignored_and_decided_by_content():
    plain = _deck().model_dump(mode="json")
    plain["schema_version"] = 2
    assert Deck.model_validate(plain).schema_version == 1
    rich = _deck(key_message="핵심").model_dump(mode="json")
    rich["schema_version"] = 1
    assert Deck.model_validate(rich).schema_version == 2
    plain["schema_version"] = 3
    with pytest.raises(ValidationError, match="앱을 업데이트해 주세요"):
        Deck.model_validate(plain)


def test_unknown_detail_key_and_too_long_values_are_rejected():
    with pytest.raises(ValidationError):
        _deck(report_details={"weekly.unknown": "x"})
    with pytest.raises(ValidationError):
        _deck(report_details={"weekly.period": "x" * 1001})
    with pytest.raises(ValidationError):
        _deck(key_message="x" * 8001)
    with pytest.raises(ValidationError):
        _deck(desired_outcome_other="x" * 8001)
    assert _deck(key_message="x" * 8000).meta.key_message


def test_every_report_type_has_detail_fields_including_ir():
    assert set(REPORT_DETAIL_FIELDS) == {
        "weekly", "business", "monthly", "data", "research", "project", "results", "approval", "strategy", "ir",
    }
    assert all(REPORT_DETAIL_FIELDS[t] for t in REPORT_DETAIL_FIELDS)


# -- 형식 등급 ---------------------------------------------------------------------

def test_levels_follow_which_app_can_read_the_deck():
    assert MAX_SUPPORTED_FORMAT == 3
    for legacy in ("research", "approval", "strategy"):
        assert deck_format(_deck(report_type=legacy)) == 1
    for interim in ("weekly", "business", "monthly", "data", "project", "results"):
        assert deck_format(_deck(report_type=interim)) == 2
    ir = _deck(report_type="ir")
    assert deck_format(ir) == 3
    assert ir.schema_version == 2
    assert deck_format(_deck(report_type="weekly", key_message="핵심")) == 3


def test_byte_judgement_matches_the_model_judgement():
    for deck in (_deck(), _deck(report_type="weekly"), _deck(report_type="ir"), _deck(key_message="핵심"),
                 _deck(report_type="weekly", report_type_confirmed=True)):
        data = deck.model_dump_json(indent=2).encode("utf-8")
        assert project_format.deck_format_of_bytes(data) == deck_format(deck)


# -- 쓰기와 manifest -------------------------------------------------------------------

def test_raising_to_level_three_forces_a_pre_migration_snapshot_and_records_manifest_three(store):
    store.create_project("p1")
    before = _deck_bytes(store)
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    manifest = _manifest(store)
    assert manifest.format_version == 3
    [record] = manifest.migrations
    assert (record.kind, record.from_format, record.to_format, record.status) == ("upgrade", 1, 3, "done")
    assert (store.root / "p1" / "snapshots" / f"{record.snapshot_id}.json").read_bytes() == before
    assert [s.kind for s in store.list_snapshots("p1")] == ["pre_migration"]
    assert manifest.last_written_etag == hashlib.sha256(_deck_bytes(store)).hexdigest()


def test_raising_from_two_to_three_is_recorded_but_not_marked_pre_migration(store):
    store.create_project("p1")
    store.save_deck("p1", _deck(report_type="weekly"), snapshot=False)
    store.save_deck("p1", _deck(report_type="weekly", key_message="핵심"), snapshot=True)
    upgrades = [(m.from_format, m.to_format) for m in _manifest(store).migrations if m.kind == "upgrade"]
    assert upgrades == [(1, 2), (2, 3)]
    assert [s.kind for s in store.list_snapshots("p1")].count("pre_migration") == 1
    # 요청한 스냅샷은 만들지만 2에서 3 기록에는 남기지 않는다. 중간 빌드가 0.2.0 복구 지점으로 표시하지 않게 한다
    # (α 묶음 리뷰 A8)
    [record] = [m for m in _manifest(store).migrations if m.kind == "upgrade" and m.from_format == 2]
    assert record.snapshot_id is None
    assert len(store.list_snapshots("p1")) == 2


def test_manifest_is_raised_before_the_deck_is_replaced(store, monkeypatch):
    """등급 3에서는 manifest 번호가 중간 빌드를 막는 유일한 장치다 (재리뷰 RR6)."""
    store.create_project("p1")
    original = store._write_deck

    def failing(project_dir, deck):
        raise OSError("디스크 오류")

    monkeypatch.setattr(store, "_write_deck", failing)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    assert _manifest(store).format_version == 3
    monkeypatch.setattr(store, "_write_deck", original)
    store.save_deck("p1", _deck(title="다음 저장"), snapshot=False)
    manifest = _manifest(store)
    assert manifest.format_version == 1
    assert [(m.kind, m.status) for m in manifest.migrations][0] == ("upgrade", "not_applied")


def test_final_manifest_failure_on_raise_still_leaves_manifest_three(store, monkeypatch):
    store.create_project("p1")
    calls = {"n": 0}
    original = project_format.write_manifest

    def flaky(project_dir, manifest, atomic_write):
        calls["n"] += 1
        if calls["n"] == 2:  # 덱 교체 뒤의 마지막 기록
            raise OSError("기록 실패")
        return original(project_dir, manifest, atomic_write)

    monkeypatch.setattr(project_format, "write_manifest", flaky)
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    assert _manifest(store).format_version == 3


def test_lowering_writes_the_deck_before_lowering_the_manifest(store):
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    store.save_deck("p1", _deck(), snapshot=False)
    manifest = _manifest(store)
    assert manifest.format_version == 1
    assert [(m.kind, m.from_format, m.to_format) for m in manifest.migrations][-1] == ("downgrade", 3, 1)


def test_own_round_trips_do_not_pile_up_forced_snapshots(store):
    """디스크 덱이 가장 최근 0.2.0 복구 지점과 같으면 강제 스냅샷을 다시 만들지 않는다 (리뷰 S13).
    다시 씀 (D3b-1 리뷰 R5): 기준을 "마지막 쓰기 그대로"에서 "복구 지점과 바이트가 같음"으로 바꿨다"""
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    store.save_deck("p1", _deck(), snapshot=False)
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    count = len(store.list_snapshots("p1"))
    for _ in range(3):
        store.save_deck("p1", _deck(), snapshot=False)
        store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    assert len(store.list_snapshots("p1")) == count


@pytest.mark.parametrize("raised", [{"key_message": "핵심"}, {"report_type": "weekly"}])
def test_own_edit_at_level_one_becomes_a_new_restore_point(store, raised):
    """이 앱이 등급 1로 내린 뒤 고친 상태도 다음 올림의 0.2.0 복구 지점이 된다. 1에서 2로 오르는 저장도 같다
    (D3b-1 리뷰 R5: 마지막 쓰기 기준이면 이 편집을 0.2.0에서 되찾을 수 없었다)"""
    store.create_project("p1")
    store.save_deck("p1", _deck(**raised), snapshot=False)
    store.save_deck("p1", _deck(title="등급 1에서 오래 편집한 상태"), snapshot=False)
    store.save_deck("p1", _deck(title="등급 1에서 오래 편집한 상태", **raised), snapshot=False)
    titles = []
    for snap in store.list_snapshots("p1"):
        data = json.loads((store.root / "p1" / "snapshots" / f"{snap.id}.json").read_text(encoding="utf-8"))
        titles.append((snap.kind, data["meta"]["title"]))
    assert ("pre_migration", "등급 1에서 오래 편집한 상태") in titles


def test_raising_from_two_to_three_without_a_snapshot_request_makes_no_snapshot(store):
    """강제 스냅샷은 디스크 등급이 1일 때만이다. 주간 보고 덱의 자동 저장마다 쌓이지 않는다 (D3b-1 리뷰 R6, M31)."""
    store.create_project("p1")
    store.save_deck("p1", _deck(report_type="weekly"), snapshot=False)
    count = len(store.list_snapshots("p1"))
    store.save_deck("p1", _deck(report_type="weekly", key_message="핵심"), snapshot=False)
    store.save_deck("p1", _deck(report_type="weekly"), snapshot=False)
    assert len(store.list_snapshots("p1")) == count


def test_broken_legacy_deck_raise_still_puts_the_manifest_first(store, monkeypatch):
    """0.2.0도 못 여는 깨진 덱에서 오르는 저장도 manifest 번호를 먼저 올린다 (D3b-1 리뷰 R6, M26)."""
    store.create_project("p1")
    (store.root / "p1" / "deck.json").write_text(
        '{"schema_version": 1, "meta": {"title": "x", "report_type": "research"}, "slides": 5}', encoding="utf-8")

    def failing(project_dir, deck):
        raise OSError("디스크 오류")

    monkeypatch.setattr(store, "_write_deck", failing)
    with pytest.raises(OSError):
        store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    assert _manifest(store).format_version == 3


def test_a_foreign_edit_at_level_one_forces_a_new_snapshot(store):
    """새 앱이 등급 1로 내린 뒤 다른 앱(0.2.0)이 고치면 다음 올림이 그 편집을 복구 지점으로 남긴다 (재리뷰 RR2)."""
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    store.save_deck("p1", _deck(), snapshot=False)
    foreign = _deck(title="0.2.0 사용자가 고침").model_dump_json(indent=2).encode("utf-8")
    _write_legacy_bytes(store, foreign)
    store.save_deck("p1", _deck(key_message="다시"), snapshot=False)
    snapshots = sorted((store.root / "p1" / "snapshots").glob("deck-*.json"))
    assert snapshots[-1].read_bytes() == foreign
    assert [s.kind for s in store.list_snapshots("p1")].count("pre_migration") == 2


def _fail_manifest_after_deck(store, monkeypatch):
    """덱을 교체한 뒤의 manifest 쓰기만 실패시킨다. 몇 번째 쓰기인지에 기대지 않는다."""
    original_write, original_deck = project_format.write_manifest, store._write_deck
    state = {"deck_written": False}

    def deck_then_flag(project_dir, deck):
        etag = original_deck(project_dir, deck)
        state["deck_written"] = True
        return etag

    def fail_after_deck(project_dir, manifest, atomic_write):
        if state["deck_written"]:
            raise OSError("기록 실패")
        return original_write(project_dir, manifest, atomic_write)

    monkeypatch.setattr(store, "_write_deck", deck_then_flag)
    monkeypatch.setattr(project_format, "write_manifest", fail_after_deck)

    def restore():
        monkeypatch.setattr(store, "_write_deck", original_deck)
        monkeypatch.setattr(project_format, "write_manifest", original_write)
    return restore


# -- 0.2.0 되돌림 표시 ------------------------------------------------------------------

def _simulate_legacy_restore(store, snapshot_id: str):
    """0.2.0의 복구 화면: 현재 덱을 스냅샷으로 남기고 고른 스냅샷 바이트로 덮는다. manifest는 모른다."""
    project = store.root / "p1"
    current = (project / "deck.json").read_bytes()
    (project / "snapshots" / "deck-29991231-235959-000001.json").write_bytes(current)
    (project / "deck.json").write_bytes((project / "snapshots" / f"{snapshot_id}.json").read_bytes())


def test_revert_by_old_app_is_marked_in_the_listing_before_any_write(store):
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    [pre] = store.list_snapshots("p1")
    _simulate_legacy_restore(store, pre.id)
    kinds = {s.id: s.kind for s in store.list_snapshots("p1")}
    assert kinds["deck-29991231-235959-000001"] == "before_revert"
    assert _manifest(store).format_version == 3  # 목록은 읽기만 한다


def test_revert_mark_survives_a_later_old_app_save_and_is_recorded_on_write(store):
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    [pre] = store.list_snapshots("p1")
    _simulate_legacy_restore(store, pre.id)
    # 0.2.0이 복원 뒤 한 번 더 저장하며 직전 상태를 스냅샷으로 남긴다
    (store.root / "p1" / "snapshots" / "deck-29991231-235959-000002.json").write_bytes(_deck_bytes(store))
    _write_legacy_bytes(store, _deck(title="0.2.0 저장").model_dump_json(indent=2).encode("utf-8"))
    assert {s.id: s.kind for s in store.list_snapshots("p1")}["deck-29991231-235959-000001"] == "before_revert"
    store.save_deck("p1", _deck(title="새 앱"), snapshot=False)
    revert = [m for m in _manifest(store).migrations if m.kind == "external_downgrade"]
    assert [(m.from_format, m.to_format, m.snapshot_id) for m in revert] == [(3, 1, "deck-29991231-235959-000001")]
    assert {s.id: s.kind for s in store.list_snapshots("p1")}["deck-29991231-235959-000001"] == "before_revert"


@pytest.mark.parametrize("snapshot", [True, False])
def test_revert_after_a_failed_final_manifest_write_marks_the_newest_content(store, monkeypatch, snapshot):
    """마지막 기록이 실패해도 쓰려던 덱의 지문이 덱 교체 전에 남아, 0.2.0이 되돌린 뒤 최신 내용이 든 스냅샷에
    표시가 붙는다. 옛 스냅샷에 붙으면 표시를 따라 복원한 사용자가 마지막 편집을 잃는다 (D3b-1 리뷰 R1)."""
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="첫 핵심"), snapshot=False)
    restore = _fail_manifest_after_deck(store, monkeypatch)
    store.save_deck("p1", _deck(key_message="마지막 핵심"), snapshot=snapshot)
    restore()
    pre = next(s for s in store.list_snapshots("p1") if s.kind == "pre_migration")
    _simulate_legacy_restore(store, pre.id)
    marked = [s.id for s in store.list_snapshots("p1") if s.kind == "before_revert"]
    assert marked == ["deck-29991231-235959-000001"]
    data = json.loads((store.root / "p1" / "snapshots" / f"{marked[0]}.json").read_text(encoding="utf-8"))
    assert data["meta"]["key_message"] == "마지막 핵심"


def test_revert_after_a_failed_deck_replacement_marks_the_previous_deck(store, monkeypatch):
    """덱 교체 자체가 실패하면 디스크에는 직전 덱이 남는다. 0.2.0이 되돌린 뒤 그 직전 덱이 든 스냅샷에 표시가
    붙어야 한다(쓰려던 덱의 지문은 디스크 어디에도 없다, α 묶음 리뷰 A1)."""
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="첫 핵심"), snapshot=False)
    store.save_deck("p1", _deck(key_message="둘째 핵심"), snapshot=False)

    def fail(self, project_dir, deck):
        raise OSError("덱 교체 실패(시험)")

    with monkeypatch.context() as patch:
        patch.setattr(FileProjectStore, "_write_deck", fail)
        with pytest.raises(OSError):
            store.save_deck("p1", _deck(key_message="셋째 핵심"), snapshot=False)
    manifest = _manifest(store)
    assert manifest.last_written_etag and manifest.prior_written_etag
    pre = next(s for s in store.list_snapshots("p1") if s.kind == "pre_migration")
    _simulate_legacy_restore(store, pre.id)
    marked = [s.id for s in store.list_snapshots("p1") if s.kind == "before_revert"]
    assert marked == ["deck-29991231-235959-000001"]
    data = json.loads((store.root / "p1" / "snapshots" / f"{marked[0]}.json").read_text(encoding="utf-8"))
    assert data["meta"]["key_message"] == "둘째 핵심"


def test_own_downgrade_with_a_failed_final_write_is_not_marked_as_a_revert(store, monkeypatch):
    """이 앱이 등급 3에서 1로 내리며 마지막 기록이 실패해도 자기 스냅샷을 되돌림으로 표시하지 않는다 (리뷰 R6, M11)."""
    store.create_project("p1")
    store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
    restore = _fail_manifest_after_deck(store, monkeypatch)
    store.save_deck("p1", _deck(), snapshot=True)
    restore()
    assert "before_revert" not in {s.kind for s in store.list_snapshots("p1")}


def test_revert_from_level_two_does_not_mark_an_old_level_three_snapshot(store):
    store.create_project("p1")
    store.save_deck("p1", _deck(report_type="weekly", key_message="핵심"), snapshot=True)
    store.save_deck("p1", _deck(report_type="weekly"), snapshot=True)  # 핵심 내용을 지워 등급 2
    [pre] = [s for s in store.list_snapshots("p1") if s.kind == "pre_migration"]
    _simulate_legacy_restore(store, pre.id)
    assert "before_revert" not in {s.kind for s in store.list_snapshots("p1")}


# -- 진행 API ---------------------------------------------------------------------

def _purpose(deck):
    return purpose_progress(deck)


def test_purpose_is_ready_once_the_type_is_confirmed_or_not_the_default():
    assert (_purpose(_deck()).state, _purpose(_deck()).reasons) == ("needs_review", ["report_type_unconfirmed"])
    confirmed = _purpose(_deck(report_type_confirmed=True, key_message="핵심"))
    assert (confirmed.state, confirmed.reasons) == ("ready", [])
    chosen = _purpose(_deck(report_type="approval"))  # 0.2.0에서 고른 유형도 확인된 것으로 본다
    assert (chosen.state, chosen.reasons) == ("ready", ["key_message_missing"])
    blank = _purpose(_deck(report_type_confirmed=True, key_message="  "))
    assert blank.reasons == ["key_message_missing"]



def test_report_type_tables_cover_every_report_type():
    """열거와 그 열거를 키로 쓰는 표가 어긋나면 그 유형의 생성이 KeyError로 끝난다 (D3b-1 리뷰 R2)."""
    from typing import get_args

    from slidecaptain.models.story import ReportType
    from slidecaptain.pipeline.report_types import REPORT_TYPE_GUIDES

    assert set(REPORT_TYPE_GUIDES) == set(get_args(ReportType)) == set(REPORT_DETAIL_FIELDS)


def test_legacy_readable_checks_the_raw_schema_version():
    """원문 버전이 정수 1이 아니면 0.2.0이 열지 못한다. 손 편집한 "2" 문자열도 마찬가지다 (D3b-1 리뷰 R10)."""
    data = json.loads(_deck().model_dump_json())
    assert project_format.legacy_readable(json.dumps(data).encode("utf-8"))
    data["schema_version"] = "2"
    assert not project_format.legacy_readable(json.dumps(data).encode("utf-8"))


def test_too_long_purpose_text_has_a_readable_message():
    """자동 저장의 422가 원인을 알려 준다 (D3b-1 리뷰 R12)."""
    with pytest.raises(ValidationError, match="핵심 내용은 8,000자까지입니다"):
        _deck(key_message="x" * 8001)
    with pytest.raises(ValidationError, match="기타 설명은 8,000자까지입니다"):
        _deck(desired_outcome_other="x" * 8001)


def test_put_of_a_version_one_deck_with_purpose_content_writes_version_two(store):
    """화면은 받은 덱을 그대로 돌려보낸다. 버전 1 덱에 핵심 내용을 넣은 PUT도 디스크는 버전 2, manifest 3이다
    (D3b-1 리뷰 R16)."""
    from fastapi.testclient import TestClient

    from slidecaptain.server.app import create_app

    store.create_project("p1")
    with TestClient(create_app(store), headers={"X-Requested-With": "SlideCaptain"}) as client:
        deck = client.get("/api/projects/p1/deck")
        body = deck.json()
        assert body["schema_version"] == 1
        body["meta"]["key_message"] = "핵심"
        assert client.put("/api/projects/p1/deck", json=body, headers={"If-Match": deck.headers["etag"]}).status_code == 200
        assert json.loads(_deck_bytes(store))["schema_version"] == 2 and _manifest(store).format_version == 3
        deck = client.get("/api/projects/p1/deck")
        body = deck.json()
        body["meta"]["key_message"] = ""
        assert client.put("/api/projects/p1/deck", json=body, headers={"If-Match": deck.headers["etag"]}).status_code == 200
    assert json.loads(_deck_bytes(store))["schema_version"] == 1 and _manifest(store).format_version == 1


DETAIL_FIXTURE = Path(__file__).parent / "fixtures" / "report-purpose-fields.json"


def test_report_purpose_fields_match_the_fixture_the_screen_uses():
    """화면의 유형별 추가 입력 칸과 길이 상한이 서버 표와 같은지 고정 파일로 잇는다 (D3b-5). 화면 시험이 같은
    파일을 읽어 화면의 표와 비교한다. 칸이나 상한을 바꾸면 SLIDECAPTAIN_UPDATE_FIXTURES=1로 다시 쓴다."""
    import os

    collected = {
        "fields": {kind: [list(pair) for pair in fields] for kind, fields in REPORT_DETAIL_FIELDS.items()},
        "limits": {"key_message": KEY_MESSAGE_MAX, "desired_outcome_other": OUTCOME_OTHER_MAX, "detail": DETAIL_MAX},
    }
    text = json.dumps(collected, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("SLIDECAPTAIN_UPDATE_FIXTURES") == "1":
        DETAIL_FIXTURE.write_text(text, encoding="utf-8")
    assert DETAIL_FIXTURE.read_text(encoding="utf-8") == text, "보고 목적 칸 표가 바뀌었습니다. 고정 파일을 다시 써 주세요"


def test_is_blank_matches_the_screen():
    """화면 isBlank와 같은 표다 (D3b-5 리뷰 R5, frontend reportPurpose.test.ts)."""
    assert is_blank("﻿") is False
    assert is_blank("\x1f") is True
    assert is_blank("\x85") is True
    assert is_blank(" \t\n　") is True
