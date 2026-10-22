# D4 실제 생성 확인: 구현, Claude 실측 3회, 코드 리뷰 (2026-10-21, Windows)

## 현재 상태

- 브랜치 `feat/d4-live-check`(기준 main `9d62455`). main 머지는 사용자 결정 대기다.
- 계획과 기록의 진본은 [D4 실제 생성 확인 계획](../plans/2026-10-21-revision-d4-live-check.md)이다. 3절 설계, 9절 계획 리뷰 반영, 10절 구현 기록, 11절 실측 결과, 12절 코드 리뷰 반영 순서로 읽는다.
- 실제 AI 생성 호출은 3회다(사용자 결정 "A. Claude 3회 실행", 2026-10-21). 승인된 호출은 모두 썼다. 다시 호출하려면 새 승인을 받는다.

| 커밋 | 내용 |
|---|---|
| `52e009d` | 계획서 1판 |
| `d1528a1` | 요청 강도 기록, 생성 경로 `strict_mcp_config`, 응답 관측 진단, 실측 도구 확장, 계획 리뷰 반영(LCR-01~16). CI 두 OS 성공(실행 39555693562) |
| `cd3058f` | Claude 실측 3회 결과 기록. CI 실행 39564897602 |
| 이 인계가 들어 있는 커밋 | 코드 리뷰 반영(LCC-01~09, 계획 12절), 이 인계, `CLAUDE.md` 최신 인계 줄. 백엔드 전체 시험과 CI 결과는 계획 12절과 커밋 메시지에 있다 |

## 실측 결과 요약

- `default`, `claude-fable-5-1[1m]`(설치 CLI 2.1.306), `opus[1m]`(동봉 CLI 2.1.247)은 `--model`로 받아들여지고 `--effort low`도 오류 없이 생성했다. 응답 모델은 목록의 해석된 모델과 같다(`[1m]`은 응답 모델에 붙지 않는다).
- 적용 강도는 초기화 메시지에도 칸이 없어 확인할 수 없다. 화면 문구("응답에서 확인할 수 없다")를 유지한다.
- 원장 `effort`와 `ai-usage.jsonl`의 `requested_effort`가 실제 경로에서 요청대로 남는다.
- 새로 관측한 것: 생성 세션에 사용자 스킬과 플러그인이 실린다(`setting_sources=[]`로 막히지 않음). `model_usage`에 보조 haiku 모델이 함께 잡힌다. 둘 다 로드맵 D4a 이월표에 올렸다.

## 다음 즉시 행동

1. 사용자에게 `feat/d4-live-check`의 main 머지를 묻는다. 묻기 전에 마지막 커밋의 CI 두 OS 성공과 공개 저장소 감사기 0건을 확인한다.
2. 머지 뒤 D4의 다음 단위를 사용자와 정한다. 후보: 생성 세션의 스킬과 플러그인 격리(실제 호출 재확인 필요), Codex 쪽 대조(앱 전용 ChatGPT 로그인 필요), 계정 프로필과 동의(D4c), 추천과 앱 안 안내(D4d).

## 사용자 결정 대기

1. `feat/d4-live-check`의 main 머지.
2. D4의 다음 단위.

## 운용 사실

- 이 세션에서 `quality_pilot.py`를 실제 모드로 돌리면, 도구가 실행 동안 이름이 `CLAUDE`로 시작하는 환경 변수를 빼고 끝나면 되돌린다. Claude Code 세션 안에서 돌릴 때 세션 연결 변수(`CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_EFFORT` 등 11개)가 CLI에 물려지지 않게 하기 위해서다. SDK는 `CLAUDECODE` 하나만 지운다.
- 설치 CLI는 자동으로 업데이트된다(이 날 2.1.304에서 2.1.306). 실측 직전에 판을 확인하고, 다르면 생성 없이 목록을 다시 읽는다.
- 메모리 여유가 적으면(이 날 2.1GB) 백엔드 전체 시험을 다섯 묶음으로 나눠 돌린다. 공개 저장소 감사 시험(`test_public_repo_audit.py`)은 한 번에 5분 넘게 걸리므로 `timeout`을 900초 이상으로 둔다.
- 시험에 가짜 계정 경로를 쓸 때는 문자열 조각을 이어 붙인다. 리터럴로 두면 공개 저장소 감사기가 잡는다.
- Claude 생성의 CLI 표준 오류는 환경 변수 `SLIDECAPTAIN_CLAUDE_STDERR_LOG=1`일 때만 받는다. 실측 도구가 실제 Claude 실행 동안 켜므로, 실패 원인은 출력 폴더의 `diagnostic.log`에서 본다. 앱과 개발 서버에서는 꺼져 있다.
- 머지는 사용자가 정하면 세션이 `git merge --no-ff`와 push를 한다.

## 파일 인덱스

| 파일 | 용도 |
|---|---|
| `docs/plans/2026-10-21-revision-d4-live-check.md` | 이 단위의 계획, 리뷰 반영, 구현 기록, 실측 결과 |
| `docs/plans/2026-08-27-mvp-roadmap.md` | 「진행 상태」의 이 단위 줄, D4a 이월표(둘째 행과 새 두 행) |
| `backend/scripts/quality_pilot.py` | 실측 도구. 행렬 한 칸은 `--live --consent --max-calls 1 --stop-after chapter --model <값> --effort <값> --claude-cli <경로>` |
| `backend/slidecaptain/pipeline/subscription.py`, `provider.py`, `codex.py` | 생성 옵션, 응답 관측, 실패 진단 |
| `backend/slidecaptain/storage/job_ledger.py`, `server/app.py`, `pipeline/service.py`, `pipeline/story_repair.py` | 요청 강도 기록 |
| `~/slidecaptain-live-check/2026-10-21/L1`~`L3` | 실측 원시 산출물(커밋하지 않음) |
