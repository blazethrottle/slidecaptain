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
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def legacy_backend(tmp_path_factory):
    target = tmp_path_factory.mktemp("legacy020")
    archive = target / "legacy.tar"
    result = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", "-o", str(archive), LEGACY_TAG, "backend/slidecaptain"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"{LEGACY_TAG} 태그의 코드를 꺼내지 못했습니다: {result.stderr}"
    with tarfile.open(archive) as tar:
        tar.extractall(target, filter="data")
    return target / "backend"


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
