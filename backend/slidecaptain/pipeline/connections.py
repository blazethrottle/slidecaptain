"""Local, single-owner AI connections. Credentials stay with the official clients.

Settings contain only a provider and model. A generation lease pins both for all
retries, and a revision binds the browser's disclosure to that exact selection.
"""

import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .auth_status import LoginStatus, check_login, resolve_cli_path
from .provider import ProviderNotAvailable
from .subscription import SubscriptionProvider

ProviderId = Literal["claude", "chatgpt"]


class AISelection(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderId = "claude"
    model: str = Field(default="sonnet", min_length=1, max_length=150, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/\[\]-]*$")


class ModelOption(BaseModel):
    id: str
    label: str


class LoginAttempt(BaseModel):
    state: Literal["idle", "pending", "succeeded", "failed", "cancelled"]
    auth_url: str | None = None
    message: str = ""


class ProviderSettings(BaseModel):
    id: ProviderId
    label: str
    login: LoginStatus
    models: list[ModelOption]
    models_error: str | None = None
    login_attempt: LoginAttempt


class AISettings(BaseModel):
    selection: AISelection
    selection_id: str
    providers: list[ProviderSettings]
    busy: bool


class ConnectionConflict(ValueError):
    pass


class ClaudeConnection:
    """Owner's existing Claude Code profile; never exports its OAuth credentials."""

    def __init__(self):
        self._process = None
        self._started = 0.0
        self._attempt = LoginAttempt(state="idle")

    def status(self):
        status = check_login()
        if status.logged_in and status.auth_method != "claude.ai":
            return LoginStatus(error="Claude 구독 로그인이 필요합니다. Claude Code의 현재 API 인증 설정을 확인해 주세요.")
        return status

    def models(self):
        return [ModelOption(id=name, label=label) for name, label in
                [("sonnet", "Sonnet"), ("opus", "Opus"), ("haiku", "Haiku")]]

    def provider(self, model):
        return SubscriptionProvider(model=model)

    def start_login(self):
        if self.login_status().state == "pending":
            return self._attempt
        cli = resolve_cli_path()
        if cli is None:
            raise ProviderNotAvailable("Claude Code를 찾지 못했습니다. 설치 후 연결 상태를 다시 확인해 주세요.")
        # The unmodified client opens and completes its own browser flow. No
        # login URL, codes, credentials or terminal output are relayed by us.
        try:
            self._process = subprocess.Popen(
                [str(cli), "auth", "login"], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise ProviderNotAvailable("Claude Code 로그인 창을 열지 못했습니다.") from None
        self._started = time.monotonic()
        self._attempt = LoginAttempt(state="pending", message=(
            "Claude Code가 연 공식 브라우저에서 로그인해 주세요. 창이 열리지 않으면 "
            "터미널에서 claude auth login을 실행한 뒤 연결 상태를 다시 확인해 주세요."
        ))
        return self._attempt

    def login_status(self):
        if self._process is not None:
            code = self._process.poll()
            if code is not None:
                self._process = None
                ok = code == 0 and self.status().logged_in is True
                self._attempt = LoginAttempt(
                    state="succeeded" if ok else "failed",
                    message="로그인이 완료되었습니다." if ok else "로그인이 완료되지 않았습니다. 다시 시도해 주세요.",
                )
            elif time.monotonic() - self._started > 180:
                self.cancel_login()
                self._attempt = LoginAttempt(state="failed", message="로그인 대기 시간이 지났습니다. 다시 시도해 주세요.")
        return self._attempt

    def cancel_login(self):
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
            self._process = None
        self._attempt = LoginAttempt(state="cancelled", message="로그인 대기를 취소했습니다.")
        return self._attempt

    def close(self):
        if self._process is not None:
            self.cancel_login()


class AIConnections:
    def __init__(self, settings_path: Path, *, connections=None, initial: AISelection | None = None):
        self.settings_path = settings_path
        if initial is not None:
            self.selection = initial
        elif settings_path.exists():
            try:
                self.selection = AISelection.model_validate_json(settings_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raise ValueError("AI 연결 설정 파일을 읽지 못했습니다. ai-settings.json을 확인해 주세요.") from None
        else:
            self.selection = AISelection()
        if connections is None:
            from .codex import CodexConnection
            connections = {
                "claude": ClaudeConnection(),
                "chatgpt": CodexConnection(settings_path.parent / ".slidecaptain-codex"),
            }
        self.connections = connections
        self.selection_id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._active = 0
        self._identities = {}
        self._login_timers = {}
        self._expired = set()

    def _observe_identity(self, provider, status):
        identity = (status.logged_in, status.auth_method, status.account)
        previous = self._identities.get(provider)
        self._identities[provider] = identity
        if previous is not None and previous != identity and provider == self.selection.provider:
            self.selection_id = uuid.uuid4().hex

    def _idle(self):
        if self._active:
            raise ConnectionConflict("AI 생성이 진행 중입니다. 완료 후 연결 설정을 변경해 주세요.")

    def settings(self):
        with self._lock:
            providers = []
            for key, connection in self.connections.items():
                error = None
                try:
                    models = connection.models()
                except ProviderNotAvailable as e:
                    models, error = [], str(e)
                login = connection.status()
                self._observe_identity(key, login)
                providers.append(ProviderSettings(
                    id=key, label="Claude" if key == "claude" else "ChatGPT",
                    login=login, models=models, models_error=error,
                    login_attempt=self.login_status(key),
                ))
            return AISettings(selection=self.selection, selection_id=self.selection_id,
                              providers=providers, busy=bool(self._active))

    def selected_status(self):
        with self._lock:
            login = self.connections[self.selection.provider].status()
            self._observe_identity(self.selection.provider, login)
            return self.selection, self.selection_id, login

    def select(self, selection: AISelection):
        with self._lock:
            self._idle()
            models = self.connections[selection.provider].models()
            if selection.model not in {m.id for m in models}:
                raise ValueError("이 서비스에서 선택할 수 없는 모델입니다. 모델 목록을 다시 확인해 주세요.")
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.settings_path.parent, prefix=".ai-settings-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(selection.model_dump_json() + "\n")
                os.replace(name, self.settings_path)
            finally:
                Path(name).unlink(missing_ok=True)
            if self.selection != selection:
                self.selection = selection
                self.selection_id = uuid.uuid4().hex
            return selection

    def start_login(self, provider: ProviderId):
        with self._lock:
            self._idle()
            self.login_status(provider)  # Remove a completed attempt's timer before starting another.
            self.selection_id = uuid.uuid4().hex
            result = self.connections[provider].start_login()
            self._expired.discard(provider)
            if result.state == "pending" and provider not in self._login_timers:
                def expire():
                    with self._lock:
                        if self._login_timers.get(provider) is not timer:
                            return
                        self._login_timers.pop(provider, None)
                        if self.connections[provider].login_status().state == "pending":
                            self.connections[provider].cancel_login()
                            self._expired.add(provider)
                timer = threading.Timer(180, expire)
                timer.daemon = True
                self._login_timers[provider] = timer
                timer.start()
            return result

    def login_status(self, provider: ProviderId):
        with self._lock:
            if provider in self._expired:
                return LoginAttempt(state="failed", message="로그인 대기 시간이 지났습니다. 다시 시도해 주세요.")
            result = self.connections[provider].login_status()
            if result.state != "pending":
                timer = self._login_timers.pop(provider, None)
                if timer is not None:
                    timer.cancel()
            return result

    def cancel_login(self, provider: ProviderId):
        with self._lock:
            self._idle()
            timer = self._login_timers.pop(provider, None)
            if timer is not None:
                timer.cancel()
            self._expired.discard(provider)
            return self.connections[provider].cancel_login()

    @contextmanager
    def generation(self, selection_id: str | None):
        with self._lock:
            if selection_id != self.selection_id:
                raise ConnectionConflict("AI 서비스 또는 모델이 변경되었습니다. 전송 대상을 다시 확인해 주세요.")
            self._idle()
            connection = self.connections[self.selection.provider]
            if connection.login_status().state == "pending":
                raise ConnectionConflict("로그인을 완료한 뒤 생성해 주세요.")
            status = connection.status()
            self._observe_identity(self.selection.provider, status)
            if selection_id != self.selection_id:
                raise ConnectionConflict("AI 연결 상태가 변경되었습니다. 전송 대상을 다시 확인해 주세요.")
            if status.logged_in is not True:
                raise ProviderNotAvailable(status.error or "AI 연결 화면에서 먼저 로그인해 주세요.")
            if self.selection.model not in {m.id for m in connection.models()}:
                raise ProviderNotAvailable("선택한 모델을 사용할 수 없습니다. AI 연결 화면에서 모델을 다시 선택해 주세요.")
            provider = connection.provider(self.selection.model)
            self._active += 1
        try:
            yield provider
        finally:
            with self._lock:
                self._active -= 1

    def close(self):
        with self._lock:
            for timer in self._login_timers.values():
                timer.cancel()
            self._login_timers.clear()
            for connection in self.connections.values():
                connection.close()
