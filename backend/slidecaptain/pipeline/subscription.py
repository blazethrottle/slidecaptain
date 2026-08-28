"""본인 구독 프로바이더 (설계서 2.4의 1단계): Agent SDK로 로그인된 Claude Code를 구동한다.

실증(2026-08-28, 로드맵 미확인 리스크 해소): API 키 없이 호출이 성공하며
이 PC의 Claude Code 구독 로그인이 자동으로 쓰인다. output_format(json_schema)
지정 시 ResultMessage.structured_output으로 파싱 완료된 JSON이 돌아온다.

오류 원문(영문 stderr 등)은 로그로만 남기고 사용자 문구에는 넣지 않는다 (설계 결정 14).
"""

import logging

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKError,
    CLIConnectionError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    query,
)

from slidecaptain.pipeline.provider import (
    ProviderCallFailed,
    ProviderNotAvailable,
    ProviderResponse,
)

_LOG = logging.getLogger("slidecaptain.pipeline.subscription")

# CLI 기본 모델(opus 계열)은 사소한 호출에도 사용량이 크다 (2026-08-28 스파이크 실측).
# 별칭을 써서 세부 버전 교체에 흔들리지 않게 한다.
DEFAULT_MODEL = "sonnet"


class SubscriptionProvider:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or DEFAULT_MODEL

    async def complete(self, prompt: str, schema: dict) -> ProviderResponse:
        options = ClaudeAgentOptions(
            tools=[],  # 도구 없이 순수 생성만
            setting_sources=[],  # 사용자 설정 격리: CLAUDE.md와 스킬이 생성에 개입하지 못하게
            # 구조화 출력 경로는 생성 1턴 + 구조화 출력 정리 1턴을 쓴다: 2가 실측 최소값이다
            # (2026-08-28 스모크 격리 진단. 트리비얼 프롬프트에서만 통과하던 max_turns=1로는
            # 실제 생성 프롬프트가 "Reached maximum number of turns (1)"로 거부됐다).
            # 스키마 불일치 시 SDK 자체의 재프롬프트 여지는 없다: 그 경우는 앱의 형식 게이트가 담당한다.
            max_turns=2,
            model=self.model,
            output_format={"type": "json_schema", "schema": schema},
        )
        result: ResultMessage | None = None
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result = message
        except CLINotFoundError as e:
            raise ProviderNotAvailable(
                "Claude Code를 찾지 못했습니다. 이 앱의 AI 생성에는 Claude Code 설치와 "
                "구독 로그인이 필요합니다."
            ) from e
        except (CLIConnectionError, ProcessError, ClaudeSDKError) as e:
            _LOG.warning("AI 호출 실패: %s", e)
            raise ProviderCallFailed(
                "AI 호출에 실패했습니다. Claude Code 로그인 상태와 구독 사용 한도를 "
                "확인한 뒤 잠시 후 다시 시도해 주세요."
            ) from e
        if result is None or result.is_error:
            _LOG.warning("AI 호출 비정상 종료: %s", result.errors if result else "응답 없음")
            raise ProviderCallFailed(
                "AI 호출이 정상적으로 끝나지 않았습니다. 잠시 후 다시 시도해 주세요."
            )
        return ProviderResponse(structured=result.structured_output, raw_text=result.result or "")
