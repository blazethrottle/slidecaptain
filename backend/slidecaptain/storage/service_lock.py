"""자료 폴더 단일 서비스 잠금 (개정판 D2a-3).

새 버전의 서비스(독립 앱 서비스와 웹 모드 serve)는 시작할 때 자료 루트의 잠금 파일에 OS 잠금을
건다. 같은 폴더를 다른 서비스가 쥐고 있으면 시작하지 않는다. 프로세스가 끝나면 OS가 잠금을 푼다.

한계: 배포된 0.2.0은 이 잠금을 모르므로 0.2.0과 함께 켜면 막지 못한다. iCloud 같은 동기화
폴더는 잠금이 성공해도 다른 기기와 공유되지 않는다. 잠금 자체를 지원하지 않는 파일 시스템에서는
시작을 거절하지 않고 잠금 없이 실행하며, 그 사실을 상태 API로 화면에 알린다.
"""

import errno
import json
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from slidecaptain import __version__
from slidecaptain.file_locks import try_lock as _os_try_lock

LOCK_NAME = ".slidecaptain-service.lock"  # 점으로 시작해 프로젝트 이름과 겹치지 않는다. 지우지 않는다
INFO_NAME = ".slidecaptain-service.json"  # Windows 잠금은 잠근 범위를 읽지 못하게 하므로 별도 파일에 둔다
# 잠금을 얻지 못했을 때 기다리는 시간. 근거: D1 macOS 실측(앱 본체 강제 종료 뒤 서비스가 약 2초 안에
# 스스로 끝남)과 내보내기 게시 잠금의 재시도 시간(export/locking.py의 5초). Windows가 종료한
# 프로세스의 잠금을 늦게 푸는 경우도 이 시간이 흡수한다(Microsoft LockFile 문서는 해제 시점을 보장하지 않는다)
RETRY_SECONDS = 5.0
EXIT_DATA_DIR_IN_USE = 3
_BUSY = {errno.EACCES, errno.EAGAIN}
_UNSUPPORTED = {errno.ENOLCK, getattr(errno, "ENOTSUP", -1), getattr(errno, "EOPNOTSUPP", -1)}

IN_USE_MESSAGE = (
    "같은 자료 폴더를 다른 SlideCaptain이 사용하고 있습니다. 다른 SlideCaptain 창이나 웹 실행 창을 "
    "닫은 뒤 다시 실행해 주세요."
)


class DataDirInUse(OSError):
    def __init__(self, holder: dict | None):
        super().__init__(errno.EBUSY, IN_USE_MESSAGE)
        self.holder = holder or {}

    def __str__(self) -> str:  # OSError의 "[Errno 16]" 머리말 없이 사용자 문구만 보인다
        return IN_USE_MESSAGE


class ServiceLock:
    def __init__(self, fd: int | None, unsupported: bool):
        self.fd = fd
        self.unsupported = unsupported

    @property
    def state(self) -> str:
        return "unsupported" if self.unsupported else "held"

    def close(self) -> None:
        """잠금을 놓는다. 잠금 파일은 지우지 않는다(지우는 사이 다른 서비스가 새 파일을 잠그는 경합)."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _read_holder(data_dir: Path) -> dict | None:
    try:
        holder = json.loads((data_dir / INFO_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return holder if isinstance(holder, dict) else None


def _write_holder(data_dir: Path) -> None:
    info = {
        "product": "slidecaptain",
        "version": __version__,
        "pid": os.getpid(),
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    tmp = data_dir / f".slidecaptain-service-{os.getpid()}.tmp"
    try:
        tmp.write_text(json.dumps(info), encoding="utf-8")
        os.replace(tmp, data_dir / INFO_NAME)
    except OSError:
        # 진단 정보는 부가 기록이다. 쓰지 못해도 잠금은 유효하다
        try:
            tmp.unlink()
        except OSError:
            pass


def acquire_service_lock(
    data_dir: Path,
    *,
    timeout: float = RETRY_SECONDS,
    try_lock: Callable[[int], None] = _os_try_lock,
) -> ServiceLock:
    """자료 폴더를 만들고 잠금을 얻는다. 다른 서비스가 쥐고 있으면 DataDirInUse."""
    data_dir.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(data_dir / LOCK_NAME, flags, 0o600)
    os.set_inheritable(fd, False)  # 자식 CLI가 잠금을 물려받아 서비스 종료 뒤에도 쥐지 않게 한다
    deadline = time.monotonic() + timeout
    while True:
        try:
            try_lock(fd)
            break
        except OSError as exc:
            if exc.errno in _UNSUPPORTED:
                return ServiceLock(fd, unsupported=True)
            if exc.errno not in _BUSY:
                os.close(fd)
                raise
            if time.monotonic() >= deadline:
                os.close(fd)
                raise DataDirInUse(_read_holder(data_dir)) from exc
            time.sleep(0.05)
    _write_holder(data_dir)
    return ServiceLock(fd, unsupported=False)
