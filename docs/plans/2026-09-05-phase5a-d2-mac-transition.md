# 단계 5A 묶음 D2: Mac Mini 개발 전환 마무리 계획서 (2026-09-05, 적대 리뷰 반영 2026-09-05)

> 마스터 플랜 [2026-09-01-phase5a-master-plan.md](2026-09-01-phase5a-master-plan.md) 묶음 D2 의 상세 계획. C 완료(2026-09-05, `codex/phase-5a` 390cec6) 뒤 착수한다.
> 브랜치 `codex/phase-5a` 에서 태스크마다 커밋하고, 태스크별 독립 리뷰와 묶음 최종 리뷰를 거친 커밋을 `origin/codex/phase-5a` 에 push 한다. **D2 완료 = 단계 5A 전체 완료**이며 그 뒤 `main` 에 머지한다(사용자 결정 2026-09-03. 2026-09-05 실측: `main` 은 `codex/phase-5a` 의 조상이고 main 전용 커밋이 0 이라 fast-forward 머지가 가능하다).
> 리뷰 게이트: 계획서 적대 리뷰(세 관점 병렬, 2026-09-05 18건 반영, 아래 "적대 리뷰 반영" 절) → 태스크별 TDD 구현(구현자와 독립 리뷰어 분리, 리뷰어는 구현 직전 커밋에서 RED 재실증) → 묶음 최종 리뷰(세 관점 + 반박자) → 반영과 검증 → push. C 묶음과 같다.
> **사용자 결정 4건 (2026-09-05)**: ① D2 관통의 실제 AI 호출은 **1회만** 승인한다(구독 사용량 사용. C 계획서 가정 1 의 실측 필요 3항목을 같은 호출로 확인) ② 완료 관문의 "Windows 에서도 같은 흐름이 유지된다" 는 D1 과 같이 **CI windows-latest 성공으로 갈음**한다(물리 Windows 관통 없음) ③ Mac 실행 스크립트는 **더블클릭용 `.command`** 로 만든다 ④ 감사기 파일명 규칙 이월 항목은 D2 에 넣지 않고 **후속 회차**로 미룬다.

## 범위와 원인 묶음

| 태스크 | 포함 항목 | 공통 원인 |
|---|---|---|
| D2-1. 버전 단일 출처 | 패키지 버전과 FastAPI 앱 버전을 `slidecaptain.__version__` 하나로 모은다 | 이월표 "패키지 버전(0.1.0)과 FastAPI 앱 버전(0.2.0) 표기 정리". 두 값이 따로 적혀 어긋나 있다 |
| D2-2. 테스트의 폰트 설치 격리 | 백엔드 테스트 전체가 실제 사용자 폰트 폴더를 읽거나 쓰지 않게 공용 픽스처로 격리하고, 폰트 자동 설치의 실환경 실증을 관통에서 기록한다 | 이월표 "`test_cli.py::test_serve_binds_localhost_only` 가 `ensure_fonts()` 를 격리하지 않아 폰트 미설치 PC 에서 테스트 실행이 실제 폰트 폴더에 설치" 와 "폰트 자동 설치의 실환경 실증 1회" |
| D2-3. Mac 실행 스크립트 | 저장소 루트 `SlideCaptain실행.command`(더블클릭). Windows `SlideCaptain실행.bat` 와 같은 흐름: 이미 떠 있으면 브라우저만, 아니면 서버를 띄우고 응답을 기다린 뒤 브라우저를 연다 | 마스터 플랜 D2 산출물 "실행 스크립트". Mac 에는 실행 경로가 없다(로드맵 진행 상태 "Mac Mini 실행 경로는 단계 5A D 에서 추가") |
| D2-4. 문서와 개발 명령 | `README.md` 전면 갱신(상태, 문서 목록, macOS 와 Windows 실행, 개발 환경 구성, 폰트, 데이터 폴더, CI 와 감사기, 배포 순서), `CLAUDE.md` 명령 절을 macOS 기준 + Windows 병기로 | README 상태 절이 2026-08-28 에 멈춰 있고 실행 절이 Windows 전용이다. Mac 개발 환경 함정(iCloud 폴더, uv 에 pip 없음, worktree PYTHONPATH)이 이월표와 CLAUDE.md 에만 있다 |
| D2-5. SDK 원시 사용량 로그 | `build_call_usage` 가 `ResultMessage` 의 `usage` dict 키 목록, `model_usage` 의 모델 키 목록, 두 출처의 토큰 합, `num_turns` 를 내용 없이 INFO 로그 1줄로 남긴다 | 이월표 "D2 관통 실측 항목". 실호출 1회로 C 계획서 가정 1 의 ①②③ 을 전부 판정하려면 원시 키와 두 합계가 같은 호출에서 보여야 한다 |
| D2-6. 관통 (메인 세션 수동) | 새 클론에서 README 대로 환경 구성 → `.command` 로 서버 실행 → 폰트 재설치 실증 → 비기밀 프로젝트 생성과 텍스트와 XLSX 업로드 → AI 전송 확인 대화 상자 → **구조안 생성 1회(실호출)** → 사용량 표시와 기록 파일 확인 → 샘플 덱 편집과 저장 → PPTX 내보내기와 코드 재열기 → 기록 | 마스터 플랜 D2 완료 관문과 "단계 5A 통합 검증" 표 |

