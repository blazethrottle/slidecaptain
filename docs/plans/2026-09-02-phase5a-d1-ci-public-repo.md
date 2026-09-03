# 단계 5A D1 양 OS 자동 검증과 공개 저장소 경계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Every production-tooling change starts with a failing behavior test, each task receives an independent review, and the whole D1 range receives a final review.

**Goal:** Windows와 macOS에서 동일한 검증을 자동 실행하고, 공개 GitHub에 회사 원자료와 로컬 산출물과 인증정보가 들어가는 실수를 코드와 Git 규칙으로 차단한다.

**Architecture:** 제품 실행 코드와 개발 안전장치를 분리한다. 저장소 감사기는 Git이 실제로 추적하는 파일만 검사하는 독립 CLI로 만들고, GitHub Actions는 로컬에서 사용하는 pytest, Vitest, Vite 빌드, OpenAPI 타입 생성 명령을 그대로 조합한다. 운영체제 차이는 Git 줄바꿈 속성과 Actions 행렬에만 둔다.

**Tech Stack:** Python 3.13 표준 라이브러리, pytest, Git, GitHub Actions, Node.js 22.17.1, npm, Vitest, Vite

**Base commit:** `6de6de0`

**Parent plan:** `docs/plans/2026-09-01-phase5a-master-plan.md`의 묶음 D1

## Global Constraints

- 제품의 API, 화면, 덱 스키마와 내보내기 동작은 바꾸지 않는다.
- 감사기는 비밀값을 출력하지 않고 규칙 이름과 파일 경로만 출력한다.
- 감사기는 기본 실행에서 현재 Git 추적 파일을 검사하고, `--history` 실행에서 삭제된 과거 커밋의 경로와 명백한 키 패턴까지 검사한다.
- Office 파일은 기본적으로 추적을 거절한다. 단계 5A B의 XLSX 테스트는 `backend/tests/fixtures/synthetic/` 아래에서 새로 만든 비기밀 픽스처만 예외로 허용한다.
- 회사 원자료, 실제 파일럿 자료, 개인 인증정보, 생성 PPTX, 로컬 프로젝트 데이터, 의존성, 빌드 산출물, 임시 리뷰 기록은 커밋하지 않는다.
- 자동 감사기는 임의의 일반 텍스트가 기밀인지 의미로 판정할 수 없다. 구조적 차단과 별개로 매 푸시 전에 새로 추적되는 파일을 사람이 검토한다.
- YAML이나 문서 문구를 문자열 검색만으로 통과시키는 테스트를 만들지 않는다. Git 규칙은 `git check-ignore`와 `git check-attr`의 실제 결과로 검사하고, Actions는 GitHub의 실제 Windows와 macOS 실행 결과로 검증한다.
- 실제 Claude 로그인, 실호출, PowerPoint 화면 확인은 CI에서 실행하지 않는다.
- 각 태스크의 검토가 끝나기 전에는 다음 태스크로 넘어가지 않는다.

---

### Task 1: 공개 저장소 감사 CLI

**Files:**

- Create: `scripts/audit_public_repo.py`
- Create: `backend/tests/test_public_repo_audit.py`

**Behavior contract:**

