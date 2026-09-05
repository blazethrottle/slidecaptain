# slidecaptain

보고 슬라이드(PPTX) 제작을 돕는 로컬 웹앱이다.

비개발자가 리서치나 검토 결과를 발표용 덱으로 만드는 과정을 자동화하는 것을 목표로 한다. 반복 제작에서 축적한 방법론과 실패 교훈이 이 앱의 요구사항을 이룬다. 핵심 원칙은 "AI는 내용만, 배치는 코드가"이다: AI는 구조화된 콘텐츠까지만 산출하고, 좌표와 글자 크기는 결정론적 레이아웃 엔진이 프리셋에서 계산해 균일성을 구조적으로 보장한다.

## 실행

- **macOS**: 저장소 루트의 `SlideCaptain실행.command`를 더블클릭한다. 이 창이 서버 창이며, 창을 닫거나 Ctrl+C를 누르면 서버가 멈춘다.
- **Windows**: 저장소 루트의 `SlideCaptain실행.bat`를 더블클릭한다. 별도 서버 창이 뜬다.

두 스크립트 모두 서버가 이미 떠 있으면 새로 켜지 않고 브라우저만 연다. 서버 주소는 `http://127.0.0.1:8765`이며 이 PC에서만 접근할 수 있다. 처음 실행하는 PC라면 먼저 아래 "개발 환경 구성"을 마쳐야 한다.

## 개발 환경 구성

### macOS

저장소를 iCloud와 동기화되는 폴더(`~/Documents`, `~/Desktop` 등) 밖에 둔다. 예를 들어 `~/Projects/`에 둔다. iCloud 폴더 안에 두면 가상환경의 `.pth` 파일에 hidden 플래그가 붙어 Python 3.13이 editable 설치를 조용히 무시한다(2026-09-02 실측).

uv와 fnm이 없으면 먼저 설치한다.
```
brew install uv fnm
```

`backend` 폴더에서 Python 3.13 가상환경을 만든다.
```
uv venv --python 3.13
```

같은 폴더에서 백엔드를 의존성과 함께 설치한다. uv가 만든 가상환경에는 pip가 없어 `uv pip`를 쓴다.
```
uv pip install --python .venv/bin/python -e ".[dev]"
```

`.nvmrc`가 지정한 Node 버전을 설치하고 사용한다.
```
fnm install 22.17.1
fnm use 22.17.1
```

fnm을 처음 설치했다면 셸 설정 파일(`~/.zshrc`)에 `eval "$(fnm env --use-on-cd)"` 한 줄을 추가하고 터미널을 새로 연 뒤 `node -v`가 v22.17.1인지 확인한다. 이 연동이 없으면 `fnm use`는 성공 메시지를 내고도 Node 버전을 바꾸지 않는다(2026-09-05 실측).

`frontend` 폴더에서 화면 의존성을 설치하고 빌드한다. 빌드된 화면을 서버가 함께 제공한다.
```
npm ci
npm run build
```

### Windows

`backend` 폴더에서 가상환경을 만들고 의존성과 함께 설치한다(`python --version`이 3.13 이상이어야 한다).
```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

`frontend` 폴더에서 화면 의존성을 설치하고 빌드한다(최초 1회).
```
npm install
npm run build
```

## 개발 명령

- 테스트: `backend` 폴더에서 실행한다. macOS `.venv/bin/python -m pytest tests -q` (Windows `.venv\Scripts\python.exe -m pytest tests -q`)
- 로컬 서버: `backend` 폴더에서 실행한 뒤 `http://127.0.0.1:8765/docs`를 연다. macOS `.venv/bin/python -m slidecaptain serve` (Windows `.venv\Scripts\python.exe -m slidecaptain serve`)
- CLI 내보내기: `backend` 폴더에서 실행한다. macOS `.venv/bin/python -m slidecaptain export <deck.json>` (Windows `.venv\Scripts\python.exe -m slidecaptain export <deck.json>`)
- 타입 재생성: `backend`에서 OpenAPI 스키마를 뽑고 `frontend`에서 타입으로 바꾼다. macOS `.venv/bin/python scripts/dump_openapi.py` 뒤 `npm run generate-types` (Windows `.venv\Scripts\python.exe scripts\dump_openapi.py`)
- 프런트 테스트: `frontend` 폴더에서 `npm test`
- 프런트 개발 서버: `frontend` 폴더에서 `npm run dev` (백엔드 `serve`와 병행 실행)
- 화면 빌드: `frontend` 폴더에서 `npm run build`

## 주의 (macOS)

- 클론을 iCloud와 동기화되는 폴더(`~/Documents`, `~/Desktop` 등)에 두지 않는다. `.pth` 파일에 hidden 플래그가 붙어 editable 설치가 조용히 무시된다.
- uv가 만든 가상환경에는 pip가 없다. 패키지를 설치하거나 갱신할 때는 `pip` 대신 `uv pip`를 쓴다.
- git worktree(`~/Projects/slidecaptain-5a` 등)에서 백엔드 테스트를 돌릴 때는 `PYTHONPATH=<worktree>/backend`를 앞에 붙인다. main 클론의 가상환경을 빌려 쓰면 editable 설치가 main 클론 패키지를 가리켜 worktree 코드가 검증되지 않는다.

## 폰트

