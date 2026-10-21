# D4 다음 단위 착수 준비: 실제 생성으로 확인 (2026-10-21, Windows)

## 현재 상태

- main `702a5c7`. D4b와 업데이트 안내를 머지했고 CI는 두 OS 모두 성공했다. 앞 단위의 기록은 [D4b 리뷰 반영 인계](2026-10-21-d4b-review.md)다.
- 2026-10-21 사용자 결정 "A로 승인": D4의 다음 단위는 **실제 생성으로 확인**이다. 사용자는 "이 승인 내용까지만 확인 후" 인계하라고 지시했다. 그래서 이 세션은 승인 기록과 이 인계까지만 했고, 계획서는 쓰지 않았다.
- **호출 횟수는 아직 승인되지 않았다.** 세션은 "합성 입력으로 최대 4회 정도"를 제안했고, "정확한 횟수는 실행 직전에 따로 여쭙겠다"고 약속했다. 이 승인 없이 실제 생성 호출을 시작하지 않는다.
- 실제 AI 생성 호출 0회.

## 이 단위가 답할 질문

1. Claude 목록 값을 CLI가 생성의 `--model`로 받는가. 받는다면 실제 응답 모델(assistant 메시지의 `model`)은 무엇인가. 목록 값은 CLI 판마다 다르다(D4b 계획 8절): 설치 CLI 2.1.304는 `default`, `opus`, `claude-fable-5-1[1m]`, `sonnet`, `haiku`이고, SDK 동봉 CLI 2.1.247은 `default`, `opus[1m]`, `claude-fable-5[1m]`, `sonnet`, `haiku`다. 특히 `default`와 `[1m]`이 붙은 값이 걸린다. 이 값들을 받지 않으면, 그 모델을 고른 사용자는 생성할 때마다 실패한다.
2. 추론 강도(`--effort`)를 붙인 생성이 오류 없이 끝나는가. 실제 적용 강도는 응답에서 확인할 수 없다고 화면에 적어 두었다(`frontend/src/screens/AISettingsPanel.tsx:194`). 응답에서 확인할 수 있는 범위를 정하고, 그 밖은 "확인 불가"로 기록한다.
3. 생성 경로에도 `strict_mcp_config=True`를 둘지(D4b 리뷰 CMR-07). 목록 조회에는 이미 두었다.
4. ChatGPT(Codex) 쪽에서 요청 강도와 실제 모델을 대조한다(로드맵 D4a 이월표 둘째 행).
5. 원장과 사용량에 요청 강도를 남긴다(같은 행). 지금은 기록하지 않는다(아래 「지금 코드의 사실」).

## 지금 코드의 사실 (main `702a5c7`)

| 대상 | 위치 | 사실 |
|---|---|---|
| Claude 생성 | `backend/slidecaptain/pipeline/subscription.py` `SubscriptionProvider.complete` | `ClaudeAgentOptions(model=..., effort=..., tools=[], setting_sources=[], max_turns=2)`로 `query()`를 부른다. `strict_mcp_config`는 없다. 실제 모델은 첫 assistant 메시지의 `model`이고, `build_call_usage`가 `CallUsage.model`에 싣는다 |
| Codex 생성 | `backend/slidecaptain/pipeline/codex.py` `CodexProvider.complete`(351행 부근) | 강도가 있으면 요청에 `effort`를 싣는다(382행). 실제 모델은 thread의 `model`이다 |
| 사용량 | `backend/slidecaptain/pipeline/provider.py` `CallUsage` | `model`, 토큰, 시간, 비용 칸만 있고 강도 칸은 없다. SDK가 주지 않는 값은 None이다(만들지 않는다) |
| 원장 | `backend/slidecaptain/storage/job_ledger.py` | `effort` 칸이 스키마에 있지만(137, 190행) 그 칸에 값을 쓰는 코드는 없다 |
| CLI 경로 | `backend/slidecaptain/pipeline/auth_status.py` `resolve_cli_path` | 환경 변수 `SLIDECAPTAIN_CLAUDE_CLI`가 먼저다. 다음은 SDK 동봉 CLI, 마지막이 PATH다. 개발 실행은 동봉 CLI를 쓰고, 데스크톱 앱은 설치 CLI(`~/.local/bin/claude.exe`)를 쓴다. 실측할 CLI는 환경 변수로 정한다 |

## 쓸 수 있는 도구

