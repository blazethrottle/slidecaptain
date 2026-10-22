# D4 생성 격리: 내장 스킬과 명령 끄기, Claude 실측 1회 (2026-10-22, Windows)

## 현재 상태

- 브랜치 `feat/d4-generation-isolation`(기준 main `eedab2a`)를 사용자 결정 "A. main에 머지"(2026-10-22)로 main에 머지했다(`91434e9`). 개발선은 main이다.
- 계획과 기록의 진본은 [D4 생성 격리 계획](../plans/2026-10-22-revision-d4-generation-isolation.md)이다. 2절 전제 정정, 4절 실제 호출 설계, 8절 리뷰 반영, 9절 결과 순서로 읽는다.
- 실제 AI 생성 호출은 1회다(사용자 결정 "A. Claude 1회 실행"). 승인된 호출은 모두 썼다.

| 커밋 | 내용 |
|---|---|
| `cb41476` | 생성 옵션 `--disable-slash-commands`, 관측 이름 목록, 기록 정정, 계획 1판. CI 두 OS 성공(실행 39701610159) |
| `6719aaa` | 리뷰 반영(GIR-01~08): 모델별 토큰, 판본과 플러그인 이름, 계획 2판. 백엔드 전체 3,007 통과. CI 두 OS 성공(실행 39704951348) |
| `b707a5c` | 실측 G1 결과(계획 9절), 로드맵, 이 인계, `CLAUDE.md` 최신 인계 줄. CI 두 OS 성공(실행 39706581393) |
| `91434e9` | main 머지 |
| 그 뒤의 문서 커밋 | 이 표와 머지 기록(인계, 로드맵, 계획서 머리말, `CLAUDE.md`) |

## 결과 요약

- 전날 "사용자 스킬과 플러그인이 실린다"는 기록은 틀렸다. 실린 것은 Claude Code 내장 명령, 스킬, 에이전트, 플러그인(`cc-plugin-*` 3개)이고 사용자 설정은 `setting_sources=[]`가 이미 막고 있었다.
- 생성 옵션에 `--disable-slash-commands`를 넣어 내장 명령과 스킬을 0개로 만들었다. 장 생성은 정상이고 주 모델 요청 크기(6,390토큰)는 그대로다. 스킬 목록은 `tools=[]` 때문에 원래 입력에 붙지 않았을 가능성이 크며, 이 옵션은 겹쳐 막는 방어다.
- 새로 관측한 것: 보조 모델(haiku)이 생성마다 주 모델과 거의 같은 크기의 입력(5,605토큰)을 받는다. 로드맵 D4a 이월표에 올렸다.
- 사용자 질문에 따라 Grok(xAI) 제공자 추가를 검토했다. Grok Build CLI는 세 번째 제공자로 붙일 수 있는 형태이고 Grok Bot은 맞지 않는다. 로드맵 D4a 이월표에 담당(D4 제공자 확장)과 함께 올렸다.

## 다음 즉시 행동

1. main의 머지 기록 커밋의 CI 두 OS 성공을 확인한다.
2. D4의 다음 단위를 사용자와 정한다. 후보: 보조 모델 haiku 호출의 용도와 끄기, Codex 쪽 대조(앱 전용 ChatGPT 로그인 필요), Grok 제공자 추가, 계정 프로필과 동의(D4c), 추천과 앱 안 안내(D4d).

## 사용자 결정 대기

1. D4의 다음 단위.

## 운용 사실

