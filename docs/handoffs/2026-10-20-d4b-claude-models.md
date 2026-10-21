# 업데이트 안내 초안(D)과 D4b Claude 공식 모델 목록 (2026-10-20, Windows)

## 현재 상태

사용자 지시 "D 실행 후 B"에 따라 두 브랜치를 만들었다. 둘 다 main 머지는 사용자 결정 대기다.

| 브랜치 | 커밋 | 내용 |
|---|---|---|
| `docs/d4-release-notes` | `5ab4ba8` | [개정판 업데이트 안내 초안](../releases/revision-update-notes.md). 최종 리뷰 이월 (4) ST-05가 약속한 안내 6건과 2026-10-20까지의 표시 변경, 고친 문제, 알려진 제한을 사용자 문구로 모았다. 버전 번호와 앱 안 표시는 D4d |
| `feat/d4b-claude-models` | 이 문서의 커밋 | [D4b 계획](../plans/2026-10-20-revision-d4b-claude-models.md). Claude 모델 목록을 공식 SDK 초기화 응답에서 읽고(정확 버전, 지원 강도), Claude 생성에 강도를 넘긴다 |

실제 AI 생성 호출 0회. Claude CLI의 초기화 응답(모델 메타데이터)만 읽었다.

## D4b 요약

- 회사 PC 사용자 프로필의 목록: `default`(→ `claude-opus-5[1m]`), `opus[1m]`, `claude-fable-5[1m]`(Fable), `sonnet`(→ `claude-sonnet-5`), `haiku`(→ `claude-haiku-4-5-20251001`, 강도 정보 없음). 임시 빈 프로필에는 Fable이 없다. 목록은 계정마다 다르다.
- 목록은 10분 캐시하고, 연결 신원이 바뀌면 버린다. 첫 조회 2.8초.
- 기존 별칭 `opus`는 목록에 없다. 이 별칭을 저장한 사용자는 생성 전에 "선택한 모델을 사용할 수 없습니다"로 막히고 다시 고른다(D4a와 같은 규칙). 업데이트 안내에 더할 항목이다(D 브랜치가 머지된 뒤).
- 검증: 백엔드 2,969 통과, 48 건너뜀, 실패 0(두 번에 나눠 실행). 프런트 1,339 통과. 데스크톱 31 통과.

## 사용자 결정 대기

1. `docs/d4-release-notes`와 `feat/d4b-claude-models`의 main 머지(리뷰와 CI 뒤).

## 다음 행동

1. D4b 리뷰와 CI 결과를 반영한다.
2. 머지 뒤 업데이트 안내 초안에 `opus` 재선택 안내를 더한다.
3. D4의 남은 단위: 실제 적용 모델과 강도의 계측(실제 생성 호출 필요, 예산 결정), 계정 프로필과 동의(D4c), 추천과 앱 안 안내(D4d).

## 운용 사실

- Claude 목록 조회는 `ClaudeSDKClient.get_server_info()`다. 초기화 응답에는 계정 정보도 들어 있으므로 모델 항목만 읽는다. 조회용 재현 스크립트는 세션 임시 폴더에 있었고 저장소에 넣지 않았다(`scripts/probe_ai_capabilities.py`가 같은 방법의 저장소 도구다).
- 임시 폴더를 정리할 때 CLI가 아직 끝나지 않아 Windows에서 삭제 오류(WinError 32)가 날 수 있다. 코드는 `ignore_cleanup_errors=True`로 둔다.
