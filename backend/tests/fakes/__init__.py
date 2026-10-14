"""시험 전용 대역. 패키지(backend/slidecaptain)에 포함되지 않는다."""

import os
import stat
import sys
from pathlib import Path

FAKE_CLAUDE_SCRIPT = Path(__file__).with_name("fake_claude_cli.py")


def make_fake_cli(folder: Path) -> Path:
    """가짜 Claude CLI의 실행 래퍼를 만든다. SLIDECAPTAIN_CLAUDE_CLI에 이 경로를 준다.

    POSIX 전용이다. claude-agent-sdk가 cli_path를 실행 파일로 직접 띄우므로 Windows에서는
    .cmd 래퍼를 쓸 수 없다. Windows의 별도 프로세스 시험은 D2b-6에서 따로 정한다.
    """
    if os.name == "nt":
        raise RuntimeError("가짜 CLI 래퍼는 POSIX에서만 만든다")
    folder.mkdir(parents=True, exist_ok=True)
    wrapper = folder / "fake-claude"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE_SCRIPT}" "$@"\n', encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper
