"""ChatGPT subscription adapter over the official Codex app-server protocol.

No browser cookies, OAuth tokens or auth.json contents are read by SlideCaptain.
The official process owns authentication in a separate CODEX_HOME. Each content
call uses a new ephemeral thread and the common generation validation pipeline.
"""

import asyncio
import copy
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .auth_status import LoginStatus, mask_email
from .connections import LoginAttempt, ModelOption
from .provider import CallUsage, ProviderCallFailed, ProviderNotAvailable, ProviderResponse

_AUTH_HOSTS = {"auth.openai.com", "auth0.openai.com", "chatgpt.com"}
_EVENTS = {"account/login/completed", "account/updated", "turn/completed",
           "item/completed", "thread/tokenUsage/updated"}


def resolve_codex_path():
    override = os.environ.get("SLIDECAPTAIN_CODEX_CLI")
    candidates = [override] if override else [shutil.which("codex"), shutil.which("codex.exe")]
    for path in candidates:
        if path and Path(path).is_file() and Path(path).suffix.lower() not in {".bat", ".cmd"}:
            return Path(path)
    return None


def validated_auth_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        raise ProviderNotAvailable("공식 로그인 주소를 확인하지 못했습니다.")
    try:
        url = urlsplit(value)
        valid = (url.scheme == "https" and url.hostname in _AUTH_HOSTS
                 and not url.username and not url.password and url.port in {None, 443})
    except ValueError:
        valid = False
    if not valid:
        raise ProviderNotAvailable("공식 로그인 주소를 확인하지 못했습니다.")
    return value


def codex_command(cli):
    # Keep user/global project settings, hooks, MCP, web, shell and browser tools
    # out of document generation. OS sandbox and denied server requests remain
    # additional boundaries. No --dangerously-bypass... or shell command strings.
    config = {
        "model_provider": '"openai"', "forced_login_method": '"chatgpt"',
        "cli_auth_credentials_store": '"file"', "web_search": '"disabled"',
        "sandbox_mode": '"read-only"', "approval_policy": '"on-request"',
        "analytics.enabled": "false", "feedback.enabled": "false",
        "project_doc_max_bytes": "0",
    }
    for feature in ["shell_tool", "unified_exec", "code_mode", "code_mode_host", "apps",
                    "browser_use", "computer_use", "image_generation", "view_image",
                    "multi_agent", "memories", "hooks", "plugins", "remote_plugin", "shell_snapshot"]:
        config[f"features.{feature}"] = "false"
    args = [str(cli), "app-server"]
    for key, value in config.items():
        args.extend(["-c", f"{key}={value}"])
    return args


