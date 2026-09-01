"""로그인 상태 확인 모듈 테스트 (계획서 2026-09-01 태스크 4). 실제 CLI를 띄우지 않는다."""

import subprocess

from slidecaptain.pipeline import auth_status
from slidecaptain.pipeline.auth_status import LoginStatus, check_login, mask_email, resolve_cli_path


def test_mask_email_keeps_two_chars_and_domain():
    assert mask_email("cobain@gmail.com") == "co***@gmail.com"
    assert mask_email("a@b.co") == "a***@b.co"
    assert mask_email("noatsign") == "no***"


def test_resolve_prefers_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("SLIDECAPTAIN_CLAUDE_CLI", str(exe))
    assert resolve_cli_path() == exe


def test_resolve_prefers_bundled_cli_over_path(tmp_path, monkeypatch):
    monkeypatch.delenv("SLIDECAPTAIN_CLAUDE_CLI", raising=False)
    bundled = tmp_path / "bundled" / "claude.exe"
    bundled.parent.mkdir()
    bundled.write_bytes(b"")
    monkeypatch.setattr(auth_status, "_bundled_cli_path", lambda: bundled)
    other = tmp_path / "other" / "claude.exe"
    monkeypatch.setattr(auth_status.shutil, "which", lambda name: str(other))
    assert resolve_cli_path() == bundled


def test_resolve_skips_cmd_shim(tmp_path, monkeypatch):
    # npm 설치본의 claude.cmd 셰도는 SDK가 거부하는 CLI라 표시용도 같은 기준으로 채택하지 않는다 (2026-09-01 근거 정정)
    monkeypatch.delenv("SLIDECAPTAIN_CLAUDE_CLI", raising=False)
    monkeypatch.setattr(auth_status, "_bundled_cli_path", lambda: tmp_path / "missing" / "claude.exe")
    monkeypatch.setattr(
        auth_status.shutil, "which",
        lambda name: None if name == "claude.exe" else str(tmp_path / "npm" / "claude.cmd"),
    )
    assert resolve_cli_path() is None


def test_resolve_uses_native_exe_from_path(tmp_path, monkeypatch):
    monkeypatch.delenv("SLIDECAPTAIN_CLAUDE_CLI", raising=False)
    monkeypatch.setattr(auth_status, "_bundled_cli_path", lambda: tmp_path / "missing" / "claude.exe")
    native = tmp_path / "bin" / "claude.exe"
    native.parent.mkdir()
    native.write_bytes(b"")
    monkeypatch.setattr(auth_status.shutil, "which", lambda name: str(native) if name == "claude.exe" else None)
    assert resolve_cli_path() == native


def _fake_run(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    return run


STATUS_JSON = (
    b'{\n  "loggedIn": true,\n  "authMethod": "claude.ai",\n  "apiProvider": "firstParty",\n'
    b'  "email": "cobain@gmail.com",\n  "orgId": "abc"\n}\n'
)


def test_check_login_parses_cli_json_and_masks_email(tmp_path, monkeypatch):
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(auth_status.subprocess, "run", _fake_run(stdout=STATUS_JSON))
    status = check_login(cli=exe)
    assert status == LoginStatus(logged_in=True, auth_method="claude.ai", account="co***@gmail.com")
    assert status.error is None


def test_check_login_logged_out(tmp_path, monkeypatch):
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(auth_status.subprocess, "run", _fake_run(stdout=b'{"loggedIn": false}'))
    status = check_login(cli=exe)
    assert status.logged_in is False
    assert status.account is None
    assert status.error is None


def test_check_login_when_cli_missing(monkeypatch):
    monkeypatch.setattr(auth_status, "resolve_cli_path", lambda: None)
    status = check_login()
    assert status.logged_in is None
    assert "찾지 못했습니다" in status.error


def test_check_login_when_spawn_fails(tmp_path, monkeypatch):
    def run(cmd, **kwargs):
        raise OSError(193, "not a valid Win32 application")
    monkeypatch.setattr(auth_status.subprocess, "run", run)
    status = check_login(cli=tmp_path / "claude.cmd")
    assert status.logged_in is None
    assert "실행하지 못했습니다" in status.error


def test_check_login_when_cli_hangs(tmp_path, monkeypatch):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))
    monkeypatch.setattr(auth_status.subprocess, "run", run)
    status = check_login(cli=tmp_path / "claude.exe", timeout_sec=3)
    assert status.logged_in is None
    assert "응답하지 않았습니다" in status.error


def test_check_login_when_output_is_not_json(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_status.subprocess, "run", _fake_run(stdout=b"Some banner text", returncode=1))
    status = check_login(cli=tmp_path / "claude.exe")
    assert status.logged_in is None
    assert "해석하지 못했습니다" in status.error
    assert status.cli_version == "Some banner text"  # 해석 실패 시 CLI 버전(--version 출력)을 동봉한다


def test_check_login_when_logged_in_key_missing(tmp_path, monkeypatch):
    # 형식이 바뀐 JSON은 "로그인 안 됨"이 아니라 "확인하지 못함"으로 보고해야 한다 (2026-09-01 리뷰 반영)
    monkeypatch.setattr(auth_status.subprocess, "run", _fake_run(stdout=b'{"status": "authenticated"}'))
    status = check_login(cli=tmp_path / "claude.exe")
    assert status.logged_in is None
    assert "loggedIn" in status.error


def test_check_login_tolerates_non_string_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_status.subprocess, "run",
                        _fake_run(stdout=b'{"loggedIn": true, "authMethod": 7, "email": 12}'))
    status = check_login(cli=tmp_path / "claude.exe")
    assert status.logged_in is True
    assert status.auth_method is None
    assert status.account is None


def test_check_login_when_env_override_points_to_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIDECAPTAIN_CLAUDE_CLI", str(tmp_path / "없는파일.exe"))
    status = check_login()
    assert status.logged_in is None
    assert "SLIDECAPTAIN_CLAUDE_CLI" in status.error
