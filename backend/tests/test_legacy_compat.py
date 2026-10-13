"""배포된 0.2.0과의 왕복 (개정판 D2a-1).

v0.2.0 태그의 백엔드 코드를 임시 폴더에 풀고 별도 프로세스로 실행해, 새 앱이 쓴 프로젝트를
0.2.0이 어떻게 보는지 확인한다. 태그가 없으면 건너뛰지 않고 실패한다(CI는 전체 이력을 받는다).
"""

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.storage.file_store import FileProjectStore
from slidecaptain.storage.job_ledger import LEDGER_NAME, FixedInputs, JobLedger
from slidecaptain.storage.project_format import read_manifest

REPO = Path(__file__).resolve().parents[2]
LEGACY_TAG = "v0.2.0"
# 개정판 중간 빌드(D2a~D3a)의 마지막 커밋. manifest 형식 2까지 읽고 보고 유형 9종을 안다 (D3b-1)
INTERIM_REF = "afe9138"
# D3b 종결 빌드. manifest 형식 3까지 읽고 직접 수정(Slide.direct_edits)을 모른다 (D3c-1)
D3B_REF = "88a6572"

_LEGACY_SCRIPT = r"""
import json
import sys
from pathlib import Path

import slidecaptain
from slidecaptain.storage.file_store import FileProjectStore

root, legacy_backend, command = sys.argv[1], sys.argv[2], sys.argv[3]
if not Path(slidecaptain.__file__).resolve().is_relative_to(Path(legacy_backend).resolve()):
    print(json.dumps({"wrong_code": slidecaptain.__file__}))
    sys.exit(3)
store = FileProjectStore(root)
out = {"statuses": {p.name: p.status for p in store.list_projects()}}
if command == "load":
    try:
        store.load_deck("p1")
        out["load"] = "ok"
    except Exception:
        out["load"] = "error"
elif command.startswith("restore:"):
    store.restore_snapshot("p1", command.split(":", 1)[1])
    store.load_deck("p1")
    out["load"] = "ok"
elif command == "jobs":
    # 이 빌드의 앱으로 작업 목록을 조회한다(같은 자료 폴더의 원장을 읽는다)
    from fastapi.testclient import TestClient
    from slidecaptain.server.app import create_app
    with TestClient(create_app(store), headers={"X-Requested-With": "SlideCaptain"}) as client:
        response = client.get("/api/projects/p1/jobs")
        out["jobs"] = response.status_code
        out["reasons"] = [j["stale_reasons"] for j in response.json()] if response.status_code == 200 else None
        out["kinds"] = [j["kind"] for j in response.json()] if response.status_code == 200 else None
elif command.startswith("save:"):
    # 0.2.0 사용자가 덱을 열어 제목을 고치고 저장한다(화면의 저장은 직전 상태를 스냅샷으로 남긴다)
    deck = store.load_deck("p1")
    deck.meta.title = command.split(":", 1)[1]
    store.save_deck("p1", deck, snapshot=True)
    out["load"] = "ok"
print(json.dumps(out))
"""


def _extract(tmp_path_factory, ref: str, label: str) -> Path:
    target = tmp_path_factory.mktemp(label)
    archive = target / "code.tar"
    result = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", "-o", str(archive), ref, "backend/slidecaptain"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"{ref}의 코드를 꺼내지 못했습니다: {result.stderr}"
    with tarfile.open(archive) as tar:
        tar.extractall(target, filter="data")
    return target / "backend"


@pytest.fixture(scope="module")
def legacy_backend(tmp_path_factory):
    return _extract(tmp_path_factory, LEGACY_TAG, "legacy020")


@pytest.fixture(scope="module")
def interim_backend(tmp_path_factory):
    return _extract(tmp_path_factory, INTERIM_REF, "interim-d3a")


@pytest.fixture(scope="module")
def d3b_backend(tmp_path_factory):
    return _extract(tmp_path_factory, D3B_REF, "d3b")