- 사용량 진단 줄(`SDK 사용량 원시 형태`)이 이제 `model_usage_by_model`에 모델별 (입력, 출력, 캐시 읽기, 캐시 생성)을 남긴다. 주 모델 요청 크기는 주 모델의 입력, 캐시 생성, 캐시 읽기의 합으로 본다. 합계(`model_usage_in`)에는 보조 모델 몫이 섞여 있다.
- 초기화 응답의 명령 개수는 같은 CLI 판에서도 실행마다 바뀐다(51, 53, 55). 개수 비교는 판정에 쓰지 않는다.
- 실측 도구와 CLI 판 확인, 메모리 부족 때의 시험 분할 방법은 [앞 인계](2026-10-21-d4-live-check.md) 「운용 사실」과 같다. 이 날은 백그라운드 명령이 메모리 부족으로 정리되어, 전체 시험을 앞에서 묶음별로 돌렸다.
- 머지는 사용자가 정하면 세션이 `git merge --no-ff`와 push를 한다. `git merge -F -`는 이 셸에서 표준 입력을 읽지 못하므로 메시지는 파일로 넘긴다.

## 새 회사 PC에서 재개할 때 (2026-10-22 기기 교체)

사용자가 2026-10-22 이 회사 PC(Windows)를 새 회사 PC(Windows)로 교체한다고 알렸다. 저장소의 기록은 모두 GitHub `main`에 있다(머지 기록 커밋 `9333c43`까지, CI 두 OS 성공).

1. 저장소를 clone하고 [Windows 개발 환경 인계](2026-10-02-windows-dev-environment.md)의 「Windows 기준선」과 「다음 세션 시작 방법」대로 준비한다: Python 3.13 가상 환경에 `backend[dev,desktop]` editable 설치, Node 22.17.1 x64(`.nvmrc`), `frontend`와 `desktop`에서 `npm ci`.
2. 로그인을 다시 한다: `gh auth login`(push와 CI 확인), Claude Code CLI(`claude auth status`로 확인, 계정 이메일은 기록하지 않음). 앱 전용 ChatGPT 프로필은 옛 PC에도 없었다.
3. 기준선을 다시 잰다: 백엔드는 `PYTHONUTF8=1`로 다섯 묶음, 프런트는 `npx vitest run --maxWorkers=4`, 공개 저장소 감사기. 새 PC의 메모리 여유와 긴 경로 설정(`LongPathsEnabled`)이 옛 PC와 다를 수 있다.
4. 설치 CLI 판과 모델 목록을 생성 없이 다시 읽는다. 옛 PC의 실측(2.1.306, 동봉 2.1.247)은 기기와 판에 묶인 값이다.

GitHub에 없는 것(공개 저장소라 설계상 빼 둔 것): 저장소 폴더의 `.gitignore` 대상(루트의 `projects/`, `exports/`, `feedback/`, 회사 오피스 파일, `docs/pilot`의 회사 자료), 루트의 미추적 피드백 JSON, 앱 자료 폴더 `~/slidecaptain-projects`, `Documents/slidecaptain-backups`, 실측 원시 산출물 `~/slidecaptain-live-check`(요지는 계획서에 있음). 필요한 것은 사용자가 회사가 허용하는 경로로 옮긴다. 세션이 GitHub로 올리지 않는다.

옛 PC의 Claude 메모리는 옮겨지지 않는다. 저장소 정본이 없던 교훈 3건은 위키 저장소 `raw/notes/2026-10-22_흡수큐_회사PC-교체-전-메모리전용-교훈-3건.md`로 옮겼고, 머지 방식 교훈의 정본은 이 저장소의 인계 문서 「운용 사실」이다.

## 파일 인덱스

| 파일 | 용도 |
|---|---|
| `docs/plans/2026-10-22-revision-d4-generation-isolation.md` | 이 단위의 계획, 리뷰 반영, 결과 |
| `docs/plans/2026-08-27-mvp-roadmap.md` | 「진행 상태」의 이 단위 줄, D4a 이월표(생성 세션 행 해소, 보조 모델 행, Grok 행), 방치 확정 문단 |
| `backend/slidecaptain/pipeline/subscription.py`, `provider.py` | 생성 옵션, 응답 관측, 사용량 진단 |
| `~/slidecaptain-live-check/2026-10-22/G1` | 실측 원시 산출물(커밋하지 않음) |