- `python scripts/audit_public_repo.py`는 현재 저장소 루트를 자동으로 찾는다.
- `python scripts/audit_public_repo.py --root <임시 Git 저장소>`는 테스트용 저장소를 검사한다.
- 기본 입력 목록은 `git ls-files -z` 결과만 사용한다. 무시된 파일과 추적되지 않은 파일은 검사 대상이 아니다.
- 도구 폴더 `.venv`, `node_modules`, `.superpowers`, `.worktrees`, `__pycache__`는 경로 어디에 있든 거절한다. 런타임 데이터 폴더 `projects`, `uploads`, `exports`, `snapshots`, `dist`는 저장소 루트 바로 아래일 때만 거절하고, 빌드 산출 폴더 `frontend/dist`는 예외로 함께 거절한다. `distribution.md`처럼 일부 글자만 같은 정상 파일과 `frontend/src/pages/projects/List.tsx`처럼 하위 경로에 같은 이름이 나오는 정상 파일은 거절하지 않는다. (2026-09-03 정정: 구 문구 "독립된 경로 구성 요소이면 어디서든 거절"은 재작업 이전 리뷰가 실측한 오탐을 만들었다)
- 리뷰 원문 기록은 저장소 밖(스크래치 폴더, 인계 폴더)에 두는 것이 관례이며, `docs/reviews/` 아래의 추적 파일은 그 원문이 저장소에 들어오는 것을 막는 방어 규칙으로 거절한다. (2026-09-03 명문화: 재작업이 신설한 규칙인데 문서 근거가 없었다)
- `docs/pilot/` 아래에서는 최상위의 `YYYY-MM-DD-파일럿-관찰지.md` 형식만 허용하고, `raw/`, `tmp/`, 텍스트, CSV, 이미지, 추출 자료를 포함한 나머지 파일은 확장자와 관계없이 거절한다.
- `.pptx`, `.docx`, `.pdf`, `.xls`, `.xlsx`는 대소문자와 관계없이 거절한다. 단, `backend/tests/fixtures/synthetic/` 아래의 `.xlsx`만 허용한다.
- `.env`, `.env.*`, 개인 키 확장자, basename이 `credential` 또는 `credentials`, `secret` 또는 `secrets`인 파일을 거절한다. `secretary.ts`처럼 일부 글자만 같은 정상 파일과 `.env.example`은 경로 규칙에서 허용하되 내용 검사는 그대로 받는다.
- Anthropic, OpenAI, GitHub, AWS 키 접두어, 개인 키 헤더, 환경변수에 직접 대입한 키로 보이는 바이트 패턴을 거절한다.
- 실패 출력은 `규칙: 상대경로` 형식이며 발견한 비밀 문자열 자체는 포함하지 않는다.
- 추적된 심볼릭 링크는 링크 대상 파일을 열지 않고 링크 경로 자체만 검사한다. 저장소 밖을 가리키거나 깨진 링크여도 외부 내용을 읽거나 중단하지 않는다.
- `--history`는 모든 도달 가능한 커밋의 과거 경로와 텍스트 diff를 검사한다. 이미 삭제된 금지 경로와 키 패턴도 현재 파일과 같은 비노출 형식으로 보고한다.
- 발견 0건은 종료 코드 0, 한 건 이상은 종료 코드 1이다. Git 명령 실패는 종료 코드 2와 쉬운 한국어 오류를 반환한다.

**Step 1: Write the failing behavior tests**

`backend/tests/test_public_repo_audit.py`에서 임시 Git 저장소를 만들고 다음을 각각 검증한다.

1. 안전한 Python과 Markdown 파일만 추적하면 통과한다.
2. 무시된 미추적 XLSX는 검사하지 않는다.
3. 추적된 `projects/demo/deck.json`, 루트 밖 위치의 대문자 `.XLSX`, `docs/pilot/raw/brief.txt`, `docs/pilot/raw/data.csv`는 실패한다.
4. 임시 저장소 안의 `backend/tests/fixtures/synthetic/sample.xlsx`는 추적해도 통과한다. D1 저장소 자체에는 XLSX 픽스처를 만들지 않는다.
5. `docs/pilot/2026-09-02-파일럿-관찰지.md`, `distribution.md`, `secretary.ts`는 경로 규칙만으로 거절하지 않는다.
6. 런타임에 문자열 조각을 이어 만든 가짜 키를 추적 파일에 쓰면 실패한다.
7. 실패 stdout과 stderr에 가짜 키 전체 값이 나오지 않는다.
8. 만들 수 있는 운영체제에서는 `link.txt`가 저장소 밖의 가짜 키 파일을 가리키는 심볼릭 링크여도 외부 값을 읽지 않고, 깨진 심볼릭 링크도 중단하지 않는다. Windows가 심볼릭 링크 생성을 거절하면 그 경우만 건너뛰고 macOS CI에서는 반드시 실행한다.
9. 금지 경로와 가짜 키를 커밋한 뒤 삭제한 임시 저장소에서 기본 검사는 통과하지만 `--history` 검사는 실패한다.
10. Git 저장소가 아닌 경로는 종료 코드 2다.

**Step 2: Run the focused test and observe RED**

Run from `backend`:

```text
.venv/Scripts/python.exe -m pytest tests/test_public_repo_audit.py -q
```

Expected: `scripts/audit_public_repo.py`가 아직 없어 실패한다.

**Step 3: Implement the minimum CLI**

`scripts/audit_public_repo.py`에 다음 단위를 둔다.