이 묶음에 넣지 않는 것(마스터 플랜 "만들지 않는 것" 과 사용자 결정): 앱 마켓 포장, 코드 서명, 자동 업데이트, macOS PowerPoint 자동 캡처, 물리 Windows 관통(②), 감사기 파일명 규칙(④), Linux 지원, 브라우저가 열리지 않을 때의 재시도 UI, 장 생성 실호출(①: 구조안 생성 1회 뒤의 승인 루프는 실행하지 않는다), Keynote 표시 검증의 합격 판정(PowerPoint 가 이 Mac 에 없어 "열림" 만 기록).

## 가정 (실측한 것과 확인이 필요한 것)

1. **이 Mac 의 환경 (2026-09-05 실측)**: macOS(Darwin 25.6), uv 0.10.12, fnm 1.39.0 에 Node 22.17.1 과 24.14.1(기본), 가상환경 Python 3.13.12(uv 로 생성, pip 없음), `claude-agent-sdk` 0.2.145, FastAPI 0.141.1. Claude CLI 는 `claude.ai` 로그인 상태. `/Applications` 에 PowerPoint 없음, Keynote 있음. `~/Library/Fonts` 에 `NotoSansKR-Regular.ttf` 와 `NotoSansKR-Bold.ttf` 가 이미 있음(2026-09-02 테스트 실행이 설치한 것). 기본 데이터 폴더 `~/slidecaptain-projects` 는 아직 없음. 활성 클론 `~/Projects/slidecaptain`(main) 과 worktree `~/Projects/slidecaptain-5a`(codex/phase-5a).
2. **`.command` 의 동작**: Finder 더블클릭이 Terminal 창을 열어 bash 로 실행하며 작업 폴더는 홈이다. 따라서 스크립트는 `cd "$(dirname "$0")"` 로 자기 위치로 이동한다. 실행 비트가 필요하고 Git 이 모드 `100755` 로 추적한다(`.bat` 는 `100644`). 줄 끝은 LF(`.gitattributes` 가 이미 `*.command text eol=lf` 를 선언하고 `test_repo_metadata.py` 가 `scripts/run.command` 라는 가상 경로로 속성을 검사한다). Git 클론에는 quarantine 속성이 없어 Gatekeeper 가 막지 않는다고 본다(**관통에서 확인**). Windows `.bat` 는 서버를 별도 `cmd /k` 창에 띄우지만 macOS 에서는 `.command` 가 연 Terminal 창 자체가 서버 창이다: 서버를 그 창의 전경에서 돌리고, 브라우저는 뒤에서 응답을 기다렸다가 연다. 창을 닫거나 Ctrl+C 를 누르면 서버가 멈춘다(문구로 안내). 종료 보장은 시그널 전파 경로에 맡기지 않는다: 서버를 배경으로 띄운 직후 `trap 'kill "$SERVER_PID" 2>/dev/null' EXIT INT TERM HUP` 을 걸어 스크립트가 어떤 경로로 끝나든 배경 서버를 직접 정리한다(적대 리뷰 env-2: Terminal 의 job control 설정에 따라 Ctrl+C 가 배경 서버에 닿지 않을 수 있다). 파일명은 기존 `.bat` 와 같이 NFC 로 커밋한다(env-6). Gatekeeper 비차단은 `xattr` 실측으로 확인됐다(추적 파일에 `com.apple.quarantine` 없음. 더블클릭 정책만 관통에서 최종 확인).
3. **버전 단일 출처**: `backend/slidecaptain/__init__.py` 에 `__version__ = "0.1.0"` 을 두고, `pyproject.toml` 은 `dynamic = ["version"]` 과 `[tool.setuptools.dynamic] version = {attr = "slidecaptain.__version__"}` 로 그 값을 읽으며, `create_app` 의 `FastAPI(version=...)` 도 그 값을 쓴다. 값은 로드맵 표제(v0.1)에 맞춰 **0.1.0** 이다(앱의 0.2.0 은 단계 2 에서 임의로 올린 값이라 근거가 없다). OpenAPI `info.version` 이 0.2.0 → 0.1.0 으로 바뀌므로 `backend/openapi.json` 을 재생성한다(`openapi-typescript` 는 `info` 를 타입으로 내지 않으므로 `types.ts` 는 무변경일 것으로 본다. **재생성으로 확인**). setuptools 의 `attr` 은 editable 설치에서도 동작한다(적대 리뷰가 스크래치 트리에 `uv venv` 와 `uv pip install -e` 로 실험해 `importlib.metadata` 가 0.1.0 을 돌려주고 `types.ts` 가 바이트 단위로 무변경임을 확인했다. CI 의 `pip install -e` 는 CI 실행으로 확인). **worktree 에서 빌린 가상환경의 `importlib.metadata` 는 main 클론의 정적 메타데이터를 읽으므로 그 테스트는 dynamic 메커니즘의 검증이 아니다. 검증은 관통 1 의 새 클론 설치가 유일하다**(env-4). `app.py` 는 `from slidecaptain import __version__` 을 상단에 추가해야 한다(env-3: import 없이 바꾸면 `NameError`).
4. **폰트 격리**: `backend/tests/conftest.py` 에 autouse 픽스처를 두어 모든 테스트에서 `installer._user_font_dir` 를 `tmp_path` 아래 빈 폴더로, `_system_font_dirs` 를 빈 목록으로 바꾼다. 기존 `test_fonts.py` 는 테스트마다 같은 두 함수를 다시 monkeypatch 하므로 충돌 없이 덮어쓴다. 이 픽스처가 있으면 `main(["serve", ...])` 를 부르는 CLI 테스트가 실제 폴더 대신 임시 폴더에 설치한다. **실환경 실증은 관통에서** 한다: `~/Library/Fonts` 의 두 파일을 임시 폴더로 옮긴 뒤 `serve` 를 한 번 실행해 "설치했습니다" 안내와 파일 복원을 확인한다(되돌리기: 앱이 번들에서 다시 복사하므로 옮긴 파일은 삭제해도 된다. 실패하면 임시 폴더의 파일을 되돌린다).
5. **SDK 원시 로그의 내용**: 로그 한 줄에는 `usage` dict 의 **키 이름 목록**(정렬), `model_usage` 의 **키(모델 id) 목록**, `usage` dict 에서 읽은 입력과 출력 토큰 합과 `model_usage` 전체의 입력과 출력 토큰 합, `num_turns`, `total_cost_usd` 유무만 담는다. **네 합계는 `build_call_usage` 의 if/elif 가 고른 `token_source` 와 무관하게 `usage` dict 와 `model_usage` 를 각각 독립적으로 합산해 채운다**(한쪽이 없으면 그쪽만 `None`. 적대 리뷰 sdk-1: 기존 분기는 상호 배타라 지역 변수를 재사용하면 `model_usage` 가 있을 때 `usage` 합이 항상 `None` 이 되어 로그의 존재 이유가 사라진다). 캐시 읽기와 캐시 생성 토큰도 두 출처 각각의 합으로 함께 적는다(비교는 입력, 출력, 캐시 세 항목을 따로 본다). 프롬프트와 응답과 오류 문구는 담지 않는다. 판정 규칙(관통에서 적용): ① `usage` 키가 `input_tokens` 계열 snake_case 인지 그대로 읽는다 ② `model_usage` 키가 1개 이상이면 "채워짐" ③ 두 출처가 모두 있을 때 `usage` 합이 `model_usage` 합과 같으면 폴백 값은 **세션 누적**, 작으면 **마지막 턴 값**이다(그러면 C 의 "대략" 표시가 가리키는 값이 실제보다 작을 수 있으므로 `build_call_usage` 의 폴백을 재검토한다). 실호출이 형식 재시도로 2회가 되면 두 줄이 남으며 둘 다 판정 근거다. **판정 보류 규칙**(sdk-2): 표본이 1회뿐이므로 두 합계가 같지도 뚜렷이 작지도 않고 애매하게 가깝거나, `num_turns` 가 2 가 아니거나, 두 출처 중 하나가 없으면 ③ 은 "미확인" 을 유지하고 후속 관통(5B 파일럿의 실호출)에서 재확인한다. 억지로 결론을 내지 않는다.
6. **관통의 실호출 1회 경계**: 화면에서 "구조안 생성" 을 한 번 누른다. 형식 재시도가 자동으로 붙으면 SDK 호출은 2회가 되지만 사용자 조작은 1회이고 이것이 승인의 단위다(계획서에 명시). 구조안을 **승인하지 않는다**(승인 루프가 장마다 호출한다). 편집과 저장과 내보내기 검증용 덱은 AI 없이 만든다: `backend/tests/test_exporter.py` 의 덱 생성 코드를 참고한 스크래치 스크립트로 `deck.json` 을 만들어 그 프로젝트 폴더에 넣는다(비기밀 합성 내용).
7. **Windows**: `.bat` 와 Windows 명령은 손대지 않는다. CI windows-latest 가 백엔드 전체(격리 픽스처 포함)와 프런트와 빌드를 같은 순서로 실행하므로 완료 관문의 Windows 문장은 CI 성공으로 갈음한다(②). README 의 Windows 절은 종전 내용을 유지하되 macOS 절과 같은 구조로 정렬한다.
8. **README 의 독자는 비개발자다.** 실행 절은 더블클릭을 먼저 쓰고 명령은 그 아래에 둔다. 각 명령 위에 무엇을 하는지 한 줄을 붙인다. `CLAUDE.md` 는 도구가 읽는 문서라 명령 중심으로 둔다.