- `backend/scripts/quality_pilot.py`: 합성 3장 관통 도구다. `--offline`(고정 응답), `--live --consent --provider {claude,codex} --model <ID> --max-calls N`이 있다. 상한은 최초 실패, 형식 재시도, 자동 축약, 후속 재작성이 함께 쓴다. 상한을 넘거나 오류가 나면 종료 코드 2이고, 출력 폴더는 매번 새로 쓴다. 사용법은 [2026-09-28 인계](2026-09-28-quality-pilot-handoff.md)에 있다. **추론 강도 옵션은 없으므로** 이 단위에서 더할지 정한다.
- `scripts/probe_ai_capabilities.py`: 모델 메타데이터만 읽고 생성은 하지 않는다.
- 앞선 실제 호출의 선례: 2026-09-28 Sonnet, 2026-09-29 LUNA 합성 3장, 2026-09-30 LUNA 12/12회(실패와 재시도 0회). 규칙은 이렇다. 실패와 형식 재시도도 상한에 포함한다. 자동 제공자 전환은 없다. 결과를 품질 통과로 올리지 않는다.

## 다음 세션의 첫 행동

1. 이 문서, [D4b 계획](../plans/2026-10-20-revision-d4b-claude-models.md) 8절, 로드맵 D4a 이월표 둘째 행, 위키 공통 지침 `engineering.md`를 읽는다.
2. `git pull --ff-only`로 main을 맞추고, 최근 CI가 두 OS 모두 성공인지 확인한다.
3. 계획서 `docs/plans/<날짜>-revision-d4-live-check.md`를 쓴다. 담을 것:
   - 위 질문 다섯 개
   - 호출 행렬(제공자 × 모델 × 강도 × CLI 경로)과 행마다의 호출 상한
   - 합성 입력(실제 회사 자료는 쓰지 않는다)
   - 기록 위치와 형식(계정 정보와 원시 초기화 응답은 남기지 않는다)
   - 원장과 사용량의 강도 기록을 이 단위에서 구현할지
   - 상한에 넣는 범위(실패, 형식 재시도)
4. 계획을 리뷰어 1명에게 적대 리뷰로 맡기고 반영한다(저장소 품질 게이트).
5. 사용자에게 호출 횟수와 대상을 묻는다. 묻는 내용은 정확한 횟수, 쓸 계정, 쓸 CLI 경로다. 승인이 나기 전에는 실제 호출을 하지 않는다.
6. 코드 변경이 있으면 실패하는 시험부터 쓴다. 실행 뒤 결과를 계획서에 기록하고 로드맵 이월표를 갱신한다.

## 사용자 결정 대기

1. 실제 생성 호출의 횟수와 대상(다음 세션이 계획서와 함께 묻는다).

## 운용 사실

- 이 PC의 Claude Code CLI 로그인 계정은 실행 전에 `claude auth status`로 확인한다. 실제 생성은 그 계정의 구독 사용량을 쓴다. 계정 이메일은 기록에 남기지 않는다.
- 메모리 여유가 적으면(2026-10-21 0.9GB) Claude Code가 쉬는 동안의 백그라운드 명령을 끊는다. 백엔드 전체 시험은 다섯 묶음으로 나눠 앞에서 하나씩 돌린다(묶음마다 10분 안). 방법은 [앞 인계](2026-10-21-d4b-review.md) 「운용 사실」에 있다.
- push한 커밋마다 두 OS의 CI가 끝날 때까지 본다. `gh run watch <id> --exit-status`를 10분 안쪽으로 나눠 건다.
- 머지는 사용자가 정하면 세션이 `git merge --no-ff`와 push를 한다. 선택지 A를 "두 브랜치 모두 머지"로 적은 질문에 사용자가 "A"로 답한 경우, 자동 승인 검사기가 머지를 막지 않았다(2026-10-21).

## 파일 인덱스

| 파일 | 용도 |
|---|---|
| `docs/plans/2026-10-20-revision-d4b-claude-models.md` | D4b 설계, CI 실패와 리뷰 반영, 설치 CLI 실측 |
| `docs/plans/2026-08-27-mvp-roadmap.md` | 「진행 상태」의 이 단위 줄, D4a 이월표 |
| `docs/releases/revision-update-notes.md` | 업데이트 안내 초안. 이 단위에서 사용자에게 알릴 것이 생기면 여기에 더한다 |
| `backend/scripts/quality_pilot.py` | 실제 관통 도구 |
| `backend/slidecaptain/pipeline/subscription.py`, `codex.py`, `provider.py`, `storage/job_ledger.py` | 위 「지금 코드의 사실」 |
