"""저장과 게시의 방어 코드 네 곳을 지키는 회귀 시험 (최종 리뷰 ST-12, C2 계획 4.5 (13)).

네 검사는 지워도 백엔드 전체 시험이 통과하던 공백이다(변형 ST-M09, ST-M10, ST-M17, ST-M22). 지금 코드는 맞게 동작하므로
이 시험은 고치기 전에도 통과하고, 증거는 변형을 적용하면 실패한다는 사실이다. 시나리오는 리뷰 실험
(`final-review-20261014/exp-storage/scenario_survivors.py`)을 그대로 옮겼다.
"""

import os

import pytest

from slidecaptain.export import exporter
from slidecaptain.models.deck import Deck
from slidecaptain.storage.file_store import FileProjectStore, InvalidName

DECK = {"meta": {"title": "제목"}, "structure": {"chapters": [
    {"id": "c1", "topic": "t", "conclusion": "c", "template": "bullet_box"}]},
    "slides": [{"chapter_id": "c1", "slots": {"template": "bullet_box", "bullets": [{"text": "x", "level": 0}],
                                               "conclusion": "c", "footnote": ""}}]}


def _deck() -> Deck:
    return Deck.model_validate(DECK)


def test_export_fails_when_the_published_name_is_swapped_right_after_linking(tmp_path, monkeypatch):
    """① 게시 직후 재검사(`_verify_published`): 링크한 직후 게시 이름이 다른 바이트로 바뀌면 성공으로 알리지 않는다.
    지우면 남의 바이트를 내보내기 성공으로 알린다 (ST-M09)."""
    out = tmp_path / "out"
    real_link = os.link

    def link(src, dst, *args, **kwargs):
        real_link(src, dst, *args, **kwargs)
        if str(dst).endswith(".pptx"):
            foreign = tmp_path / "foreign.bin"
            foreign.write_bytes(b"not the export")
            os.replace(foreign, out / dst)

    monkeypatch.setattr(os, "link", link)
    with pytest.raises(OSError, match="Published export file changed"):
        exporter.export_deck_data(_deck(), out)


def test_drafts_with_the_same_deck_but_different_bases_are_kept_apart(tmp_path):
    """② 보존본 병합 열쇠의 `base_etag`(D2a-2 리뷰 R4): 내용이 같아도 기준이 다른 보존본은 하나로 합치지 않는다. 지우면
    둘째 기준을 잃는다 (ST-M10)."""
    store = FileProjectStore(tmp_path / "p")
    store.create_project("p1")
    deck = _deck().model_dump(mode="json")
    store.save_draft("p1", deck=deck, reason="conflict", source="editor", base_etag="a" * 64)
    second = store.save_draft("p1", deck=deck, reason="conflict", source="editor", base_etag="b" * 64)
    drafts = store.list_drafts("p1")
    assert len(drafts) == 2
    assert second.base_etag == "b" * 64
    assert sorted(d.base_etag for d in drafts) == ["a" * 64, "b" * 64]


def test_export_history_refuses_a_project_folder_that_is_a_shortcut(tmp_path, symlink_or_skip):
    """③ 검수 이력의 프로젝트 폴더 바로가기 거절: 프로젝트 폴더가 바로가기이면 따라가지 않는다. 지우면 바로가기를 따라간
    폴더의 검수 증거를 읽는다 (ST-M17). 바로가기를 만들 권한이 없는 Windows 계정에서는 건너뛴다(C2 계획 리뷰 PR-23)."""
    real = FileProjectStore(tmp_path / "real")
    real.create_project("p1")
    store = FileProjectStore(tmp_path / "store")
    symlink_or_skip(tmp_path / "store" / "p1", tmp_path / "real" / "p1", target_is_directory=True)
    with pytest.raises(InvalidName):
        store.export_history_dir("p1")


def _case_insensitive(folder) -> bool:
    probe = folder / "case-probe"
    probe.write_text("x")
    try:
        return (folder / "CASE-PROBE").exists()
    finally:
        probe.unlink()


def test_export_never_reuses_a_version_that_differs_only_in_case(tmp_path):
    """④ 버전 경로 백스톱: 대소문자만 다른 기존 파일(`제목_v001.PPTX`)이 있으면 그 번호를 쓰지 않는다. 지우면 내보내기가
    실패하고 짝 없는 품질 기록이 남는다 (ST-M22). 대소문자를 구별하는 파일 시스템에서는 두 이름이 다른 파일이라 해당하지
    않는다."""
    out = tmp_path / "out"
    out.mkdir()
    if not _case_insensitive(out):
        pytest.skip("대소문자를 구별하는 파일 시스템")
    (out / "제목_v001.PPTX").write_bytes(b"user renamed file")
    path = exporter.export_deck_data(_deck(), out)
    assert path.name == "제목_v002.pptx"
    assert (out / "제목_v001.PPTX").read_bytes() == b"user renamed file"