class CodexRPC:
    """Bounded JSONL transport, shared by read-only status/auth and generation."""

    def __init__(self, home: Path, *, timeout=20.0):
        cli = resolve_codex_path()
        if cli is None:
            raise ProviderNotAvailable("Codex CLI를 찾지 못했습니다. Codex를 설치한 뒤 연결 상태를 다시 확인해 주세요.")
        self.timeout = timeout
        self._guard = threading.RLock()
        self._pending = {}
        self._next_id = 0
        self.events = queue.Queue(maxsize=512)
        self._closed = False
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._cwd = tempfile.TemporaryDirectory(prefix="slidecaptain-codex-")
        self.cwd = self._cwd.name
        keep = {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
                "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
                "SSL_CERT_FILE", "SSL_CERT_DIR"}
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        env["CODEX_HOME"] = str(home.resolve())
        try:
            self._process = subprocess.Popen(
                codex_command(cli), cwd=self.cwd, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._cwd.cleanup()
            raise ProviderNotAvailable("Codex를 실행하지 못했습니다. 설치 상태를 확인해 주세요.") from None
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        try:
            self.request("initialize", {"clientInfo": {"name": "slidecaptain", "version": "0.1.0"}})
            self._send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def _send(self, message):
        with self._guard:
            if self._closed:
                raise ProviderNotAvailable("Codex 연결이 종료되었습니다. 다시 연결해 주세요.")
            try:
                self._process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
                self._process.stdin.flush()
            except (OSError, ValueError):
                raise ProviderNotAvailable("Codex 연결이 끊겼습니다. 다시 연결해 주세요.") from None

    def _read(self):
        try:
            while True:
                line = self._process.stdout.readline(2_000_001)
                if not line or len(line) > 2_000_000:
                    break
                message = json.loads(line)
                if not isinstance(message, dict):
                    break
                if "id" in message and "method" in message:
                    # Never grant tools, filesystem writes, shell, credential
                    # refresh by a host, or arbitrary server requests.
                    self._send({"id": message["id"], "error": {"code": -32601, "message": "Not supported by SlideCaptain"}})
                elif "id" in message:
                    with self._guard:
                        target = self._pending.get(message["id"])
                    if target is not None:
                        target.put_nowait(message)
                elif message.get("method") in _EVENTS:
                    self.events.put_nowait(message)
        except (ValueError, TypeError, OSError, queue.Full, ProviderNotAvailable):
            pass
        finally:
            with self._guard:
                self._closed = True
                for target in self._pending.values():
                    if target.empty():
                        target.put_nowait({"error": {}})

    def request(self, method, params=None, *, timeout=None):
        with self._guard:
            self._next_id += 1
            request_id = self._next_id
            target = queue.Queue(maxsize=1)
            self._pending[request_id] = target
        try:
            self._send({"id": request_id, "method": method, "params": params or {}})
            try:
                result = target.get(timeout=self.timeout if timeout is None else timeout)
            except queue.Empty:
                raise ProviderNotAvailable("Codex 응답 시간이 초과되었습니다. 연결 상태를 다시 확인해 주세요.") from None
            if "error" in result or not isinstance(result.get("result"), dict):
                raise ProviderNotAvailable("Codex 요청을 완료하지 못했습니다. 로그인과 Codex 버전을 확인해 주세요.")
            return result["result"]
        finally:
            with self._guard:
                self._pending.pop(request_id, None)

    def close(self):
        with self._guard:
            self._closed = True
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
        self._reader.join(timeout=3)
        self._process.stdin.close()
        self._process.stdout.close()
        self._cwd.cleanup()


class CodexConnection:
    def __init__(self, home: Path, *, rpc_factory=CodexRPC):
        self.home = home
        self._factory = rpc_factory
        self._rpc = None
        self._attempt = LoginAttempt(state="idle")
        self._login_id = None
        self._started = 0.0

    def _client(self):
        if self._rpc is not None and getattr(self._rpc, "_closed", False):
            self.close()
        if self._rpc is None:
            self._rpc = self._factory(self.home)
        return self._rpc

    def status(self):
        try:
            data = self._client().request("account/read", {"refreshToken": False})
            account = data.get("account")
            if account is None:
                return LoginStatus(logged_in=False)
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                return LoginStatus(error="ChatGPT 구독 로그인이 필요합니다. 연결 화면에서 로그인해 주세요.")
            email = account.get("email")
            return LoginStatus(logged_in=True, auth_method="ChatGPT",
                               account=mask_email(email) if isinstance(email, str) and email else None)
        except ProviderNotAvailable as e:
            self.close()
            return LoginStatus(error=str(e))

    def models(self):
        models, cursor, seen = [], None, set()
        for _ in range(10):
            result = self._client().request("model/list", {"limit": 100, "includeHidden": False, "cursor": cursor})
            for item in result.get("data", []):
                if not isinstance(item, dict) or item.get("hidden"):
                    continue
                model = item.get("model")
                if not isinstance(model, str) or "text" not in item.get("inputModalities", ["text"]):
                    continue
                if model not in seen:
                    models.append(ModelOption(id=model, label=item.get("displayName") or model))
                    seen.add(model)
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                return models
            if next_cursor == cursor:
                break
            cursor = next_cursor
        raise ProviderNotAvailable("모델 목록을 끝까지 읽지 못했습니다. 다시 확인해 주세요.")

    def start_login(self):
        if self.login_status().state == "pending":
            return self._attempt
        result = self._client().request("account/login/start", {"type": "chatgpt"})
        self._login_id = result.get("loginId")
        try:
            url = validated_auth_url(result.get("authUrl"))
            if not isinstance(self._login_id, str) or not self._login_id:
                raise ProviderNotAvailable("로그인 요청을 확인하지 못했습니다.")
        except ProviderNotAvailable:
            self.close()
            raise
        self._started = time.monotonic()
        self._attempt = LoginAttempt(state="pending", auth_url=url, message="공식 로그인 페이지에서 완료한 뒤 이 화면으로 돌아오세요.")
        return self._attempt

    def login_status(self):
        if self._rpc is not None:
            while True:
                try:
                    event = self._rpc.events.get_nowait()
                except queue.Empty:
                    break
                params = event.get("params", {})
                if (event.get("method") == "account/login/completed" and self._login_id
                        and params.get("loginId") == self._login_id and self._attempt.state == "pending"):
                    ok = params.get("success") is True and self.status().logged_in is True
                    self._attempt = LoginAttempt(
                        state="succeeded" if ok else "failed",
                        message="로그인이 완료되었습니다." if ok else "로그인이 완료되지 않았습니다. 다시 시도해 주세요.",
                    )
        if self._attempt.state == "pending" and time.monotonic() - self._started > 180:
            self.cancel_login()
            self._attempt = LoginAttempt(state="failed", message="로그인 대기 시간이 지났습니다. 다시 시도해 주세요.")
        return self._attempt

    def cancel_login(self):
        if self._login_id and self._rpc is not None and self._attempt.state == "pending":
            try:
                self._rpc.request("account/login/cancel", {"loginId": self._login_id})
            except ProviderNotAvailable:
                self.close()
        self._login_id = None
        self._attempt = LoginAttempt(state="cancelled", message="로그인 대기를 취소했습니다.")
        return self._attempt

    def provider(self, model):
        return CodexProvider(self.home, model=model, rpc_factory=self._factory)

    def close(self):
        if self._rpc is not None:
            self._rpc.close()
            self._rpc = None
        if self._attempt.state == "pending":
            self._attempt = LoginAttempt(state="failed", message="로그인 연결이 종료되었습니다. 다시 시도해 주세요.")


def _token(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def strict_output_schema(schema):
    """Adapt the wire schema only; the common Pydantic parser remains authoritative.

    OpenAI Structured Outputs requires closed objects and all properties required.
    Existing nullable fields stay nullable; default-valued lists/strings must be
    emitted explicitly. Never mutate Claude's schema or the domain data contract.
    """
    result = copy.deepcopy(schema)

    def visit(node):
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        if any(k in node for k in ("allOf", "oneOf", "not", "if", "then", "else", "patternProperties")):
            raise ProviderNotAvailable("이 응답 스키마는 ChatGPT 연결에서 아직 지원하지 않습니다.")
        if node.get("type") == "object":
            if isinstance(node.get("additionalProperties"), dict):
                raise ProviderNotAvailable("가변 키 응답 스키마는 ChatGPT 연결에서 아직 지원하지 않습니다.")
            node.setdefault("properties", {})
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        for key in ("properties", "$defs", "definitions"):
            for child in node.get(key, {}).values():
                visit(child)
        for child in node.get("anyOf", []):
            visit(child)
        if "items" in node:
            visit(node["items"])

    visit(result)
    return result


class CodexProvider:
    def __init__(self, home: Path, *, model: str, timeout_s=300, rpc_factory=CodexRPC):
        self.home, self.model, self.timeout_s, self._factory = home, model, timeout_s, rpc_factory

    async def complete(self, prompt, schema):
        stop = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(self._complete, prompt, schema, stop))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            stop.set()
            try:
                await asyncio.shield(task)
            except (ProviderCallFailed, ProviderNotAvailable):
                pass
            raise

    def _complete(self, prompt, schema, stop):
        wire_schema = strict_output_schema(schema)
        client = self._factory(self.home)
        started = time.monotonic()
        try:
            account = client.request("account/read", {"refreshToken": False}).get("account")
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                raise ProviderNotAvailable("ChatGPT 구독 로그인이 필요합니다.")
            thread = client.request("thread/start", {
                "model": self.model, "modelProvider": "openai", "cwd": client.cwd,
                "approvalPolicy": "on-request", "sandbox": "read-only", "ephemeral": True,
                "baseInstructions": "Return only the requested JSON. Use only the supplied text. Do not use tools or access files, the network, or other applications.",
            })
            thread_id = thread["thread"]["id"]
            actual_model = thread.get("model")
            turn = client.request("turn/start", {"threadId": thread_id,
                "input": [{"type": "text", "text": prompt}], "outputSchema": wire_schema,
                "model": self.model, "approvalPolicy": "on-request",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            })
            turn_id = turn["turn"]["id"]
            text, tokens = "", None
            while True:
                if stop.is_set():
                    raise ProviderCallFailed("ChatGPT 생성을 취소했습니다.")
                remaining = self.timeout_s - (time.monotonic() - started)
                if remaining <= 0:
                    raise ProviderCallFailed("ChatGPT 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
                try:
                    event = client.events.get(timeout=min(remaining, 1))
                except queue.Empty:
                    if getattr(client, "_closed", False):
                        raise ProviderCallFailed("ChatGPT 연결이 종료되었습니다. 다시 시도해 주세요.")
                    continue
                params = event.get("params", {})
                if params.get("threadId") != thread_id or params.get("turnId", turn_id) != turn_id:
                    continue
                method = event.get("method")
                if method == "item/completed":
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage":
                        text = item.get("text", "")
                        if not isinstance(text, str):
                            raise ValueError("Invalid agent text")
                elif method == "thread/tokenUsage/updated":
                    tokens = params.get("tokenUsage", {}).get("total")
                elif method == "turn/completed":
                    completed = params.get("turn", {})
                    if completed.get("id") != turn_id:
                        continue
                    if completed.get("status") != "completed":
                        raise ProviderCallFailed("ChatGPT 생성을 완료하지 못했습니다. 로그인, 사용 한도와 연결 상태를 확인해 주세요.")
                    break
            try:
                structured = json.loads(text)
            except (ValueError, TypeError):
                structured = None
            t = tokens if isinstance(tokens, dict) else {}
            usage = CallUsage(
                model=actual_model if isinstance(actual_model, str) else None,
                input_tokens=_token(t.get("inputTokens")), output_tokens=_token(t.get("outputTokens")),
                cache_read_tokens=_token(t.get("cachedInputTokens")), cache_creation_tokens=_token(t.get("cacheWriteInputTokens")),
                duration_ms=int((time.monotonic() - started) * 1000), duration_api_ms=None,
                num_turns=1, cost_usd=None, stop_reason=None, terminal_reason="completed", api_error_status=None,
                token_source="usage" if t else "none",
            )
            return ProviderResponse(structured=structured, raw_text=text, usage=usage)
        except (KeyError, TypeError, ValueError):
            raise ProviderCallFailed("Codex 응답 형식을 읽지 못했습니다. Codex 버전을 확인해 주세요.") from None
        finally:
            # Process termination cancels timed-out turns and closes ephemeral
            # threads. No raw prompt/result logs are persisted by this adapter.
            client.close()