- `Finding(rule: str, path: str)` 불변 데이터 구조
- `tracked_paths(root: Path) -> list[str]`
- `historical_paths(root: Path) -> list[str]`
- `audit_paths(paths: list[str]) -> list[Finding]`
- `audit_contents(root: Path, paths: list[str]) -> list[Finding]`
- `audit_repository(root: Path, include_history: bool = False) -> list[Finding]`
- `main(argv: Sequence[str] | None = None) -> int`

Git 경로는 `/`로 정규화하고 경로 구성 요소 단위로 비교하며 대소문자와 확장자 차이를 흡수한다. 과거 경로는 NUL 구분 Git 출력을 사용한다. 과거 diff는 값을 출력하지 않고 패턴 존재 여부만 판정한다. 파일 내용 검사는 심볼릭 링크를 따라 저장소 밖을 읽지 않는다. 비밀 패턴 리터럴이 감사기 자신의 소스에 그대로 나타나 자기 자신을 오탐하지 않도록 접두어 조각을 코드에서 결합한다.

**Step 4: Run GREEN and regression tests**

Run from `backend`:

```text
.venv/Scripts/python.exe -m pytest tests/test_public_repo_audit.py -q
.venv/Scripts/python.exe -m pytest tests -q
```

Run from repository root:

```text
backend/.venv/Scripts/python.exe scripts/audit_public_repo.py
backend/.venv/Scripts/python.exe scripts/audit_public_repo.py --history
```

Expected: 모든 테스트와 실제 저장소 감사가 통과하고 출력에 경고나 비밀값이 없다.

**Step 5: Commit**

```text
git add scripts/audit_public_repo.py backend/tests/test_public_repo_audit.py
git commit -m "feat: 공개 저장소 추적 파일을 감사한다"
```

**재작업과 리뷰 기록 (2026-09-02 ~ 09-03, Mac Mini)**

- 최초 구현(be6fb96, c238f3c)의 독립 리뷰가 미탐 4계열(PKCS8 헤더, 신형 키 접두어와 YAML 콜론 대입, 파일명 규칙, 잘못된 UTF-8 경로 크래시)과 오탐 2계열(환경변수 조회식과 CI 문법, 하위 경로의 `projects` 등 폴더명)을 실측해 재작업했다(8afb53b). 위 계약 문구 두 곳(금지 폴더 판정 기준, `historical_diff` 유닛)은 그 재작업이 계획서와 달리 한 편차이며, 리뷰가 둘 다 타당하다고 판정해 계약을 고쳤다.
- 재작업 리뷰(2026-09-03, 판정 "수정 후 승인")가 새 미탐 1건을 찾았다: 오탐을 줄이며 환경변수 이름의 대소문자 구분을 켰더니 pydantic Settings 관례인 소문자 이름(`anthropic_api_key = "..."`)의 실제 값을 놓쳤다. 값 형태 제한이 오탐을 막는 실질 조건이라 대소문자 무시를 복원해도 오탐 회피 테스트가 그대로 통과함을 리뷰어와 구현자가 각각 검증했다. AKIA 양성 테스트와 한계 문서화(확장자 없는 zip 시그니처 오피스 파일, 중첩 빌드 폴더 관례)도 함께 반영했다(65476b2). 감사 테스트 54건 → 58건.
- 이월(이 태스크 범위 밖, 로드맵 이월표 등재는 태스크 4의 문서 커밋에서): `_is_secret_filename`이 `google-credentials.json`, `secret_key.py`, `.secrets`처럼 앞뒤에 글자가 붙은 이름을 잡지 않는다(계약은 정확한 basename만 요구). 테스트 공백: 추적 중이지만 작업트리에서 삭제된 파일의 경로 규칙, 미추적 도구 폴더가 있을 때의 오탐 없음.
- 검증 환경 주의: 이 작업공간(worktree)은 가상환경이 없어 main 클론의 `backend/.venv`로 실행한다. 그 editable 설치가 main 클론의 패키지를 가리키므로 백엔드 전체 테스트는 main 병합 전에는 `capacity`, `prompts`, `openapi` 4건이 어긋난다(감사기와 무관). main 병합 뒤 재실행해 확인한다.

---

### Task 2: macOS와 Windows용 Git 무시 및 줄바꿈 규칙

**Files:**

- Create: `backend/tests/test_repo_metadata.py`
- Create: `backend/tests/fixtures/eol/probe.sh`
- Create: `backend/tests/fixtures/eol/probe.command`
- Modify: `.gitignore`
- Modify: `.gitattributes`