## 태스크 D2-1: 버전 단일 출처

**변경 (`backend/slidecaptain/__init__.py`, `backend/pyproject.toml`, `backend/slidecaptain/server/app.py`, `backend/openapi.json` 재생성)**

- `__init__.py`: `__version__ = "0.1.0"` 한 줄(주석: 단일 출처. pyproject 와 FastAPI 앱이 이 값을 읽는다).
- `pyproject.toml`: `version = "0.1.0"` 줄을 지우고 `dynamic = ["version"]` 추가, `[tool.setuptools.dynamic] version = {attr = "slidecaptain.__version__"}` 추가.
- `app.py`: 상단에 `from slidecaptain import __version__` 을 추가하고 `FastAPI(title="Slide Captain", version=__version__)`.
- `openapi.json` 재생성(`info.version` 0.1.0). `types.ts` 는 재생성해 무변경을 확인한다.

**테스트 (실패부터, `backend/tests/test_openapi.py` 또는 신규 `test_version.py`)**

- `slidecaptain.__version__` 이 정규식 `\d+\.\d+\.\d+` 에 맞고, `pyproject.toml`(`tomllib`)의 `project.dynamic` 에 `"version"` 이 있으며 `project` 에 정적 `version` 키가 없다.
- `create_app(store).version == slidecaptain.__version__` 이고 `/openapi.json` 의 `info.version` 도 같다.
- `importlib.metadata.version("slidecaptain")` 이 `__version__` 과 같다(패키지가 설치되지 않은 환경은 `PackageNotFoundError` 로 skip. worktree 에서 빌린 가상환경은 main 클론의 editable 메타데이터를 보므로 값이 같을 때만 의미가 있다).

