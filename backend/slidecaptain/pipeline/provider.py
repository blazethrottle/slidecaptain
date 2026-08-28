"""AI 프로바이더 인터페이스 (설계서 2.4, 단계 3 결정 2).

교체 지점을 원시 호출 하나로 좁힌다: 프로바이더는 프롬프트와 응답 스키마를
받아 구조화 응답을 돌려주기만 한다. 프롬프트 조립과 검증 게이트는 파이프라인
공통부(prompts, service)에 있다. 배포 단계의 앱 관리형(API 키), BYOK는
이 Protocol의 다른 구현으로 추가된다.
"""

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    """사용자에게 쉬운 말로 보여줄 AI 호출 오류 (설계서 7.2)."""


class ProviderNotAvailable(ProviderError):
    """호출 환경 자체가 없다 (Claude Code 미설치 등)."""


class ProviderCallFailed(ProviderError):
    """호출은 시도됐지만 실패했다 (미로그인, 한도 소진, 네트워크)."""


@dataclass
class ProviderResponse:
    structured: Any | None  # 스키마에 맞는 구조화 응답 (없으면 None)
    raw_text: str  # 응답 원문 (형식 재실패 시 수동 처리 화면에 보여준다)


class AIProvider(Protocol):
    async def complete(self, prompt: str, schema: dict) -> ProviderResponse: ...
