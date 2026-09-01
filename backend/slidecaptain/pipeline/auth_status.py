"""AI 연결 상태 확인: Claude CLI의 `auth status`로 로그인 여부만 읽는다 (계획서 2026-09-01 태스크 4).

모델을 호출하지 않으므로 구독 사용량이 들지 않는다. 자격 증명 파일은 토큰이 들어 있어 읽지 않고,
CLI 출력 가운데 로그인 여부, 방식, 계정(가린 형태)만 전달한다.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

ENV_CLI = "SLIDECAPTAIN_CLAUDE_CLI"
_SHIM_SUFFIXES = {".cmd", ".bat"}  # npm 설치본의 배치 셰도는 shell=False로 실행할 수 없다


class LoginStatus(BaseModel):
    logged_in: bool | None = None  # None = 확인하지 못함 (error에 사유)
    auth_method: str | None = None
    account: str | None = None  # 가린 이메일 (co***@example.com)
    cli_version: str | None = None  # 해석 실패 시 사용자가 알아차리도록 함께 보여준다
    error: str | None = None


def mask_email(email: str) -> str:
    local, at, domain = email.partition("@")
    head = local[:2]
    return f"{head}***@{domain}" if at else f"{head}***"


def _bundled_cli_path() -> Path:
    import claude_agent_sdk

    name = "claude.exe" if sys.platform == "win32" else "claude"
    return Path(claude_agent_sdk.__file__).resolve().parent / "_bundled" / name


def resolve_cli_path() -> Path | None:
    """환경 변수 → SDK 동봉 CLI → PATH의 네이티브 실행 파일 순서. 생성 파이프라인이 실제로 쓰는 것이 동봉 CLI라 그것을 먼저 본다."""
    override = os.environ.get(ENV_CLI)
    if override:
        p = Path(override)
        return p if p.is_file() else None
    bundled = _bundled_cli_path()
    if bundled.is_file():
        return bundled
    for name in ("claude.exe", "claude"):
        found = shutil.which(name)
        if found and Path(found).suffix.lower() not in _SHIM_SUFFIXES:
            return Path(found)
    return None


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _cli_version(cli: Path, timeout_sec: float) -> str | None:
    try:
        proc = subprocess.run([str(cli), "--version"], capture_output=True, timeout=timeout_sec)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.decode("utf-8", errors="replace").strip()[:60] or None


def check_login(timeout_sec: float = 10.0, cli: Path | None = None) -> LoginStatus:
    """`claude auth status`를 실행해 로그인 상태를 읽는다. 어떤 실패도 예외로 올리지 않고 error 필드로 보고한다."""
    cli = cli or resolve_cli_path()
    if cli is None:
        return LoginStatus(error="Claude CLI를 찾지 못했습니다. Claude Code가 설치되어 있는지 확인해 주세요.")
    try:
        proc = subprocess.run([str(cli), "auth", "status"], capture_output=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return LoginStatus(error=f"Claude CLI가 {timeout_sec:g}초 안에 응답이 없습니다.")
    except OSError as e:
        return LoginStatus(error=f"Claude CLI를 실행하지 못했습니다: {e}")
    data = _extract_json(proc.stdout.decode("utf-8", errors="replace"))
    if data is None:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        detail = f": {stderr[:200]}" if stderr else ""
        return LoginStatus(
            cli_version=_cli_version(cli, timeout_sec),
            error=f"Claude CLI의 응답을 해석하지 못했습니다(종료 코드 {proc.returncode}){detail}",
        )
    email = data.get("email")
    return LoginStatus(
        logged_in=bool(data.get("loggedIn")),
        auth_method=data.get("authMethod"),
        account=mask_email(email) if isinstance(email, str) and email else None,
    )