## 태스크 D2-2: 테스트의 폰트 설치 격리

**변경 (`backend/tests/conftest.py`)**

- autouse 픽스처 `isolated_font_dirs(tmp_path, monkeypatch)`: `installer._user_font_dir` 를 `tmp_path / "user_fonts"` 를 돌려주는 함수로, `installer._system_font_dirs` 를 `[]` 를 돌려주는 함수로 바꾼다. docstring 에 사유(이월표 행)를 적는다.
- 제품 코드는 바꾸지 않는다. `_run_serve` 가 함수 안에서 `from slidecaptain.fonts.installer import ensure_fonts` 를 하므로 모듈 속성 교체가 그대로 적용된다.

**테스트 (실패부터, `backend/tests/test_cli.py`)**

- `test_serve_binds_localhost_only` 뒤에 신규 테스트: uvicorn 을 가짜로 바꾼 채 `main(["serve", ...])` 를 부르면 격리된 사용자 폰트 폴더(`installer._user_font_dir()`)에 `NotoSansKR-Regular.ttf` 와 `NotoSansKR-Bold.ttf` 가 생기고, 그 폴더가 `tmp_path` 아래이며 `Path.home() / "Library/Fonts"` 가 아니다. 또 `capsys` 로 "설치했습니다" 안내가 출력됐음을 단언한다. **RED 근거**: 픽스처가 없으면 이 Mac 에서는 폰트가 이미 있어 `already` 가 되어 안내가 출력되지 않고 격리 폴더도 비어 있다. 폰트가 없는 환경(CI 러너)에서는 픽스처 없이 돌리면 실제 사용자 폰트 폴더에 설치되므로 "격리 폴더가 `tmp_path` 아래" 단언에서 RED 가 되고, 그 과정에서 실제 설치가 부수 효과로 일어난다(러너는 폐기되므로 무해. env-5). 두 환경 모두 RED 이며 경로만 다르다.
- 기존 `test_fonts.py` 전부와 `test_cli.py` 전부가 통과한다(픽스처 우선순위 충돌 없음).

## 태스크 D2-3: Mac 실행 스크립트

**변경 (`SlideCaptain실행.command` 신설, `.github/workflows/ci.yml`, `backend/tests/test_repo_metadata.py`)**

- `SlideCaptain실행.command`(bash, `#!/bin/bash`, LF, 모드 755, UTF-8 한국어 안내): ① `cd "$(dirname "$0")/backend"` ② 가상환경 `.venv/bin/python` 이 없으면 "README 의 macOS 개발 환경 구성을 먼저 해 주세요" 안내 후 종료 1 ③ `curl -s -o /dev/null --max-time 1 http://127.0.0.1:8765/` 가 되면 이미 실행 중이므로 `open` 으로 브라우저만 열고 종료 0 ④ 아니면 서버를 배경(`&`)으로 띄우고 최대 30회(회당 1초) 응답을 기다리며 진행 표시 ⑤ 응답하면 `open http://127.0.0.1:8765` 뒤 `wait` 로 서버 프로세스를 전경에 붙잡는다(이 창이 서버 창이다. 닫거나 Ctrl+C 로 종료한다는 안내를 먼저 출력) ⑥ 30회 안에 응답이 없으면 서버 프로세스를 정리하고 실패 안내 후 종료 1. **④ 직후에 `trap 'kill "$SERVER_PID" 2>/dev/null' EXIT INT TERM HUP` 을 건다**(가정 2). 스크립트는 PATH 에 의존하지 않고 `.venv/bin/python` 절대 경로만 쓴다. 파일명은 NFC 로 저장한다. `frontend/dist` 가 없으면 서버가 스스로 "API 만 제공" 을 출력하므로 스크립트는 별도 검사를 하지 않는다.
- `ci.yml` 의 줄바꿈 바이트 검사 단계에 `SlideCaptain실행.command` 가 LF 이고 실행 비트(`git ls-files -s` 모드 `100755`)를 가졌는지 추가한다.
- `test_repo_metadata.py`: 속성 검사의 가상 경로 `scripts/run.command` 를 실제 경로 `SlideCaptain실행.command` 로 바꾸고, 작업트리 검사에 `.command` 의 LF 와 셔뱅(`#!/bin/bash`)과 Git 인덱스 모드 `100755` 를 추가한다. `bash -n` 문법 검사 1건(`shutil.which("bash")` 없으면 skip. Windows 러너에는 Git Bash 가 있어 보통 통과한다).

