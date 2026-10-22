"""AI 프로바이더 인터페이스 (설계서 2.4, 단계 3 결정 2).

교체 지점을 원시 호출 하나로 좁힌다: 프로바이더는 프롬프트와 응답 스키마를
받아 구조화 응답을 돌려주기만 한다. 프롬프트 조립과 검증 게이트는 파이프라인
공통부(prompts, service)에 있다. 배포 단계의 앱 관리형(API 키), BYOK는
이 Protocol의 다른 구현으로 추가된다.
"""

from dataclasses import dataclass
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel


class CallUsage(BaseModel, frozen=True):
    """원시 호출 1건의 실제 사용량 (설계서 4.4, 단계 5A 묶음 C 태스크 C1).

    SDK 가 값을 못 주면 그 필드는 None 이다. 없는 값은 만들지 않는다(가정 3).
    """

    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    duration_ms: int | None
    duration_api_ms: int | None
    num_turns: int | None  # SDK 내부 턴 수. 서비스가 세는 호출 수(calls)와 다른 축이다
    cost_usd: float | None
    stop_reason: str | None
    terminal_reason: str | None
    api_error_status: int | None
    token_source: Literal["model_usage", "usage", "none"]


_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_OBSERVED_TEXT_MAX = 80


def observed_fields(data: Any, *, value_keys: set[str] | frozenset[str], value_hints: tuple[str, ...],
                    count_keys: set[str] | frozenset[str] = frozenset()) -> dict:
    """응답 관측 진단 (D4 실제 생성 확인 3.3): 칸 이름 목록과 허용한 칸의 값만 고른다.

    실제 적용 모델과 강도를 응답에서 읽을 수 있는지 보려는 것이다. 원시 응답에는 계정 정보가 들어 있으므로 통째로 남기지
    않는다. 칸 이름은 한 단계 아래 dict까지 모은다. 값은 이름이 value_keys에 있거나 value_hints를 포함하는 칸의 스칼라만
    담고, 그 칸이 dict면 한 단계 아래 스칼라까지 담는다. count_keys의 칸(MCP 서버, 도구 목록 등)은 개수만 "<이름>#count"로
    담고 안을 보지 않는다. 이름 규칙에 맞지 않는 칸(값이 이름 자리에 온 경우)은 "?"로 센다.
    """
    keys: list[str] = []
    values: dict[str, Any] = {}

    def allowed(name: str) -> bool:
        lowered = name.lower()
        return name in value_keys or any(hint in lowered for hint in value_hints)

    def scalar(value: Any) -> bool:
        return value is None or isinstance(value, (bool, int, float, str))

    def keep(path: str, value: Any) -> None:
        values[path] = value[:_OBSERVED_TEXT_MAX] if isinstance(value, str) else value

    def visit(node: dict, prefix: str, nested: bool) -> None:
        for name, value in node.items():
            if not isinstance(name, str) or not _FIELD_NAME.fullmatch(name):
                keys.append(prefix + "?")
                continue
            path = prefix + name
            keys.append(path)
            if not nested and name in count_keys and isinstance(value, (list, dict)):
                values[path + "#count"] = len(value)
            elif allowed(name) and scalar(value):
                keep(path, value)
            elif allowed(name) and isinstance(value, dict):
                for sub, sub_value in value.items():
                    if isinstance(sub, str) and _FIELD_NAME.fullmatch(sub) and scalar(sub_value):
                        keep(f"{path}.{sub}", sub_value)
            elif isinstance(value, dict) and not nested:
                visit(value, path + ".", True)

    if isinstance(data, dict):
        visit(data, "", False)
    return {"keys": sorted(set(keys)), "values": values}


class ProviderError(Exception):
    """사용자에게 쉬운 말로 보여줄 AI 호출 오류 (설계서 7.2).

    code는 던지는 자리마다 붙이는 원인 코드다(개정판 D3a-4, 계획 4.3). 예외 클래스로 원인을 정하지 않는다:
    ChatGPT 연결은 호출 중 시간 초과도 ProviderNotAvailable로, Claude 연결은 미로그인과 한도 초과를
    ProviderCallFailed 한 자리로 던지기 때문이다. 한 자리가 둘 이상의 원인을 함께 받으면 넓은 코드
    provider_call_failed를 쓴다. 코드 목록은 PROVIDER_ERROR_CODES다.
    """

    def __init__(self, message: str, *, usage: CallUsage | None = None, code: str = "provider_call_failed") -> None:
        super().__init__(message)
        self.usage = usage
        if code not in PROVIDER_ERROR_CODES:  # 최적화 실행(-O)에서도 검사한다 (D3a-4 리뷰 R19)
            raise ValueError(f"모르는 제공자 오류 코드: {code}")
        self.code = code


# 제공자 오류 코드 (D3a-4). 화면의 원인별 안내 표(계획 4.3)가 이 목록을 덮는다
PROVIDER_ERROR_CODES = frozenset({
    "provider_missing",        # 설치 없음, 실행 파일을 찾거나 실행하지 못함
    "login_required",          # 연결 상태 확인에서 로그인이 없다고 판정
    "provider_timeout",        # 응답 시간 초과
    "provider_disconnected",   # 연결 끊김, 결과 없이 끝남
    "provider_unsupported",    # 이 연결이 지원하지 않는 응답 스키마
    "provider_limit",          # 사용 한도 초과(HTTP 429로 온 경우만 가른다)
    "provider_cancelled",      # 제공자가 생성을 취소로 끝냄
    "model_unavailable",       # 선택한 모델을 쓸 수 없음
    "provider_call_failed",    # 그 밖의 호출 실패, 또는 한 자리가 둘 이상의 원인을 함께 받음
})


class ProviderNotAvailable(ProviderError):
    """호출 환경 자체가 없다 (Claude Code 미설치 등)."""


class ProviderCallFailed(ProviderError):
    """호출은 시도됐지만 실패했다 (미로그인, 한도 소진, 네트워크)."""


@dataclass
class ProviderResponse:
    structured: Any | None  # 스키마에 맞는 구조화 응답 (없으면 None)
    raw_text: str  # 응답 원문 (형식 재실패 시 수동 처리 화면에 보여준다)
    usage: CallUsage | None = None  # 원시 호출의 사용량 (없으면 None)


class AIProvider(Protocol):
    async def complete(self, prompt: str, schema: dict) -> ProviderResponse: ...
