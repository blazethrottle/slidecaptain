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
from slidecaptain.models.report_purpose import REPORT_DETAIL_FIELDS, is_blank
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
    assert deck_format(_deck(report_type="research", desired_outcome="facts", desired_outcome_other="옛 설명")) == 3


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
    """이 앱이 마지막으로 쓴 덱이 디스크에 그대로면 강제 스냅샷을 다시 만들지 않는다 (리뷰 S13)."""
    store.create_project("p1")
    for _ in range(3):
        store.save_deck("p1", _deck(key_message="핵심"), snapshot=False)
        store.save_deck("p1", _deck(), snapshot=False)
    assert len(store.list_snapshots("p1")) == 1


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