**테스트 (실패부터)**: 위 `test_repo_metadata.py` 항목이 파일 부재로 실패한 뒤 파일 생성으로 통과한다. 스크립트 동작 자체는 자동 테스트하지 않고 관통(D2-6)에서 실행으로 확인한다(계획서에 명시).

## 태스크 D2-4: 문서와 개발 명령

**변경 (`README.md`, `CLAUDE.md`)**

- `README.md`: (1) 상태 절을 로드맵 진행 상태와 맞춘다(단계 1~4 완료, 파일럿과 소형 묶음, 5A 의 D1 과 A 와 B 와 C 완료와 D2 진행. 진본은 로드맵이라는 문장 유지) (2) 문서 목록에 단계 3 과 4 계획서, 5A 마스터 플랜, 파일럿 관찰지, 설계서를 추가하고 "묶음별 상세 계획서 전체는 로드맵의 단계 표와 진행 상태 절에서 찾는다" 한 줄로 나머지를 가리킨다(계획서 15건을 전부 나열하지 않는다. docs-3) (3) "실행" 절을 **macOS: `SlideCaptain실행.command` 더블클릭 / Windows: `SlideCaptain실행.bat` 더블클릭** 으로 쓰고, 처음 실행 전 개발 환경 구성이 필요하다는 안내 (4) "개발 환경 구성" 절 신설: macOS(`uv venv --python 3.13` → `uv pip install --python .venv/bin/python -e ".[dev]"` → `fnm install 22.17.1` 과 `fnm use` → `frontend` 에서 `npm ci` 와 `npm run build`), Windows(종전 명령 유지). 명령마다 위에 한 줄 설명 (5) "주의" 절: 클론을 iCloud 동기화 폴더(`~/Documents` 등)에 두지 말 것(`.pth` hidden 플래그로 editable 설치가 무력화된다. 이월표 실측), uv 가상환경에는 pip 가 없어 `uv pip` 를 쓸 것, worktree 에서 백엔드 테스트는 `PYTHONPATH` 필요 (6) 폰트 절: 첫 `serve` 가 Noto Sans KR 을 사용자 폰트 폴더에 자동 설치(macOS `~/Library/Fonts`, Windows 사용자 폰트 폴더), 실패 시 수동 설치 경로 (7) 데이터 폴더 기본값 `~/slidecaptain-projects` 와 `--data-dir` (8) 검증과 CI 절: 백엔드와 프런트 테스트, 재생성, 감사기, CI 가 두 OS 에서 도는 것과 CI 가 보증하지 않는 것(AI 로그인과 호출, PowerPoint 표시, 폰트 설치 실증) (9) 배포 순서: 서버 종료 → `npm run build` → 실행 스크립트 → 브라우저 새로고침(옛 서버와 새 화면이 섞이면 저장 유실 창이 생긴다는 로드맵 기록 인용).
- `CLAUDE.md`: "명령 (Windows 기준)" 절을 "명령 (macOS 기준, Windows 병기)" 로 바꾸고 각 항목에 `backend/.venv/bin/python` 과 `.venv/Scripts/python.exe` 를 병기한다. 실행 스크립트 2종을 적는다. nvm4w 32비트 우회 이력 단락은 명령이 아니라 경위 서술이므로 "Windows 전용 참고" 로 표시해 남긴다(docs-5). "푸시 전 검증과 CI" 절의 감사기 명령도 macOS 경로를 앞에, Windows 경로를 괄호에 두는 순서로 맞춘다(docs-6). 그 밖의 절은 손대지 않는다.
- 길이 통제(docs-4): README 는 접기 마크업 없이 "실행" 절을 더블클릭 2줄로 맨 앞에 두고 개발 절을 뒤에 둔다. **README 전체 120줄 이내**를 상한으로 하고 넘으면 리뷰어가 지적한다.

**테스트**: 문서 태스크라 자동 테스트는 없다. 대신 (a) `bash -n` 없이도 README 의 macOS 명령을 **관통의 새 클론에서 그대로 복사해 실행**하는 것이 검증이다(D2-6) (b) 리뷰어가 README 의 모든 파일 경로와 명령이 저장소에 실재하는지 대조한다 (c) 금지 문자 0건.

## 태스크 D2-5: SDK 원시 사용량 로그

**변경 (`backend/slidecaptain/pipeline/subscription.py`)**

- `build_call_usage` 안(또는 그 직전)에서 `_LOG.info` 한 줄: 예 `SDK 사용량 원시 형태: usage_keys=['cache_creation_input_tokens', ...] model_usage_keys=['claude-sonnet-4-5-20250929'] usage_in=1234 usage_out=56 model_usage_in=1234 model_usage_out=56 num_turns=2 total_cost_usd=있음`. 값이 없으면 `None` 으로 적는다. 문자열 포맷은 f-string 이며 프롬프트와 응답과 오류 문구 변수는 참조하지 않는다.
- 로그 레벨은 INFO 다. uvicorn 기본 설정에서 `slidecaptain` 로거의 INFO 가 콘솔에 보이는지 확인하고, 보이지 않으면 `__main__.py` 의 `serve` 에서 `logging.basicConfig(level=logging.INFO)` 를 한 번 부른다(다른 INFO 로그가 지나치게 늘면 이 로거만 INFO 로 올린다. 구현자가 실측해 결정하고 커밋 메시지에 적는다).