def _run_legacy(legacy_backend: Path, root: Path, command: str) -> dict:
    env = {**os.environ, "PYTHONPATH": str(legacy_backend), "PYTHONUTF8": "1"}
    result = subprocess.run(
        # -P와 cwd: `python -c`는 현재 폴더를 import 경로 맨 앞에 두므로 저장소의 현재 코드가 잡힌다
        [sys.executable, "-P", "-c", _LEGACY_SCRIPT, str(root), str(legacy_backend), command],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120,
        cwd=legacy_backend,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _deck(report_type="research", title="보고"):
    return Deck(meta=DeckMeta(title=title, report_type=report_type))


def test_legacy_app_opens_a_project_saved_without_new_values(store, legacy_backend):
    store.create_project("p1")
    store.save_deck("p1", _deck(title="새 앱에서 고침"), snapshot=False)
    assert (store.root / "p1" / "manifest.json").exists()
    # D2b-1: 자료 루트의 작업 원장 파일이 0.2.0의 목록과 열기를 깨지 않는다
    ledger = JobLedger.open(store.root)
    ledger.create_job(project="p1", kind="structure", request_id="r1", params={}, instance_id="i1",
                      inputs=FixedInputs(None, None, None, None, None, None))
    ledger.close()
    assert (store.root / LEDGER_NAME).exists()
    out = _run_legacy(legacy_backend, store.root, "load")
    assert out == {"statuses": {"p1": "ok"}, "load": "ok"}


def test_legacy_app_sees_new_type_as_needing_recovery_and_pre_migration_snapshot_restores(store, legacy_backend):
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    out = _run_legacy(legacy_backend, store.root, "load")
    assert out == {"statuses": {"p1": "needs_recovery"}, "load": "error"}
    [pre] = [s for s in store.list_snapshots("p1") if s.kind == "pre_migration"]
    out = _run_legacy(legacy_backend, store.root, f"restore:{pre.id}")
    assert out["load"] == "ok"


def test_new_app_records_a_second_upgrade_after_legacy_restore(store, legacy_backend):
    store.create_project("p1")
    store.save_deck("p1", _deck("weekly"), snapshot=False)
    [pre] = [s for s in store.list_snapshots("p1") if s.kind == "pre_migration"]
    _run_legacy(legacy_backend, store.root, f"restore:{pre.id}")
    store.save_deck("p1", _deck("monthly"), snapshot=False)
    upgrades = [m for m in read_manifest(store.root / "p1").migrations if m.kind == "upgrade"]
    assert len(upgrades) == 2
    assert read_manifest(store.root / "p1").format_version == 2


# -- D3b-1: 새 항목 덱과 0.2.0, 중간 빌드 (계획 4.2) ------------------------------------------------

def _purpose_deck(**meta):
    meta.setdefault("title", "보고")
    return Deck(meta=DeckMeta(**meta))


def test_legacy_app_cannot_open_a_deck_with_purpose_content(store, legacy_backend):
    store.create_project("p1")
    store.save_deck("p1", _purpose_deck(report_type="approval", key_message="예산 증액을 승인받는다"), snapshot=False)
    out = _run_legacy(legacy_backend, store.root, "load")
    assert out == {"statuses": {"p1": "needs_recovery"}, "load": "error"}


def test_confirmed_type_alone_keeps_the_deck_open_in_the_legacy_app(store, legacy_backend):
    """유형 확인 표시는 형식 등급에 넣지 않는다 (계획 4.1의 Q1 해석)."""
    store.create_project("p1")
    store.save_deck("p1", _purpose_deck(report_type="approval", report_type_confirmed=True), snapshot=False)
    out = _run_legacy(legacy_backend, store.root, "load")
    assert out == {"statuses": {"p1": "ok"}, "load": "ok"}


def test_purpose_content_is_recoverable_after_a_legacy_restore_and_a_later_legacy_save(store, legacy_backend):
    store.create_project("p1")
    store.save_deck("p1", _purpose_deck(report_type="approval", key_message="핵심"), snapshot=False)
    [pre] = [s for s in store.list_snapshots("p1") if s.kind == "pre_migration"]
    _run_legacy(legacy_backend, store.root, f"restore:{pre.id}")
    # 쓰기 없이 목록에서 되찾을 지점이 보인다 (재리뷰 RR3)
    [mark] = [s for s in store.list_snapshots("p1") if s.kind == "before_revert"]
    _run_legacy(legacy_backend, store.root, "save:0.2.0에서 고침")
    assert [s.id for s in store.list_snapshots("p1") if s.kind == "before_revert"] == [mark.id]
    restored, _ = store.restore_snapshot("p1", mark.id)
    assert restored.meta.key_message == "핵심"


def test_legacy_edit_after_own_downgrade_is_kept_as_a_legacy_restore_point(store, legacy_backend):
    """새 앱이 등급 1로 내린 뒤 0.2.0이 고친 상태는 다음 올림의 강제 스냅샷에 남는다 (재리뷰 RR2)."""
    store.create_project("p1")
    store.save_deck("p1", _purpose_deck(key_message="핵심"), snapshot=False)
    store.save_deck("p1", _purpose_deck(), snapshot=False)
    _run_legacy(legacy_backend, store.root, "save:0.2.0 사용자가 고침")
    store.save_deck("p1", _purpose_deck(key_message="다시"), snapshot=False)
    restorable = []
    for snap in store.list_snapshots("p1"):
        data = json.loads((store.root / "p1" / "snapshots" / f"{snap.id}.json").read_text(encoding="utf-8"))
        restorable.append((snap.kind, data["meta"]["title"]))
    assert ("pre_migration", "0.2.0 사용자가 고침") in restorable


def test_interim_build_refuses_level_three_projects_without_touching_them(store, interim_backend):
    """중간 빌드(D2a~D3a)는 등급 3 프로젝트를 "더 새 형식"으로 거절한다 (리뷰 S4, 재리뷰 RR1)."""
    store.create_project("p1")
    store.save_deck("p1", _purpose_deck(key_message="핵심"), snapshot=False)
    store.create_project("p2")
    store.save_deck("p2", _purpose_deck(report_type="ir"), snapshot=False)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    out = _run_legacy(interim_backend, store.root, "load")
    assert out["statuses"] == {"p1": "newer_format", "p2": "newer_format"}
    assert out["load"] == "error"
    after = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert after == before


def test_interim_build_lists_jobs_with_new_relevance_markers(store, interim_backend):
    """같은 원장을 읽는 이전 빌드가 새 표지의 장과 구조안 행에서 500을 내지 않는다 (재리뷰 RR11)."""
    from fastapi.testclient import TestClient

    from slidecaptain.server.app import create_app
    from test_jobs_candidates import SLOTS, _two_chapters
    from test_jobs_candidates import GateProvider as ChapterGate

    from slidecaptain.pipeline.provider import ProviderResponse
    from test_jobs_api import STRUCTURE

    class Provider(ChapterGate):
        async def complete(self, prompt, schema):
            if "chapters" in schema.get("properties", {}):  # 구조안 요청
                return ProviderResponse(structured=STRUCTURE, raw_text="r")
            return await super().complete(prompt, schema)

    _two_chapters(store)
    store.write_source("p1", "자료.md", "시장 규모는 500억 원이다")
    provider = Provider(SLOTS)
    provider.release.set()
    headers = {"X-Requested-With": "SlideCaptain", "X-AI-Consent": "SlideCaptain"}
    relevance = {}
    with TestClient(create_app(store, provider=provider), headers=headers) as client:
        for kind, params in (("chapter", {"chapter_id": "c1"}), ("structure", {})):
            job = client.post("/api/projects/p1/jobs", json={"request_id": f"{kind}-0001", "kind": kind,
                                                             "params": params}).json()
            assert client.app.state.job_runner._handles[job["id"]].wait_sync(10) is not None
            view = client.get(f"/api/projects/p1/jobs/{job['id']}").json()
            assert view["candidate_status"] == "held", view
            relevance[kind] = view["relevance_hash"]
    assert relevance["chapter"].startswith("c1:") and relevance["chapter"].count("|") == 2
    assert relevance["structure"].startswith("s1:")
    out = _run_legacy(interim_backend, store.root, "jobs")
    assert out["jobs"] == 200
    reasons = dict(zip(out["kinds"], out["reasons"]))
    # 이전 빌드는 표지 때문에 장 템플릿이 다르다고 보고(계산식도 달라 보고 계획 변경도 함께 나온다) 반영하지 않는다
    assert "template_changed" in reasons["chapter"]
    # 구조안 행은 이전 빌드가 ETag로 판정한다. 덱이 그대로라 사유가 없다 (D3b-2 리뷰 R8)
    assert reasons["structure"] == []


# -- 직접 수정 (D3c-1, 계획 4.2) ------------------------------------------------------------------

def _edited_deck(title="보고"):
    from slidecaptain.models.deck import Chapter, Slide, Structure

    return Deck(meta=DeckMeta(title=title), structure=Structure(chapters=[Chapter(id="c1", topic="장", template="callout")]),
                slides=[Slide(chapter_id="c1", slots={"template": "callout", "text": "핵심"},
                              direct_edits={"text": {"dx_pt": 12, "dy_pt": 8}})])


def test_d3b_build_refuses_level_four_projects_without_touching_them(store, d3b_backend):
    """D3b 빌드가 등급 4 덱을 열어 저장하면 수정값을 지운다. 그래서 manifest 형식 4로 거절하게 한다."""
    store.create_project("p1")
    store.save_deck("p1", _edited_deck(), snapshot=False)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    out = _run_legacy(d3b_backend, store.root, "load")
    assert out["statuses"] == {"p1": "newer_format"}
    assert out["load"] == "error"
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before


def test_d3b_build_lists_jobs_with_batch_relevance_and_applied_candidates(store, d3b_backend):
    """D3c는 묶음 부모의 relevance_hash에 장별 해시("b1:")를 담고 장 후보를 적용 라우트로 반영한다. 원장 형식 번호는 그대로이므로
    같은 자료 폴더를 여는 D3b 빌드의 작업 목록이 깨지지 않아야 한다 (계획 4.2, 리뷰 저장 S27)."""
    from fastapi.testclient import TestClient

    from slidecaptain.pipeline.relevance import BATCH_MARKER
    from slidecaptain.server.app import create_app
    from tests import test_candidate_apply_api as apply
    from tests import test_jobs_batch as batch

    batch._project(store)
    provider = batch.ChapterProvider([batch.slots("하나"), batch.slots("둘"), batch.slots("셋")], gate_at=2)
    with TestClient(create_app(store, provider=provider), headers=batch.HEADERS) as client:
        single = apply._job(client, "chapter-0001", chapter_id="c1")
        assert apply._apply(client, store, single["id"]).status_code == 200
        job = batch._register(client, store, ["c2", "c3"]).json()
        assert provider.entered.wait(10)
        current = store.load_deck("p1")
        current.meta.presenter = "다른 창의 편집"
        store.save_deck("p1", current, snapshot=False)
        provider.release.set()
        view = batch._wait(client, job["id"])
    assert view["relevance_hash"].startswith(BATCH_MARKER)
    assert [c["candidate_status"] for c in view["chapters"]] == ["applied", "stale"]
    out = _run_legacy(d3b_backend, store.root, "jobs")
    assert out["jobs"] == 200
    assert sorted(out["kinds"]) == ["chapter", "chapters"]


def test_legacy_app_sees_level_four_as_needing_recovery_and_the_new_app_marks_the_revert(store, legacy_backend):
    """0.2.0은 schema_version 3을 거절해 복구 필요로 본다. 0.2.0에서 복원하면 이 앱은 되돌리기 직전 덱을 표시하고
    머리에 알린다 (계획 리뷰 저장 S4: 1판대로면 표시가 0개였다)."""
    store.create_project("p1")
    store.save_deck("p1", _edited_deck(), snapshot=False)
    out = _run_legacy(legacy_backend, store.root, "load")
    assert out["statuses"] == {"p1": "needs_recovery"}
    [pre] = [s for s in store.list_snapshots("p1") if s.kind == "pre_migration"]
    _run_legacy(legacy_backend, store.root, f"restore:{pre.id}")
    [mark] = [s for s in store.list_snapshots("p1") if s.kind == "before_revert"]
    [info] = store.list_projects()
    assert info.reverted_by_other_app is True
    restored, _ = store.restore_snapshot("p1", mark.id)
    assert restored.slides[0].direct_edits["text"].dx_pt == 12
