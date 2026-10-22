"""Local, single-owner AI connections. Credentials stay with the official clients.

Settings contain only a provider, model and optional effort. A lease pins these for all
retries, and a revision binds the browser's disclosure to that exact selection.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth_status import LoginStatus, check_login, resolve_cli_path
from .provider import ProviderNotAvailable
from .subscription import SubscriptionProvider

ProviderId = Literal["claude", "chatgpt"]

# 저장할 수 있는 모델 ID. 제공자 목록도 같은 규칙으로 거른다(맞지 않는 ID를 보이면 고른 뒤 저장이 422로 막힌다, D4b 리뷰 CMR-12)
MODEL_ID_MAX = 150
MODEL_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._:/\[\]-]*$"
_MODEL_ID = re.compile(MODEL_ID_PATTERN)


class AISelection(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderId = "claude"
    model: str = Field(default="sonnet", min_length=1, max_length=MODEL_ID_MAX, pattern=MODEL_ID_PATTERN)
    effort: str | None = Field(default=None, min_length=1)

    @field_validator("effort")
    @classmethod
    def nonblank_effort(cls, value):
        if value is not None and not value.strip():
            raise ValueError("추론 강도는 비어 있을 수 없습니다.")
        return value


class ModelOption(BaseModel):
    id: str
    label: str
    # 제공자 목록이 알려 준 정확한 모델 버전(예: sonnet -> claude-sonnet-5). 모르면 None이다. 목록은 이용 권한의 증거가 아니다
    resolved_model: str | None = None
    supported_efforts: list[str] = Field(default_factory=list)
    default_effort: str | None = None
    capability_source: Literal["unverified", "codex_model_list", "claude_sdk_init"] = "unverified"
    capabilities_checked_at: datetime | None = None


def _supports_effort(selection: AISelection, model: ModelOption) -> bool:
    # 제공자와 관계없이 선택한 모델의 지원 목록에 있는 강도만 받는다. 지원 정보가 없는 모델은 제공자 기본값만 쓴다 (D4b)
    return selection.effort is None or selection.effort in model.supported_efforts


# Claude 모델 목록 (D4b, docs/plans/2026-10-20-revision-d4b-claude-models.md). 공식 SDK의 CLI 초기화 응답에서 읽고 프롬프트를
# 보내지 않는다. 조회마다 CLI를 띄우므로 캐시하고, 연결 신원이 바뀌면 버린다
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")  # ClaudeAgentOptions.effort가 받는 값
CLAUDE_CATALOG_TTL_S = 600.0
CLAUDE_CATALOG_RETRY_S = 60.0
CLAUDE_CATALOG_TIMEOUT_S = 30.0


def _remove_folder(path: str, *, attempts: int = 50, wait_s: float = 0.2) -> None:
    """조회용 빈 작업 폴더를 지운다. Windows에서는 CLI가 완전히 끝나기 전이면 사용 중 오류(WinError 32)가 나므로, 그때는
    데몬 스레드가 잠시 뒤 다시 지운다(최대 약 10초). 조회마다 빈 폴더가 쌓이지 않게 한다 (D4b 리뷰 CMR-09)."""
    def remove() -> bool:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return True

    def retry():
        for _ in range(attempts):
            time.sleep(wait_s)
            if remove():
                return

    if not remove():
        threading.Thread(target=retry, name="slidecaptain-claude-cleanup", daemon=True).start()


def _read_claude_catalog() -> dict:
    """사용자의 기존 Claude Code 프로필로 CLI 초기화 응답을 읽는다. 도구, 사용자 설정 파일, 사용자 단위 MCP 서버를 쓰지 않고
    프롬프트를 보내지 않는다. 응답의 계정 정보는 호출자가 쓰지 않는다.

    호출자의 이벤트 루프와 섞이지 않게 데몬 스레드의 이벤트 루프에서 돈다. 제한 시간은 연결(SDK 초기화)까지 덮는다. 실제
    대기는 연결 단계에서 일어나고, SDK 자체의 초기화 제한은 60초 이상이다. 시간을 넘기면 CLI 정리를 기다리지 않고
    TimeoutError를 낸다. 정리는 그 스레드가 마저 한다 (D4b 리뷰 CMR-02)."""
    cli = resolve_cli_path()
    if cli is None:
        raise ProviderNotAvailable("Claude Code를 찾지 못해 모델 목록을 확인하지 못했습니다. 설치 후 다시 확인해 주세요.",
                                   code="provider_missing")

    async def read():
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        directory = tempfile.mkdtemp(prefix="slidecaptain-claude-")
        try:
            options = ClaudeAgentOptions(cli_path=str(cli), cwd=directory, tools=[], setting_sources=[],
                                         strict_mcp_config=True, env={"DISABLE_TELEMETRY": "1"}, max_turns=1)
            async with asyncio.timeout(CLAUDE_CATALOG_TIMEOUT_S):
                async with ClaudeSDKClient(options=options) as client:
                    return await client.get_server_info()
        finally:
            _remove_folder(directory)

    outcome = {}

    def run():
        try:
            outcome["info"] = asyncio.run(read())
        except BaseException as e:
            outcome["error"] = e

    worker = threading.Thread(target=run, name="slidecaptain-claude-catalog", daemon=True)
    worker.start()
    worker.join(CLAUDE_CATALOG_TIMEOUT_S + 5)
    if worker.is_alive():
        raise TimeoutError("Claude 모델 목록 조회가 제한 시간 안에 끝나지 않았습니다.")
    if "error" in outcome:
        raise outcome["error"]
    info = outcome.get("info")
    return info if isinstance(info, dict) else {}


def _short_text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= 200 else None


def _model_id(value) -> str | None:
    return value if isinstance(value, str) and len(value) <= MODEL_ID_MAX and _MODEL_ID.fullmatch(value) else None


def _claude_catalog_models(info: dict) -> list[ModelOption]:
    checked_at = datetime.now(timezone.utc)
    models, seen = [], set()
    items = info.get("models") if isinstance(info, dict) else None
    for item in items[:100] if isinstance(items, list) else []:
        model_id = _model_id(item.get("value")) if isinstance(item, dict) else None
        if model_id is None or model_id in seen:
            continue
        advertised = item.get("supportedEffortLevels")
        efforts = [effort for effort in CLAUDE_EFFORTS if isinstance(advertised, list) and effort in advertised]
        models.append(ModelOption(
            id=model_id, label=_short_text(item.get("displayName")) or model_id,
            resolved_model=_short_text(item.get("resolvedModel")), supported_efforts=efforts,
            capability_source="claude_sdk_init", capabilities_checked_at=checked_at,
        ))
        seen.add(model_id)
    return models


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
    """연결 선택이나 신원이 바뀌었거나 로그인 중이다. code는 던지는 자리마다 붙인다 (D3a-4, 계획 4.3)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        if code not in CONNECTION_CONFLICT_CODES:  # 최적화 실행(-O)에서도 검사한다 (D3a-4 리뷰 R19)
            raise ValueError(f"모르는 연결 충돌 코드: {code}")
        self.code = code