**테스트 (실패부터, `backend/tests/test_subscription_provider.py`)**

- `caplog` 로 `model_usage` 와 `usage` 가 모두 있는 `ResultMessage` 를 `build_call_usage` 에 넣으면 INFO 레코드 1건에 두 키 목록과 네 합계와 `num_turns` 가 있고, 프롬프트 조각과 `raw_text` 는 없다. 둘 다 없는 경우 `usage_keys=[]` 와 `None` 합계로 기록된다.

## 태스크 D2-6: 관통 (메인 세션이 수동으로 수행하고 기록한다)

워크플로가 아니라 메인 세션이 아래 순서로 수행하고, 결과를 이 계획서의 "관통 기록" 절(마지막 문서 커밋에서 신설)에 항목별로 적는다. 각 항목은 **CI 로 확인 / 실기기로 확인 / 미수행(사유)** 셋 중 하나로 표기한다(마스터 플랜 통합 검증 표의 구분).

1. **새 클론 환경 구성**: 스크래치 폴더(iCloud 밖)에 **`git clone --branch codex/phase-5a`** 로 받는다(env-1 critical: GitHub 기본 브랜치는 `main` 이고 머지는 관통 뒤라, 브랜치를 지정하지 않으면 D2 변경이 하나도 없는 코드를 관통하게 된다. 클론 직후 `git rev-parse --short HEAD` 가 push 된 최신 커밋과 같은지 확인해 기록한다). 그 뒤 README 의 macOS 명령을 그대로 복사해 실행한다(uv venv, uv pip install, fnm, npm ci, npm run build). 백엔드 테스트 1회, 프런트 테스트 1회. 여기서 막히면 README 를 고친다(문서 정정 커밋).
2. **실행 스크립트**: 새 클론의 `SlideCaptain실행.command` 를 `open` 으로 실행해(Finder 더블클릭과 같은 경로) Terminal 창이 열리고 서버가 뜨고 브라우저가 열리는지, 이미 떠 있을 때 다시 실행하면 브라우저만 여는지, 창을 닫으면 서버가 멈추는지 확인한다. Gatekeeper 가 막으면 가정 2 를 정정하고 우회 안내를 README 에 적는다.
3. **폰트 재설치 실증**: `~/Library/Fonts` 의 Noto 두 파일을 스크래치로 옮긴 뒤 `serve` 를 1회 실행해 "설치했습니다" 안내와 파일 복원을 확인한다. `font_installed()` 가 참이 되는지 파이썬으로 확인한다.
4. **비기밀 프로젝트**: 브라우저에서 새 프로젝트를 만들고 텍스트 자료와 `backend/tests/fixtures/synthetic/` 의 합성 XLSX 를 올려 추출본을 확인한다.
5. **AI 전송 확인과 실호출 1회**: 구조안 생성을 누르면 고지 대화 상자가 뜬다. 먼저 **취소**해 호출 없이 끝나는지 확인하고, 다시 눌러 **동의** 뒤 구조안 1회 생성(승인 ①). 확인 항목: 화면의 사용량 한 줄(모델, 호출 수, 토큰, 시간, 참고 비용), 프로젝트 폴더 `ai-usage.jsonl` 1줄, 서버 로그의 D2-5 원시 로그로 가정 5 의 ①②③ 판정, 호출 뒤 `ps` 에 남은 `claude` 프로세스가 없는지(C 계획서 "틀렸을 가능성" 의 조기 종료 항목. SDK 는 동봉 `claude` 바이너리를 `--output-format stream-json --verbose` 로 띄우므로 `ps aux | grep claude` 로 잡힌다). 예상되는 부수 출력: 루트 로거를 INFO 로 올리므로 SDK 의 `Using bundled Claude Code CLI: <경로>` 한 줄이 함께 보인다(내용 아님. sdk-4). **구조안은 승인하지 않는다.**
6. **편집과 저장과 내보내기**: 가정 6 의 스크래치 덱을 프로젝트 폴더에 넣고 브라우저에서 편집 탭에서 문구를 고쳐 저장(저장됨 표시), 스냅샷 생성, PPTX 내보내기, `python-pptx` 로 재열기(슬라이드 수와 도형 이름 "장ID:슬롯" 확인). Keynote 로 열어 "열림" 을 기록한다(PowerPoint 표시는 도구 부재로 미수행).
7. **Windows**: CI windows-latest 의 최신 성공 실행 id 를 기록한다(②).
8. **정리와 판정**: 새 클론과 스크래치 덱을 지우고, 실호출 결과에 따라 C 계획서 가정 1 의 "실측 필요" 를 실측 결과로 바꾼다(가정 5 의 판정 보류 규칙 적용. 다르면 `build_call_usage` 수정을 별도 fix 커밋으로 하고 **독립 리뷰어 1명이 구현 직전 커밋에서 RED 를 재실증한 뒤** 반영한다. docs-7). C 계획서 "이 계획이 틀렸을 가능성" 의 `_consume` 조기 종료 불릿에 관통 5 의 `ps` 결과를 병기한다(sdk-3). 로드맵 이월표의 "아주 작은 양수 비용의 $0 표시와 `usage` dict 폴백의 캐스팅 비대칭" 행은 처리 시점이 "D2 실측으로 `usage` dict 값 형태가 확인되면" 이므로, 원시 로그의 값 형태(정수인지)로 그 조건의 충족 여부를 판정해 적는다(docs-2).