**Behavior contract:**

- macOS의 `.DS_Store`, Windows의 `Thumbs.db`, 편집기 임시 파일, 일반 `.venv`, 빌드와 테스트 산출물, 런타임 프로젝트 하위 폴더를 Git이 무시한다.
- `docs/pilot/`에서는 날짜가 붙은 파일럿 관찰지만 추적할 수 있고, 원자료와 임시 추출물은 확장자와 관계없이 무시한다.
- Office 파일은 위치와 관계없이 기본 무시한다. `backend/tests/fixtures/synthetic/*.xlsx`만 무시 예외다. 실제 합성 XLSX 파일은 단계 5A B에서 만든다.
- `.env`와 `.env.*`는 무시하되 `.env.example`은 추적할 수 있다.
- 모든 텍스트는 저장소에서 LF로 정규화한다. Windows 배치 파일만 CRLF로 체크아웃한다. `.command`와 `.sh`는 LF를 강제한다.
- 폰트와 이미지 같은 바이너리는 텍스트 줄바꿈 변환 대상이 아니다.
- 저장소에 작은 `.sh`와 `.command` 줄바꿈 픽스처를 두고 실제 체크아웃 바이트를 검사한다.

**Step 1: Write failing Git behavior tests**

`backend/tests/test_repo_metadata.py`에서 저장소 루트를 기준으로 실제 Git 명령을 호출한다.

- `git check-ignore --no-index`가 `.DS_Store`, `tmp/.DS_Store`, `Thumbs.db`, `.env.local`, `projects/demo/uploads/demo.xlsx`, `projects/demo/exports/demo.pptx`, `projects/demo/snapshots/demo.json`, `docs/pilot/raw/brief.txt`를 무시한다고 확인한다.
- 같은 명령이 `.env.example`, `docs/pilot/2026-09-02-파일럿-관찰지.md`, `backend/tests/fixtures/synthetic/sample.xlsx`를 무시하지 않는다고 확인한다.
- `git check-attr eol`이 `.bat`에는 `crlf`, `.command`, `.sh`, `.py`, `.md`, `.yml`에는 `lf`를 반환한다고 확인한다.
- `git check-attr text`가 실제 동봉 `.ttf`에 `unset`을 반환한다고 확인한다.
- 실제 작업트리 바이트에서 `SlideCaptain실행.bat`는 CRLF를 포함하고, 두 줄바꿈 픽스처는 CRLF를 포함하지 않는다고 확인한다.

**Step 2: Run the focused test and observe RED**

Run from `backend`:

```text
.venv/Scripts/python.exe -m pytest tests/test_repo_metadata.py -q
```

Expected: 현재 `.DS_Store`, `.env.local`, LF 규칙이 없어 실패한다.

**Step 3: Apply minimal Git rules**

`.gitignore`의 기존 회사 자료 설명을 유지하면서 `docs/pilot/`를 관찰지 명명 규칙의 Markdown만 허용하는 방식으로 좁히고, 모든 Office 파일을 무시한 뒤 비기밀 합성 XLSX 경로만 다시 허용한다. `.gitattributes`에는 기본 LF, 배치 파일 CRLF, 셸 스크립트 LF, 바이너리 확장자 규칙을 선언한다. 두 줄바꿈 픽스처는 실행 동작을 포함하지 않는 두 줄짜리 파일로 만든다. 기존 파일 전체의 의미 없는 줄바꿈 재커밋은 만들지 않는다.

**Step 4: Run GREEN, audit, and full backend tests**

Run from `backend`:

```text
.venv/Scripts/python.exe -m pytest tests/test_repo_metadata.py -q
.venv/Scripts/python.exe -m pytest tests -q
```

Run from repository root:

```text
backend/.venv/Scripts/python.exe scripts/audit_public_repo.py
git diff --check
```

Expected: Git 동작 테스트와 전체 백엔드 테스트가 통과하고, 기존 추적 파일에 대량 줄바꿈 diff가 생기지 않는다.

**Step 5: Commit**

```text
git add .gitignore .gitattributes backend/tests/test_repo_metadata.py backend/tests/fixtures/eol/probe.sh backend/tests/fixtures/eol/probe.command
git commit -m "chore: Windows와 macOS Git 규칙을 고정한다"
```

---

