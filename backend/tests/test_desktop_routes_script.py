"""독립 앱 브리지 경로 대조 도구의 인코딩 (최종 리뷰 SV-07, 2026-10-16 회사 PC 실측).

`backend/openapi.json`에는 한글 설명이 들어 있다. 도구가 운영체제 기본 인코딩으로 읽으면 Windows(cp949, cp1252)
에서 UnicodeDecodeError로 멈춘다. CI는 PYTHONUTF8=1을 전역으로 켜므로 이 차이를 보지 못한다. 그래서 UTF-8 모드를
끈 별도 프로세스로 실행한다.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_route_check_runs_without_python_utf8_mode():
    env = {key: value for key, value in os.environ.items() if key != "PYTHONUTF8"}
    result = subprocess.run([sys.executable, "-X", "utf8=0", str(ROOT / "scripts" / "check_desktop_routes.py")],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "native API routes match OpenAPI" in result.stdout