## 문서 정정 (마지막 커밋)

- 로드맵 이월표: "폰트 자동 설치의 실환경 실증 1회", "패키지 버전과 FastAPI 앱 버전 표기 정리", "`test_cli.py` 가 `ensure_fonts()` 를 격리하지 않아...", "Mac 개발 환경: 클론이 iCloud...", "Mac Mini 를 주 개발 환경으로 전환", "D2 관통 실측 항목" 6행을 처리 완료(실측 결과 요약 포함)로. "감사기 `_is_secret_filename`" 행은 "후속 회차(사용자 결정 2026-09-05)" 로 처리 시점만 정정. 진행 상태에 5A D2 항목과 **5A 전체 완료** 표기, 5A 요약 줄을 `[x]` 로.
- 로드맵 "단계 5A 확정 범위" 표의 D 행 문구 "양 OS 실기기 관통을 확정" 을 "macOS 실기기 관통을 확정하고 Windows 는 CI windows-latest 성공으로 갈음(사용자 결정 2026-09-05)" 으로 날짜와 사유를 달아 정정하고, 마스터 플랜 "단계 5A 통합 검증" 표의 Windows 열("Windows 실기기", "불가")에 같은 갈음 사실을 각주로 단다(docs-1. D1 때 같은 간극을 남겼으므로 이번에 닫는다).
- 로드맵 이월표의 "$0 표시와 캐스팅 비대칭" 행에 관통 8 의 조건 판정 결과를 적는다(docs-2).
- C 계획서 "이 계획이 틀렸을 가능성" 의 `_consume` 조기 종료 불릿에 `ps` 확인 결과 병기(sdk-3).
- 설계서 9.1 항목 7 에 구현 완료 표기. 4.4 절의 "실측 미확인" 문장을 실측 결과로 정정.
- C 계획서 가정 1 의 실측 필요 3항목에 실측 결과 병기.
- 이 계획서에 "관통 기록" 절과 "구현 리뷰 반영" 표.
- `CLAUDE.md` 는 D2-4 에서 이미 정정.

## 실행 순서

D2-1 → D2-2 → D2-3 → D2-5 → D2-4(문서는 스크립트 이름과 명령이 확정된 뒤) → 전체 검증과 push 와 CI → 묶음 최종 리뷰(세 관점 + 반박자) → 반영 → D2-6 관통(실호출 1회) → 문서 정정 커밋 → push 와 CI → 5A 완료 → `main` 머지. 검증 명령은 C 와 같다(worktree 백엔드 테스트는 `PYTHONPATH` 필수).

관통이 묶음 최종 리뷰 **뒤**인 이유(docs-7): 실호출은 1회뿐이라 최종 리뷰 반영까지 끝난 최종 코드에서 한 번만 해야 관통 결과가 곧 배포 상태의 근거가 된다. 대신 최종 리뷰는 C 와 같이 실제 서버로 헤더 관문과 스크립트 기동(대체 서버)까지 재현하고, 관통에서 fix 커밋이 나오면 관통 8 의 독립 리뷰 절차를 거친다.

`main` 머지(docs-8): main 클론 `~/Projects/slidecaptain` 에서 `git pull` 뒤 `git merge --ff-only codex/phase-5a` 와 `git push origin main` 을 실행한다(fast-forward 가 안 되면 멈추고 사용자에게 보고). 머지 직전에 사용자에게 결과를 보고한다(사용자 결정 2026-09-03 에 따른 실행이지만 되돌리기 어려운 조치의 마지막 확인). worktree `~/Projects/slidecaptain-5a` 와 브랜치 정리는 비가역이라 별도의 사용자 확인 사항으로 남기고 이 묶음에서 하지 않는다.

## 완료 관문 대조 (마스터 플랜 D2)

| 관문 문장 | 확인 수단 | 담당 |
|---|---|---|
| Mac Mini 새 클론에서 환경 구성 | 실기기 (관통 1) | D2-4 문서, D2-6 |
| 서버 실행 | 실기기 (관통 2) | D2-3, D2-6 |
| 비기밀 샘플과 XLSX 업로드 | 실기기 (관통 4) + CI(B 테스트) | D2-6 |
| AI 전송 확인 | 실기기 (관통 5, 취소와 동의) + CI(B 테스트) | D2-6 |
| 저장 | 실기기 (관통 6) + CI(A 테스트) | D2-6 |
| PPTX 내보내기와 재열기 | 실기기 (관통 6, python-pptx 재열기) + CI(골든 테스트) | D2-6 |
| Windows 에서도 같은 흐름 | **CI windows-latest 로 갈음**(사용자 결정 ②) | D2-6 항목 7 |
| CI 확인 항목과 실기기 확인 항목의 구분 기록 | 관통 기록 절의 3분류 표기 | 문서 정정 |
| (D1 이월) 실제 AI 로그인, 폰트 설치 실증, PowerPoint 표시 | 로그인과 실호출은 실기기(관통 5), 폰트 실기기(관통 3), PowerPoint 미수행(도구 부재. Keynote 열림만 기록) | D2-6 |

