"""원인 분류와 오류 코드 (개정판 D3a-4, 계획 4.3, 사실 7, 17).

실제 AI 호출은 없다. 원장 행은 실제 실행기로 만들고, 읽기 관대화는 원장 파일에 값을 직접 써서 확인한다.
"""

import sqlite3

from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.job_ledger import LEDGER_NAME
from tests.test_jobs_api import HEADERS, GateProvider, _project, _register, _wait, manager  # noqa: F401


def _finished_job(client):
    job = _register(client).json()
    _wait(client, job["id"])
    return job["id"]


# 회귀 RED(사실 17): 지금 코드는 응답 모델이 원인 분류를 고정 목록으로 검증해, 원장 행 하나가 모르는 값을
# 가지면 작업 조회, 작업 목록, 진행 API가 모두 500이다(리뷰 탐침)

def test_unknown_error_class_in_the_ledger_reads_as_internal_and_keeps_the_original(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job_id = _finished_job(client)
        with sqlite3.connect(store.root / LEDGER_NAME) as conn:
            conn.execute("UPDATE jobs SET state = 'failed', error_class = 'future_class', error_status = 500, "
                         "error_detail = '다른 빌드가 쓴 값' WHERE id = ?", (job_id,))
        one = client.get(f"/api/projects/p1/jobs/{job_id}")
        listed = client.get("/api/projects/p1/jobs")
        progress = client.get("/api/projects/p1/progress")
    assert (one.status_code, listed.status_code, progress.status_code) == (200, 200, 200)
    error = one.json()["error"]
    assert error["error_class"] == "internal" and error["raw_error_class"] == "future_class"
    assert listed.json()[0]["error"]["error_class"] == "internal"
    assert progress.json()["jobs"][0]["error"]["raw_error_class"] == "future_class"


def test_known_error_class_is_read_as_is_without_a_raw_value(store):
    _project(store)
    provider = GateProvider()
    provider.release.set()
    with TestClient(create_app(store, provider=provider), headers=HEADERS) as client:
        job_id = _finished_job(client)
        with sqlite3.connect(store.root / LEDGER_NAME) as conn:
            conn.execute("UPDATE jobs SET state = 'failed', error_class = 'connection', error_status = 503 WHERE id = ?",
                         (job_id,))
        error = client.get(f"/api/projects/p1/jobs/{job_id}").json()["error"]
    assert (error["error_class"], error["raw_error_class"]) == ("connection", None)


# -- 두 허용값 목록과 오류 자리 대응표 (D3a-4, 계획 4.3) ---------------------------------------------

def test_ledger_write_classes_and_response_classes_are_the_same_set():
    from typing import get_args

    from slidecaptain.models.jobs import ErrorClass
    from slidecaptain.storage.job_ledger import ERROR_CLASSES

    assert set(ERROR_CLASSES) == set(get_args(ErrorClass))
    assert {"storage", "internal"} <= set(ERROR_CLASSES)


# 오류 자리 대응표: (파일, 문구 앞부분, 클래스, 코드). 예외 클래스가 아니라 던지는 자리마다 원인 코드를 붙인다.
# 한 자리가 둘 이상의 원인을 함께 받으면 넓은 코드 provider_call_failed다(Claude의 CLI 오류: 미로그인과 한도)
RAISE_SITES = [
    ("pipeline/subscription.py", "Claude Code를 찾지 못했습니다. 네이티브", "ProviderNotAvailable", "provider_missing"),
    ("pipeline/subscription.py", "AI 응답이 너무 오래 걸려", "ProviderCallFailed", "provider_timeout"),
    ("pipeline/subscription.py", "Claude Code를 찾지 못했습니다. 이 앱의", "ProviderNotAvailable", "provider_missing"),
    ("pipeline/subscription.py", "AI 호출에 실패했습니다.", "ProviderCallFailed", "provider_call_failed"),
    ("pipeline/subscription.py", "AI 호출이 정상적으로 끝나지 않았습니다.", "ProviderCallFailed", "provider_disconnected"),
    ("pipeline/subscription.py", "AI 호출이 정상적으로 끝나지 않았습니다.", "ProviderCallFailed", "<429이면 provider_limit>"),
    ("pipeline/codex.py", "공식 로그인 주소를 확인하지 못했습니다.", "ProviderNotAvailable", "provider_call_failed"),
    ("pipeline/codex.py", "공식 로그인 주소를 확인하지 못했습니다.", "ProviderNotAvailable", "provider_call_failed"),
    ("pipeline/codex.py", "Codex CLI를 찾지 못했습니다.", "ProviderNotAvailable", "provider_missing"),
    ("pipeline/codex.py", "Codex를 실행하지 못했습니다.", "ProviderNotAvailable", "provider_missing"),
    ("pipeline/codex.py", "Codex 연결이 종료되었습니다.", "ProviderNotAvailable", "provider_disconnected"),
    ("pipeline/codex.py", "Codex 연결이 끊겼습니다.", "ProviderNotAvailable", "provider_disconnected"),
    ("pipeline/codex.py", "Codex 응답 시간이 초과되었습니다.", "ProviderNotAvailable", "provider_timeout"),
    ("pipeline/codex.py", "Codex 요청을 완료하지 못했습니다.", "ProviderNotAvailable", "provider_call_failed"),
    ("pipeline/codex.py", "모델 목록을 끝까지 읽지 못했습니다.", "ProviderNotAvailable", "provider_call_failed"),
    ("pipeline/codex.py", "로그인 요청을 확인하지 못했습니다.", "ProviderNotAvailable", "provider_call_failed"),
    ("pipeline/codex.py", "이 응답 스키마는 ChatGPT", "ProviderNotAvailable", "provider_unsupported"),
    ("pipeline/codex.py", "가변 키 응답 스키마는", "ProviderNotAvailable", "provider_unsupported"),
    ("pipeline/codex.py", "ChatGPT 구독 로그인이 필요합니다.", "ProviderNotAvailable", "login_required"),
    ("pipeline/codex.py", "ChatGPT 생성을 취소했습니다.", "ProviderCallFailed", "provider_cancelled"),
    ("pipeline/codex.py", "ChatGPT 응답 시간이 초과되었습니다.", "ProviderCallFailed", "provider_timeout"),
    ("pipeline/codex.py", "ChatGPT 연결이 종료되었습니다.", "ProviderCallFailed", "provider_disconnected"),
    ("pipeline/codex.py", "ChatGPT 생성을 완료하지 못했습니다.", "ProviderCallFailed", "provider_call_failed"),
    ("pipeline/codex.py", "Codex 응답 형식을 읽지 못했습니다.", "ProviderCallFailed", "provider_call_failed"),
    ("pipeline/connections.py", "Claude Code를 찾지 못했습니다. 설치 후", "ProviderNotAvailable", "provider_missing"),
    ("pipeline/connections.py", "Claude Code 로그인 창을 열지 못했습니다.", "ProviderNotAvailable", "provider_missing"),
    ("pipeline/connections.py", "AI 생성이 진행 중입니다.", "ConnectionConflict", "settings_busy"),
    ("pipeline/connections.py", "AI 서비스 또는 모델이 변경되었습니다.", "ConnectionConflict", "selection_changed"),
    ("pipeline/connections.py", "로그인을 완료한 뒤 생성해 주세요.", "ConnectionConflict", "login_pending"),
    ("pipeline/connections.py", "AI 연결 상태가 변경되었습니다.", "ConnectionConflict", "identity_changed"),
    ("pipeline/connections.py", "AI 연결에 로그인되어 있지 않습니다.", "ProviderNotAvailable", "login_required"),
    ("pipeline/connections.py", "AI 도구를 찾지 못했습니다.", "ProviderNotAvailable", "provider_missing"),
    ("pipeline/connections.py", "AI 연결 상태 확인이 시간 안에 끝나지 않았습니다.", "ProviderNotAvailable", "provider_timeout"),
    ("pipeline/connections.py", "구독 로그인을 확인해 주세요.", "ProviderNotAvailable", "login_required"),
    ("pipeline/connections.py", "AI 연결 상태를 확인하지 못했습니다.", "ProviderNotAvailable", "provider_call_failed"),
    ("pipeline/connections.py", "선택한 모델을 사용할 수 없습니다.", "ProviderNotAvailable", "model_unavailable"),
    ("server/app.py", "AI 서비스 또는 모델이 변경되었습니다.", "ConnectionConflict", "selection_changed"),
]


def _raise_sites():
    """slidecaptain 아래의 모든 raise ProviderNotAvailable/ProviderCallFailed/ConnectionConflict를 읽는다."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "slidecaptain"
    found = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                    and isinstance(node.exc.func, ast.Name)
                    and node.exc.func.id in ("ProviderNotAvailable", "ProviderCallFailed", "ConnectionConflict")):
                continue
            text = "".join(part.value for part in ast.walk(node.exc.args[0])
                           if isinstance(part, ast.Constant) and isinstance(part.value, str))
            code = next((k.value for k in node.exc.keywords if k.arg == "code"), None)
            value = code.value if isinstance(code, ast.Constant) else ("<429이면 provider_limit>" if code else None)
            found.append((path.relative_to(root).as_posix(), text, node.exc.func.id, value))
    return found


def test_every_raise_site_carries_the_code_in_the_table():
    """새 raise 자리가 생기면 이 표에 코드와 함께 더해야 한다. 코드 없는 자리는 원인을 가를 수 없다."""
    remaining = list(RAISE_SITES)
    for path, text, cls, code in _raise_sites():
        match = next((row for row in remaining
                      if row[0] == path and text.startswith(row[1]) and row[2] == cls and row[3] == code), None)
        assert match is not None, ("표에 없는 자리이거나 코드가 다르다", path, text[:30], cls, code)
        remaining.remove(match)
    assert remaining == [], ("코드에 없는 표의 행", remaining)


# -- 분류와 코드가 원장과 응답에 실리는지 ---------------------------------------------------------------

class _Raising:
    def __init__(self, exc):
        self.exc = exc

    async def complete(self, prompt, schema):
        raise self.exc


def _failed_view(store, exc):
    _project(store)
    with TestClient(create_app(store, provider=_Raising(exc)), headers=HEADERS) as client:
        return _wait(client, _register(client).json()["id"])


# 회귀 RED(사실 7): 예기치 않은 예외가 input, 500으로 남았다(리뷰 탐침 {input, 500, None})
def test_unexpected_exception_is_internal_not_input(store):
    error = _failed_view(store, RuntimeError("예기치 않음"))["error"]
    assert (error["error_class"], error["status"], error["code"]) == ("internal", 500, None)


# 회귀 RED(사실 7): 제공자 예외는 원인과 무관하게 {connection, 503, 코드 없음}이었다
def test_provider_failures_carry_the_raise_site_code(store):
    from slidecaptain.pipeline.provider import ProviderNotAvailable

    error = _failed_view(store, ProviderNotAvailable("시간 초과", code="provider_timeout"))["error"]
    assert (error["error_class"], error["status"], error["code"]) == ("connection", 503, "provider_timeout")


def test_storage_errors_are_storage(store):
    from slidecaptain.storage.file_store import ProjectNotFound

    error = _failed_view(store, ProjectNotFound("프로젝트가 없습니다"))["error"]
    assert error["error_class"] == "storage"


# 회귀 RED: 등록 단계의 연결 오류는 응답 본문에 코드가 없었다
def test_wrapped_generation_connection_errors_put_the_code_in_the_body(store, manager):
    """래퍼 라우트는 원장 행을 거쳐 JobFailed로 응답한다(provider_error_handler를 지나지 않는다)."""
    from slidecaptain.pipeline.auth_status import LoginStatus

    _project(store)
    manager.connections["claude"].login = LoginStatus(logged_in=False)  # 처음 보는 로그아웃
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        response = client.post("/api/projects/p1/generate/structure", json={},
                               headers={"X-AI-Selection": manager.selection_id})
    assert response.status_code == 503 and response.json()["code"] == "login_required"


def test_registration_selection_change_puts_the_code_in_the_body(store, manager):
    _project(store)
    with TestClient(create_app(store, ai_connections=manager), headers=HEADERS) as client:
        response = client.post("/api/projects/p1/generate/structure", json={},
                               headers={"X-AI-Selection": "other-selection"})
    assert response.status_code == 409 and response.json()["code"] == "selection_changed"


def test_provider_error_handler_puts_the_code_in_the_body(store, monkeypatch, tmp_path):
    """연결 오류 처리기를 직접 지나는 경로: AI 설정의 로그인 시작에서 CLI 없음 (D3a-4 리뷰 R23)."""
    from slidecaptain.pipeline.connections import AIConnections, ClaudeConnection
    from tests.test_jobs_api import FakeConnection

    monkeypatch.setenv("SLIDECAPTAIN_CLAUDE_CLI", str(tmp_path / "no-such-cli"))
    connections = AIConnections(tmp_path / "settings.json", connections={
        "claude": ClaudeConnection(), "chatgpt": FakeConnection("gpt-test")})
    _project(store)
    try:
        with TestClient(create_app(store, ai_connections=connections), headers=HEADERS) as client:
            response = client.post("/api/ai/providers/claude/login")
    finally:
        connections.close()
    assert response.status_code == 503 and response.json()["code"] == "provider_missing"


def test_generation_with_a_missing_cli_records_provider_missing_not_login_required(store, monkeypatch, tmp_path):
    """상태 확인이 CLI를 찾지 못하면 로그인 필요가 아니라 설치 없음이다 (D3a-4 리뷰 R2).

    회귀 RED: 고치기 전 코드는 확인하지 못한 모든 원인을 login_required로 기록했다.
    """
    from slidecaptain.pipeline.connections import AIConnections, ClaudeConnection
    from tests.test_jobs_api import FakeConnection

    monkeypatch.setenv("SLIDECAPTAIN_CLAUDE_CLI", str(tmp_path / "no-such-cli"))
    connections = AIConnections(tmp_path / "settings.json", connections={
        "claude": ClaudeConnection(), "chatgpt": FakeConnection("gpt-test")})
    _project(store)
    try:
        with TestClient(create_app(store, ai_connections=connections), headers=HEADERS) as client:
            response = client.post("/api/projects/p1/generate/structure", json={},
                                   headers={"X-AI-Selection": connections.selection_id})
    finally:
        connections.close()
    assert response.status_code == 503 and response.json()["code"] == "provider_missing"
