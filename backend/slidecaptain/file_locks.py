"""OS 파일 잠금 기본 동작 (내보내기 게시 잠금과 자료 폴더 서비스 잠금이 함께 쓴다).

2026-10-08 D2a-3: export/locking.py에서 옮겼다. 동작은 같다.
"""

import os

if os.name == "nt":
    import msvcrt

    def try_lock(fd: int) -> None:
        # Windows locks from the current offset and permits ranges beyond EOF.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def try_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