**리뷰 기록 (2026-09-03, 판정 "수정 후 승인" → 반영)**: `.gitignore` 의 런타임 폴더 4개(`projects/` 등)가 루트에 고정되지 않아 `frontend/src/pages/projects/List.tsx` 같은 하위 경로까지 무시했다(감사기 `_ROOT_DATA_DIRECTORIES` 는 루트 기준). `/projects/` 형태로 앵커링하고 하위 경로 4건이 추적 가능하다는 테스트를 추가했다. `.sh` 와 `.command` 의 명시 규칙은 기본 규칙과 eol 결과가 같아 지워도 테스트가 못 잡았으므로, `text` 속성이 `auto` 가 아니라 `set` 인지 검사하는 테스트를 추가했다(규칙 제거 시 실제 실패 확인). 테스트 26 → 34. 리뷰어가 `git ls-files -z` 로 전수 확인한 결과 새 규칙에 걸리는 기존 추적 파일은 0건이다(`xargs` 로 파이프하면 한글 파일명이 이스케이프되어 거짓 양성이 나오므로 `-z` 를 쓸 것).

### Task 3: Windows와 macOS GitHub Actions

**Files:**

- Create: `.github/workflows/ci.yml`
- Create: `.nvmrc`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `CLAUDE.md`

**Behavior contract:**

- 모든 push와 pull request에서 Windows와 macOS 작업을 각각 실행한다.
- Python 3.13과 Node.js 22.17.1을 사용한다. `frontend/package.json`과 `.nvmrc`도 같은 Node 기준을 선언한다.
- 두 운영체제에서 공개 저장소 감사, 백엔드 전체 테스트, OpenAPI 재생성, 프런트 타입 재생성, 생성 파일 무변경 확인, 프런트 전체 테스트, 화면 빌드를 실행한다.
- 새 체크아웃의 실제 바이트를 검사해 배치 파일은 CRLF, `.sh`와 `.command` 픽스처는 LF인지 확인한다.
- Actions 권한은 저장소 읽기만 허용한다.
- 실제 AI 로그인과 PowerPoint는 호출하지 않는다.

**Step 1: Record the failing acceptance state**

Run from repository root:

```text
gh workflow list
```

Expected: 이 저장소에 CI workflow가 없어 D1의 양 OS 자동 검증 관문을 만족하지 못한다.

**Step 2: Add the minimal workflow and version contract**

`.github/workflows/ci.yml`의 각 운영체제 작업은 다음 순서를 사용한다.

1. checkout
2. setup-python 3.13과 `backend/pyproject.toml` 기준 pip 캐시
3. Python 한 줄 명령으로 `SlideCaptain실행.bat`와 두 줄바꿈 픽스처의 실제 바이트 검사
4. setup-node 22.17.1과 `frontend/package-lock.json` 기준 npm 캐시
5. `python -m pip install -e "./backend[dev]"`
6. `frontend`에서 `npm ci`
7. `python scripts/audit_public_repo.py`
8. `backend`에서 `python -m pytest tests -q`
9. `backend`에서 `python scripts/dump_openapi.py`
10. `frontend`에서 `npm run generate-types`
11. `git diff --exit-code -- backend/openapi.json frontend/src/api/types.ts`
12. `frontend`에서 `npm test`
13. `frontend`에서 `npm run build`

`CLAUDE.md`에는 푸시 전 감사 명령과 CI의 보증 범위, 실제 AI와 PowerPoint가 제외된다는 경계를 추가한다. macOS 전체 설치와 실행 안내는 D2까지 미룬다.

**Step 3: Update the lockfile mechanically**

Run from `frontend` after adding the Node engine:

```text
npm install --package-lock-only
```

Expected: 루트 패키지의 engine 메타데이터만 lockfile에 반영되고 의존성 버전은 바뀌지 않는다.

**Step 4: Run the full local acceptance commands**

Run from repository root:

```text
backend/.venv/Scripts/python.exe scripts/audit_public_repo.py
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
backend/.venv/Scripts/python.exe backend/scripts/dump_openapi.py
npm --prefix frontend run generate-types
git diff --exit-code -- backend/openapi.json frontend/src/api/types.ts
npm --prefix frontend test
npm --prefix frontend run build
git diff --check
```

If the historical Windows `npm --prefix` problem reappears, run the npm commands from `frontend` instead and keep the workflow on per-step working directories. Do not encode a machine-specific absolute Node path.

