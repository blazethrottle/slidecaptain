"""자료 폴더 단일 서비스 잠금 (개정판 D2a-3).

새 버전끼리 같은 자료 폴더를 동시에 쓰지 않게 한다. 배포된 0.2.0은 이 잠금을 모르므로 막지
못한다(계획서 8절 가정 2). Windows 실기기 확인은 CI로 갈음한다(사용자 결정 2026-10-08).
"""

import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from slidecaptain.storage import service_lock
from slidecaptain.storage.service_lock import DataDirInUse, acquire_service_lock

BACKEND = Path(__file__).resolve().parents[1]

_HOLDER = r"""
import sys, time
from pathlib import Path
from slidecaptain.storage.service_lock import acquire_service_lock
lock = acquire_service_lock(Path(sys.argv[1]), timeout=0.5)
if sys.argv[2] == "child":
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
print("held", flush=True)
sys.stdin.read()
"""


def _env():
    return {**os.environ, "PYTHONPATH": str(BACKEND), "PYTHONUTF8": "1"}


def _start_holder(data_dir: Path, mode: str = "plain") -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-P", "-c", _HOLDER, str(data_dir), mode],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=_env())
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_second_service_on_the_same_folder_is_refused_with_holder_info(tmp_path):
    holder = _start_holder(tmp_path / "data")
    try:
        with pytest.raises(DataDirInUse) as caught:
            acquire_service_lock(tmp_path / "data", timeout=0.3)
        assert caught.value.holder["pid"] == holder.pid
        assert caught.value.holder["product"] == "slidecaptain"
    finally:
        holder.stdin.close()
        holder.wait(10)


def test_different_folders_can_run_together(tmp_path):
    holder = _start_holder(tmp_path / "a")
    try:
        lock = acquire_service_lock(tmp_path / "b", timeout=0.3)
        assert not lock.unsupported
        lock.close()
    finally:
        holder.stdin.close()
        holder.wait(10)


def test_lock_is_free_after_normal_exit_and_after_kill(tmp_path):
    data = tmp_path / "data"
    holder = _start_holder(data)
    holder.stdin.close()
    holder.wait(10)
    acquire_service_lock(data, timeout=5).close()
    holder = _start_holder(data)
    holder.kill()
    holder.wait(10)
    acquire_service_lock(data, timeout=service_lock.RETRY_SECONDS).close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX 자식 상속 확인. Windows는 핸들 비상속이 기본이다")
def test_lock_is_free_after_kill_even_if_a_child_survives(tmp_path):
    data = tmp_path / "data"
    holder = _start_holder(data, "child")
    holder.kill()
    holder.wait(10)
    acquire_service_lock(data, timeout=service_lock.RETRY_SECONDS).close()


def test_lock_descriptor_is_not_inherited_and_lock_file_is_kept(tmp_path):
    lock = acquire_service_lock(tmp_path / "data", timeout=0.3)
    assert os.get_inheritable(lock.fd) is False
    lock.close()
    assert (tmp_path / "data" / service_lock.LOCK_NAME).exists()
    info = json.loads((tmp_path / "data" / service_lock.INFO_NAME).read_text(encoding="utf-8"))
    assert info["pid"] == os.getpid()


def test_unsupported_locking_runs_without_lock_and_reports_it(tmp_path):
    def unsupported(fd):
        raise OSError(errno.ENOTSUP, "잠금 미지원 흉내")

    lock = acquire_service_lock(tmp_path / "data", timeout=0.3, try_lock=unsupported)
    assert lock.unsupported is True
    lock.close()


def test_desktop_service_reports_data_dir_in_use_as_error_record(tmp_path):
    data = tmp_path / "data"
    holder = _start_holder(data)
    try:
        env = {**_env(), "SLIDECAPTAIN_DESKTOP_SESSION": "s" * 64, "SLIDECAPTAIN_DESKTOP_INSTANCE": "abc123"}
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-P", "-m", "slidecaptain.desktop_service", "--data-dir", str(data)],
                                capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        assert result.returncode == service_lock.EXIT_DATA_DIR_IN_USE
        record = json.loads(result.stdout.strip().splitlines()[-1])
        assert record == {"event": "error", "product": "slidecaptain", "desktop_instance_id": "abc123",
                          "code": "data_dir_in_use", "holder_started_at": record["holder_started_at"]}
        assert record["holder_started_at"]
        assert time.monotonic() - started < 30
    finally:
        holder.stdin.close()
        holder.wait(10)


def test_web_serve_refuses_before_any_setup_when_folder_is_in_use(tmp_path):
    data = tmp_path / "data"
    holder = _start_holder(data)
    try:
        result = subprocess.run([sys.executable, "-P", "-m", "slidecaptain", "serve", "--data-dir", str(data)],
                                capture_output=True, text=True, encoding="utf-8", env=_env(), timeout=60)
        assert result.returncode == service_lock.EXIT_DATA_DIR_IN_USE
        assert "다른 SlideCaptain" in result.stderr
        assert "Errno" not in result.stderr
        assert "폰트" not in result.stdout + result.stderr  # 폰트 설치 같은 준비보다 먼저 거절한다
    finally:
        holder.stdin.close()
        holder.wait(10)


def test_status_reports_data_folder_project_count_and_lock_state(store):
    from fastapi.testclient import TestClient

    from slidecaptain.server.app import create_app

    store.create_project("p1")
    client = TestClient(create_app(store, data_dir_lock="unsupported"))
    data_dir = client.get("/api/status").json()["data_dir"]
    assert data_dir == {"path": str(store.root), "project_count": 1, "lock": "unsupported"}