CONNECTION_CONFLICT_CODES = frozenset({"selection_changed", "login_pending", "identity_changed", "settings_busy"})


class ClaudeConnection:
    """Owner's existing Claude Code profile; never exports its OAuth credentials."""

    def __init__(self, *, catalog_reader=None):
        self._process = None
        self._started = 0.0
        self._attempt = LoginAttempt(state="idle")
        self._read_catalog = catalog_reader or _read_claude_catalog
        self._catalog_lock = threading.Lock()
        self._catalog: list[ModelOption] | None = None
        self._catalog_at = 0.0
        self._failure: tuple[ProviderNotAvailable, float] | None = None

    def status(self):
        status = check_login()
        if status.logged_in and status.auth_method != "claude.ai":
            return LoginStatus(error="Claude 구독 로그인이 필요합니다. Claude Code의 현재 API 인증 설정을 확인해 주세요.",
                               error_code="login_required")
        return status

    def models(self):
        """설치된 Claude Code가 이 계정에 알려 준 모델 목록(캐시 10분). 조회가 실패하면 마지막 목록을 쓰고, 목록이 없으면
        원인 코드와 함께 알린다. 실패한 뒤 1분 동안은 다시 띄우지 않는다(화면 조회가 매번 CLI를 기다리지 않게)."""
        with self._catalog_lock:
            now = time.monotonic()
            if self._catalog is not None and now - self._catalog_at < CLAUDE_CATALOG_TTL_S:
                return list(self._catalog)
            if self._catalog is None and self._failure is not None and now - self._failure[1] < CLAUDE_CATALOG_RETRY_S:
                raise self._failure[0]
            try:
                models = _claude_catalog_models(self._read_catalog())
                if not models:
                    raise ProviderNotAvailable("Claude Code가 모델 목록을 알려 주지 않았습니다. Claude Code를 업데이트한 뒤 "
                                               "다시 확인해 주세요.", code="provider_call_failed")
            except ProviderNotAvailable as e:
                error = e
            except TimeoutError:
                error = ProviderNotAvailable("Claude 모델 목록 확인이 시간 안에 끝나지 않았습니다. 잠시 뒤 다시 확인해 주세요.",
                                             code="provider_timeout")
            except Exception:
                error = ProviderNotAvailable("Claude 모델 목록을 읽지 못했습니다. Claude Code 설치와 로그인을 확인해 주세요.",
                                             code="provider_call_failed")
            else:
                self._catalog, self._catalog_at, self._failure = models, now, None
                return list(models)
            self._failure = (error, now)
            if self._catalog is not None:
                # 마지막 목록으로 계속 쓰되, 1분 뒤에 다시 조회한다
                self._catalog_at = now - CLAUDE_CATALOG_TTL_S + CLAUDE_CATALOG_RETRY_S
                return list(self._catalog)
            raise error

    def warm_models(self):
        """연결 관리자의 잠금 밖에서 목록을 미리 읽어 둔다. 실패도 보존되어, 다음 models()가 같은 원인을 바로 알린다."""
        try:
            self.models()
        except ProviderNotAvailable:
            pass

    def invalidate_models(self):
        with self._catalog_lock:
            self._catalog, self._catalog_at, self._failure = None, 0.0, None

    def provider(self, model, *, effort=None):
        return SubscriptionProvider(model=model, effort=effort)

    def start_login(self):
        if self.login_status().state == "pending":
            return self._attempt
        cli = resolve_cli_path()
        if cli is None:
            raise ProviderNotAvailable("Claude Code를 찾지 못했습니다. 설치 후 연결 상태를 다시 확인해 주세요.", code="provider_missing")
        # The unmodified client opens and completes its own browser flow. No
        # login URL, codes, credentials or terminal output are relayed by us.
        try:
            self._process = subprocess.Popen(
                [str(cli), "auth", "login"], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise ProviderNotAvailable("Claude Code 로그인 창을 열지 못했습니다.", code="provider_missing") from None
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
        if previous is not None and previous != identity:
            # 모델 목록은 계정마다 다르다(2026-10-20 실측). 신원이 바뀌면 캐시한 목록을 버린다 (D4b)
            invalidate = getattr(self.connections[provider], "invalidate_models", None)
            if invalidate is not None:
                invalidate()
            if provider == self.selection.provider:
                self.selection_id = uuid.uuid4().hex

    def _idle(self):
        if self._active:
            raise ConnectionConflict("AI 생성이 진행 중입니다. 완료 후 연결 설정을 변경해 주세요.", code="settings_busy")

    def _warm_models(self, providers=None):
        # Claude 목록 조회는 CLI를 띄워 몇 초 걸린다. 이 잠금 밖에서 캐시를 채우고 잠금 안에서는 캐시만 읽는다. 그동안 상태
        # 조회, 로그인 확인, 생성 임대의 획득과 반납이 기다리지 않는다. 반납은 작업 루프 스레드가 동기로 부른다 (D4b 리뷰 CMR-03).
        # Codex는 연결 하나를 공유하므로 지금처럼 잠금 안에서 읽는다
        for key in providers or list(self.connections):
            warm = getattr(self.connections[key], "warm_models", None)
            if warm is not None:
                warm()

    def settings(self):
        # 신원을 먼저 본다. 로그인이나 계정이 바뀌었으면 목록 캐시를 버린 뒤 새 신원으로 읽는다 (D4b 리뷰 CMR-04)
        with self._lock:
            logins = {}
            for key, connection in self.connections.items():
                logins[key] = connection.status()
                self._observe_identity(key, logins[key])
        self._warm_models()
        with self._lock:
            providers = []
            for key, connection in self.connections.items():
                error = None
                try:
                    models = connection.models()
                except ProviderNotAvailable as e:
                    models, error = [], str(e)
                providers.append(ProviderSettings(
                    id=key, label="Claude" if key == "claude" else "ChatGPT",
                    login=logins[key], models=models, models_error=error,
                    login_attempt=self.login_status(key),
                ))
            return AISettings(selection=self.selection, selection_id=self.selection_id,
                              providers=providers, busy=bool(self._active))

    def current_selection(self, selection_id):
        """선택 식별자가 지금과 같을 때만 지금 선택을 돌려준다. 둘을 잠금 안에서 함께 읽어, 확인과 읽기 사이에 선택이 바뀌면
        새 선택과 옛 식별자가 한 원장 행에 섞이지 않게 한다 (D4 실제 생성 확인 코드 리뷰 LCC-08)."""
        with self._lock:
            if selection_id != self.selection_id:
                raise ConnectionConflict("AI 서비스, 모델 또는 추론 강도가 변경되었습니다. 전송 대상을 다시 확인해 주세요.",
                                         code="selection_changed")
            return self.selection

    def selected_status(self):
        with self._lock:
            login = self.connections[self.selection.provider].status()
            self._observe_identity(self.selection.provider, login)
            return self.selection, self.selection_id, login

    def select(self, selection: AISelection):
        self._warm_models([selection.provider])
        with self._lock:
            self._idle()
            models = self.connections[selection.provider].models()
            model = next((m for m in models if m.id == selection.model), None)
            if model is None:
                raise ValueError("이 서비스에서 선택할 수 없는 모델입니다. 모델 목록을 다시 확인해 주세요.")
            if not _supports_effort(selection, model):
                raise ValueError("선택한 모델에서 지원을 확인할 수 없는 추론 강도입니다. AI 연결 화면에서 다시 선택해 주세요.")
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.settings_path.parent, prefix=".ai-settings-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(selection.model_dump_json(exclude_none=True) + "\n")
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
        self._warm_models([self.selection.provider])
        with self._lock:
            if selection_id != self.selection_id:
                raise ConnectionConflict("AI 서비스, 모델 또는 추론 강도가 변경되었습니다. 전송 대상을 다시 확인해 주세요.", code="selection_changed")
            self._idle()
            connection = self.connections[self.selection.provider]
            if connection.login_status().state == "pending":
                raise ConnectionConflict("로그인을 완료한 뒤 생성해 주세요.", code="login_pending")
            status = connection.status()
            self._observe_identity(self.selection.provider, status)
            if selection_id != self.selection_id:
                raise ConnectionConflict("AI 연결 상태가 변경되었습니다. 전송 대상을 다시 확인해 주세요.", code="identity_changed")
            # 로그인 안 됨과 확인하지 못함을 가른다. 확인하지 못함은 상태 확인이 가른 원인 코드를 싣는다 (D3a-4 리뷰 R2)
            if status.logged_in is False:
                raise ProviderNotAvailable(status.error or "AI 연결에 로그인되어 있지 않습니다.", code="login_required")
            if status.logged_in is not True and status.error_code == "provider_missing":
                raise ProviderNotAvailable(status.error or "AI 도구를 찾지 못했습니다.", code="provider_missing")
            if status.logged_in is not True and status.error_code == "provider_timeout":
                raise ProviderNotAvailable(status.error or "AI 연결 상태 확인이 시간 안에 끝나지 않았습니다.",
                                           code="provider_timeout")
            if status.logged_in is not True and status.error_code == "login_required":
                raise ProviderNotAvailable(status.error or "구독 로그인을 확인해 주세요.", code="login_required")
            if status.logged_in is not True:
                raise ProviderNotAvailable(status.error or "AI 연결 상태를 확인하지 못했습니다.", code="provider_call_failed")
            model = next((m for m in connection.models() if m.id == self.selection.model), None)
            if model is None:
                raise ProviderNotAvailable("선택한 모델을 사용할 수 없습니다. AI 연결 화면에서 모델을 다시 선택해 주세요.", code="model_unavailable")
            if not _supports_effort(self.selection, model):
                raise ProviderNotAvailable("선택한 추론 강도의 지원 정보가 바뀌었습니다. AI 연결 화면에서 다시 선택해 주세요.", code="model_unavailable")
            # Keep the provider default path unchanged for clients without effort support.
            provider = (connection.provider(self.selection.model, effort=self.selection.effort)
                        if self.selection.effort is not None else connection.provider(self.selection.model))
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