**Step 5: Commit**

```text
git add .github/workflows/ci.yml .nvmrc frontend/package.json frontend/package-lock.json CLAUDE.md
git commit -m "ci: Windows와 macOS 자동 검증을 추가한다"
```

**실행 중 보정 (2026-09-03, Mac Mini)**: `frontend/package.json` 의 `engines.node` 는 정확 고정(`22.17.1`)이 아니라 하한(`>=22.17.1`)으로 둔다. CI 와 `.nvmrc` 는 22.17.1 을 쓰지만 주 개발 환경인 Mac Mini 는 Node 24.14.1 이라 정확 고정이면 매 설치마다 경고가 난다. 로컬 수용 검증은 fnm 으로 22.17.1 을 따로 설치해 그 버전으로 수행했다(프런트 76건 통과, 빌드 성공). OpenAPI 와 프런트 타입의 무변경 확인은 작업공간이 main 클론의 editable 설치를 빌려 쓰는 동안은 의미가 없어 main 병합 뒤에 수행한다.

**Step 6: Controller review, push, and remote GREEN**

After the task review approves the commit, the controller pushes `codex/phase-5a` and waits for the workflow attached to that exact commit.

Expected remote evidence:

- Windows job: success
- macOS job: success
- Both jobs reference the Task 3 commit SHA

If either job fails, treat it as a Task 3 defect. Resume the same implementer for a minimal fix, then run scoped re-review and push again. Do not mark D1 complete from local tests alone.

---

### Task 4: 과거 이력 감사와 D1 완료 근거 반영

**Files:**

- Modify: `docs/plans/2026-08-27-mvp-roadmap.md`

**Prerequisite:** Task 3의 정확한 commit SHA에서 Windows와 macOS GitHub Actions가 모두 성공해야 한다.

**Step 1: Run the reproducible history audit**

Run from repository root:

```text
backend/.venv/Scripts/python.exe scripts/audit_public_repo.py --history
git log 6de6de0..HEAD --name-status --oneline
```

Expected: 현재와 과거 커밋의 금지 경로 및 명백한 키 패턴이 0건이고, D1에서 새로 추적한 파일 전부가 계획 범위 안이다. 자동 검사는 임의의 일반 텍스트가 기밀인지 판정하지 못하므로 변경 파일의 목적과 내용을 사람이 함께 확인한다.

**Step 2: Record verified facts only**

로드맵 진행 상태에 단계 5A D1 완료 항목을 추가한다.

- 감사 CLI와 Git 규칙
- 로컬 백엔드, 프런트 테스트 수와 빌드 결과
- GitHub Actions 실행 URL과 Windows, macOS 성공 상태
- 과거 Git 이력의 금지 확장자 경로 감사와 명백한 키 패턴 diff 감사 결과
- 실제 AI 로그인, PowerPoint 화면, Mac Mini 새 클론은 D2에 남았다는 경계

테스트 수는 해당 시점의 실제 출력만 기록하고 추정하지 않는다.

**Step 3: Verify documentation and repository state**

```text
git diff --check
backend/.venv/Scripts/python.exe scripts/audit_public_repo.py
backend/.venv/Scripts/python.exe scripts/audit_public_repo.py --history
git status --short --branch
```

Expected: 문서 외 예상하지 못한 변경이 없고 감사기가 통과한다.

**Step 4: Commit and push after review**

```text
git add docs/plans/2026-08-27-mvp-roadmap.md
git commit -m "docs: 단계 5A D1 검증 완료를 기록한다"
```

독립 문서 검토 뒤 `origin/codex/phase-5a`에 푸시한다.

## D1 Completion Gate

- Task 1부터 Task 4까지 각 태스크의 독립 검토가 승인됨
- 공개 저장소 감사 CLI가 현재 추적 파일에서 0건을 반환함
- 과거 Git 이력의 금지 확장자 경로와 명백한 키 패턴 감사가 0건임
- Windows 로컬 전체 백엔드 테스트, 프런트 테스트와 빌드가 성공함
- GitHub Actions의 Windows와 macOS 작업이 동일한 commit SHA에서 성공함
- OpenAPI와 프런트 생성 타입의 diff가 0건임
- D2에서 확인할 Mac Mini 새 클론, 실제 AI 로그인, 폰트 설치와 PowerPoint 표시가 완료로 오기록되지 않음