## 적대 리뷰 반영 (2026-09-05)

세 관점 리뷰어(환경과 스크립트, SDK 로그와 관통 절차, 문서와 완료 관문 대조. ultracode 가 꺼진 세션이라 Workflow 대신 sonnet 서브에이전트 3개를 병렬로 띄웠다)가 반박했고 셋 다 "수정 후 승인"(발견 18건: critical 1, major 3, minor 8, nit 6). 18건 전부 반영.

| 관점 | 반영한 것 |
|---|---|
| 환경과 스크립트 | 관통 1 의 클론이 브랜치를 지정하지 않으면 D2 변경이 없는 `main` 을 관통하게 됨(critical), `.command` 의 배경 서버 정리를 `trap` 으로 보장(major), `app.py` 의 `__version__` import 명시, worktree 의 `importlib.metadata` 테스트가 dynamic 검증이 아님을 명시, RED 의 환경별 경로와 부수 효과, 파일명 NFC. 실험으로 확인해 준 것: setuptools dynamic 이 `uv pip install -e` 에서 동작, `types.ts` 무변경, Gatekeeper 비차단, `git ls-files -s` 가 `core.filemode` 와 무관, 태스크별 커밋 자족성 |
| SDK 로그와 관통 | 원시 로그의 네 합계를 분기와 무관하게 독립 합산(major), 단일 표본의 판정 보류 규칙, C 계획서의 프로세스 잔존 불릿에 `ps` 결과 병기, `logging.basicConfig` 채택 확정(실측: uvicorn 은 루트 로거를 건드리지 않아 INFO 레코드가 생성조차 안 되며 basicConfig 는 유지됨)과 SDK 부수 출력 예고. 확인해 준 것: 취소는 호출 0회, 자동 트리거 경로 없음, 스크래치 덱은 `test_exporter.py` 의 `_write_deck` 패턴으로 가능, 폰트 이동은 안전 |
| 문서와 관문 | 로드맵 확정 범위 표 D 행과 마스터 플랜 통합 검증 표의 Windows 문구 정정(major), 이월표 조건부 행의 판정, README 문서 목록 기준과 120줄 상한, CLAUDE.md 의 nvm4w 단락과 푸시 전 검증 절 순서, 관통이 최종 리뷰 뒤인 근거와 fix 의 독립 리뷰, 머지 디렉터리와 worktree 정리의 분리 |

## 이 계획이 틀렸을 가능성

- `.command` 를 `open` 으로 실행하는 것과 Finder 더블클릭이 완전히 같지 않을 수 있다(로그인 셸 환경 차이로 `fnm` 이나 `uv` 경로가 다를 수 있다). 스크립트는 가상환경의 절대 경로 python 만 쓰므로 PATH 에 의존하지 않게 만든다. 그래도 다르면 관통 기록에 적는다.
- Gatekeeper 가 클론된 `.command` 를 막을 수 있다(quarantine 은 다운로드 파일에만 붙는다고 보지만 확인하지 않았다). 막히면 "우클릭 → 열기" 우회를 README 에 적는다.
- setuptools 의 `dynamic` 버전이 `uv pip install -e` 에서 다르게 동작할 수 있다. 관통 1 의 새 클론 설치가 검증이다. 실패하면 정적 `version` 으로 되돌리고 테스트로 두 값의 일치만 강제한다.
- 실호출 1회가 형식 재시도로 2회가 될 수 있다(가정 6 에 명시). 그 이상은 절대 발생하지 않는다(승인 루프를 실행하지 않는다).
- `model_usage` 가 실제로 채워지면 가정 5 ③ 의 폴백 판정은 두 합계 비교로만 가능하고, `model_usage` 가 비어 있으면 ③ 을 직접 관측하지만 ② 가 "안 채워짐" 이 되어 C 의 1순위 출처가 실효를 잃는다. 어느 쪽이든 결과를 C 계획서에 적고, 후자면 `build_call_usage` 의 출처 우선순위를 재검토한다.
- 폰트 재설치 실증은 사용자 폰트 폴더를 건드린다. 두 파일을 지우지 않고 옮기며, 앱이 번들에서 복사하므로 원상 복구가 항상 가능하다.
- README 를 비개발자 기준으로 쓰면 길어진다. 실행 절은 더블클릭 2줄로 끝내고 개발 절은 접어 두는 구조로 길이를 통제한다(Karpathy 2항).
- 최종 리뷰가 관통 결과를 보지 못하는 순서다(docs-7 의 근거로 감수). 관통에서 나온 fix 는 독립 리뷰를 거치되 최종 리뷰를 다시 돌리지는 않는다.
- 단일 실호출로 가정 5 ③ 을 못 가를 수 있다(sdk-2). 그때는 "미확인" 으로 남기며 C 의 "대략" 표시가 그 불확실성을 계속 알린다.
- 문서 태스크(D2-4)는 자동 테스트가 없어 리뷰 의존도가 높다. 리뷰어에게 "README 의 모든 명령을 새 클론에서 실제로 실행" 을 요구하는 대신 관통 1 이 그 역할을 하므로, 리뷰어는 경로와 이름의 실재 여부와 문구만 대조한다.
