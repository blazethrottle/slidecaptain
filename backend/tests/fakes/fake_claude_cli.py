"""시험용 가짜 Claude Code CLI (개정판 D2b-2, 계획서 6절).

실제 AI를 부르지 않는다. 서비스 환경의 SLIDECAPTAIN_CLAUDE_CLI가 이 파일의 실행 래퍼를 가리키게
해서 쓴다(래퍼는 시험이 `make_fake_cli`로 만든다). 흉내 내는 것은 claude-agent-sdk 0.2.145가 쓰는
범위뿐이다: `-v` 버전 확인, `auth status`, stream-json 입력의 초기화 제어 요청과 사용자 메시지,
assistant 메시지와 structured_output이 든 result 메시지.

동작은 환경 변수로 정한다.
- FAKE_CLAUDE_DIR: 기록 폴더. calls.log(생성 호출마다 한 줄), pids.log(프로세스마다 한 줄)를 쓴다
- FAKE_CLAUDE_MODE: respond(기본), gate(관문 파일이 생길 때까지 기다린 뒤 응답), hang(stdin을 읽지 않고 잔다)
- FAKE_CLAUDE_GATE: gate 모드의 관문 파일 경로
- FAKE_CLAUDE_RESPONSES: 응답 JSON 목록 파일. 호출 순서대로 꺼내고, 다 쓰면 마지막 것을 되풀이한다
- FAKE_CLAUDE_LOGGED_IN: 0이면 로그아웃 상태로 답한다
"""

import json
import os
import sys
import time
from pathlib import Path

FAKE_VERSION = "2.1.999 (Claude Code)"
FAKE_MODEL = "claude-fake-model"


def _dir() -> Path:
    path = Path(os.environ["FAKE_CLAUDE_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wait_while_parent(parent: int, done, limit: float = 600.0) -> bool:
    """done()이 참이 될 때까지 기다린다. 부모(서비스)가 죽어 다른 프로세스에 입양되면 기다리지 않고 거짓을 돌려준다.

    SIGKILL 시험은 서비스만 끊으므로, 이 검사가 없으면 관문 모드의 가짜 CLI가 영구히 남는다 (D2b-6 리뷰 R1).
    """
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if done():
            return True
        if os.getppid() != parent:
            return False
        time.sleep(0.02)
    return False


def _append(name: str, line: str) -> None:
    with open(_dir() / name, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _next_response(call_index: int) -> dict:
    source = os.environ.get("FAKE_CLAUDE_RESPONSES")
    if not source:
        return {}
    items = json.loads(Path(source).read_text(encoding="utf-8"))
    return items[min(call_index, len(items) - 1)]


def main(argv: list[str]) -> int:
    if "-v" in argv or "--version" in argv:
        print(FAKE_VERSION)
        return 0
    if argv[:2] == ["auth", "status"]:
        logged_in = os.environ.get("FAKE_CLAUDE_LOGGED_IN", "1") != "0"
        print(json.dumps({"loggedIn": logged_in, "authMethod": "claude.ai" if logged_in else None,
                          "email": "fake@example.invalid" if logged_in else None}))
        return 0
    _append("pids.log", str(os.getpid()))
    mode = os.environ.get("FAKE_CLAUDE_MODE", "respond")
    parent = os.getppid()
    if mode == "hang":
        _wait_while_parent(parent, lambda: False, 3600)
        return 0
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("type") == "control_request":
            request = message.get("request", {})
            _write({"type": "control_response", "response": {
                "subtype": "success", "request_id": message["request_id"], "response": {}}})
            if request.get("subtype") not in ("initialize", "interrupt"):
                continue
        elif message.get("type") == "user":
            calls = _dir() / "calls.log"
            index = len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0
            _append("calls.log", f"{index} {os.getpid()}")
            if mode == "gate":
                gate = Path(os.environ["FAKE_CLAUDE_GATE"])
                if not _wait_while_parent(parent, gate.exists):
                    return 0
            structured = _next_response(index)
            text = json.dumps(structured, ensure_ascii=False)
            _write({"type": "assistant", "message": {"model": FAKE_MODEL, "content": [{"type": "text", "text": text}]},
                    "parent_tool_use_id": None, "session_id": "fake-session"})
            _write({"type": "result", "subtype": "success", "duration_ms": 1, "duration_api_ms": 1,
                    "is_error": False, "num_turns": 1, "session_id": "fake-session", "result": text,
                    "structured_output": structured, "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "modelUsage": {FAKE_MODEL: {"inputTokens": 1, "outputTokens": 1, "cacheReadInputTokens": 0,
                                                "cacheCreationInputTokens": 0, "costUSD": 0.0}}})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