첫 `serve` 실행이 Noto Sans KR 두 파일(Regular, Bold)을 사용자 폰트 폴더(macOS `~/Library/Fonts`, Windows 사용자 폰트 폴더)에 자동으로 설치한다. 설치에 실패하면 안내 문구와 함께 수동 설치 파일 경로(`backend/slidecaptain/fonts/assets/`)를 출력한다. 화면 폭 계산은 폰트가 없어도 번들 수치로 동작한다.

## 데이터 폴더

기본 데이터 폴더는 `~/slidecaptain-projects`이며 `serve --data-dir <경로>`로 바꿀 수 있다. 프로젝트마다 `deck.json`, `uploads/`, `sources/`, `snapshots/`, `exports/`, `ai-usage.jsonl`(AI 사용량 기록, 내용은 담지 않는다) 폴더와 파일이 생긴다.

## 검증과 CI

- 백엔드 테스트, 프런트 테스트, 타입 재생성 무변경 확인은 위 "개발 명령"과 같다.
- 푸시 전에 공개 저장소 감사기를 돌린다. 이 저장소는 공개 GitHub에 올라가므로 회사 자료, 오피스 파일, 인증정보가 추적되면 안 된다. 저장소 루트에서 macOS `backend/.venv/bin/python scripts/audit_public_repo.py` (Windows `backend\.venv\Scripts\python.exe scripts\audit_public_repo.py`). 과거 이력까지 보려면 `--history`를 붙인다.
- `.github/workflows/ci.yml`이 push와 pull request마다 Windows와 macOS에서 같은 순서로 실행한다: 줄바꿈 검사, 감사기, 백엔드 테스트, OpenAPI와 타입 재생성 뒤 무변경 확인, 프런트 테스트, 화면 빌드.
- CI가 보증하지 않는 것: 실제 AI 로그인과 호출(본인 Claude 구독으로 로그인해 호출하며, 첫 호출 전 전송 범위 고지 대화 상자가 뜨고 호출별 사용량이 화면에 표시된다), PowerPoint 표시, 폰트 설치 실증. 이것들은 실기기 관통의 몫이다.

## 화면을 갱신할 때 (배포 순서)

서버 종료 → `frontend` 폴더에서 `npm run build` → 실행 스크립트(`SlideCaptain실행.command` 또는 `SlideCaptain실행.bat`)로 재실행 → 브라우저 새로고침. 서버를 먼저 끄지 않으면 옛 서버와 새 화면이 섞여 저장 유실 창이 생길 수 있다(로드맵 실측 기록).

## 상태 (2026-09-05 기준)

단계 1(결정론 코어), 단계 2(저장소와 API 서버), 단계 3(AI 파이프라인), 단계 4(편집 화면)를 완료했다. 실전 파일럿에서 나온 소형 개선 묶음 2건과 Critical 소형 수정 묶음, 저장 안전성 소형 수정 묶음도 완료했다. 단계 5A(로컬 안전성과 이식성)는 D1(양 OS CI와 공개 저장소 경계), A(저장과 로컬 API 안전성), B(XLSX 파일럿 입력과 데이터 전송 고지), C(AI 사용량과 원가 근거)를 완료했고, D2(Mac Mini 개발 전환 마무리)를 진행하고 있다. 그 뒤 단계 5B(반복 가능한 로컬 파일럿)로 이어간다.

진행 상태의 진본은 [구현 로드맵](docs/plans/2026-08-27-mvp-roadmap.md)의 "진행 상태" 절이다.

## 문서

- [배경 히스토리](docs/background/methodology-history.md): 본격 개발에 앞서, 실제 덱을 반복 제작하며 정리한 방법론 진화와 기술 교훈. 요구사항의 원천이다.
- [MVP 설계서](docs/specs/2026-08-27-mvp-design.md): 프로덕트 정의, 아키텍처, 데이터 모델, AI 파이프라인, 오버플로 정책, MVP 범위.
- [구현 로드맵](docs/plans/2026-08-27-mvp-roadmap.md): MVP를 5단계로 분해한 구현 순서와 단계 공통 아키텍처 결정, 기술 사실 검증 결과, 이월 사항. **진행 상태의 진본은 이 문서의 "진행 상태" 절이다.**
- [단계 1 상세 계획](docs/plans/2026-08-27-phase1-core-pipeline.md): 결정론 코어(deck.json → PPTX)의 태스크별 TDD 구현 계획.
- [단계 2 상세 계획](docs/plans/2026-08-28-phase2-storage-api.md): 저장소, FastAPI 서버, 타입 공유 파이프라인의 구현 계획.
- [단계 3 상세 계획](docs/plans/2026-08-28-phase3-ai-pipeline.md): 구조안과 장별 생성, 수동 축약 API, 검증 게이트의 구현 계획.
- [단계 4 상세 계획](docs/plans/2026-08-29-phase4-editor.md): 편집 화면(React)의 구현 계획.
- [단계 5A 마스터 플랜](docs/plans/2026-09-01-phase5a-master-plan.md): 로컬 안전성과 이식성 묶음(D1, A, B, C, D2)의 범위와 완료 관문.
- [파일럿 관찰지](docs/pilot/2026-08-31-파일럿-관찰지.md): 실전 파일럿 실행에서 얻은 관찰 기록.

묶음별 상세 계획서 전체는 로드맵의 단계 표와 진행 상태 절에서 찾는다.
