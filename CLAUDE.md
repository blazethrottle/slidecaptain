# slidecaptain

보고 슬라이드(PPTX) 제작 로컬 웹앱. 핵심 원칙은 "AI는 보고 논리와 표현을 설계하고, 코드는 배치를 계산하며, 완성본 검수로 제출 가능 여부를 판단한다"이다. 2026-09-12 사용자 승인으로 품질 중심 설계를 채택했다. 생성 성공, 템플릿 개수, 테스트 개수를 보고서 품질 통과로 대신하지 않는다.

## 진본 문서 (작업 시작 전 필독)

- 2026-10-02 Windows PowerPoint 검수 재개: `docs/qa/2026-10-02-windows-powerpoint-guide.md`. 현재 개발 브랜치 `codex/phase-5b`에서 `Windows검수준비.bat`로 합성 5개/15페이지와 JSON 피드백 양식을 준비한다. 기존 회사 프로젝트·인증정보·미커밋 변경을 보존하고 별도 포트 8870/검수 폴더를 사용한다. 이번 준비는 AI 호출 0회이며 사람 피드백을 서명 검수나 제출 승인으로 자동 승격하지 않는다.

- 진행 상태, 아키텍처 결정, 이월 사항의 진본: `docs/plans/2026-08-27-mvp-roadmap.md` (단계 구성, 이월표, 방치 확정 문단까지 이 문서가 관리한다)
- 설계 진본: `docs/specs/2026-08-27-mvp-design.md`
- 품질 중심 제품과 서비스 요구: `docs/specs/2026-09-12-quality-first-product.md`. 기존 설계서에 변경 범위와 우선순위를 반영했다.
- 기술 결정: `docs/architecture/2026-09-12-quality-pipeline.md`. 진행 순서: `docs/plans/2026-09-12-quality-first-rebuild.md`. Q1b의 이력 조회와 Q2d의 계산 문구 대조, Q3a의 독립 도식 계약 다음으로 Q3b의 결정론 배치와 공통 렌더, 프로젝트 의미 입력 저장/미리보기, 직접 작성/수정 UI와 기존 StoryPlan 연결 최소 계약까지 로컬 검증했다. 2026-09-28 Sonnet에 이어 2026-09-29 LUNA도 합성 3장 사례의 장 생성/편집 보존 재작성/초안 PPTX를 완료했다. LUNA 재작성은 형식 재시도 1회를 사용했다. 실제 PowerPoint와 독자 품질 평가는 미수행이다.
- 2026-09-30 현재 상태: `docs/plans/2026-09-30-remaining-batch.md`. DB-6/7, 명시적 단위 환산, Q2f 비교/요약 의심 문구 휴리스틱, 근거 연결 native 막대/열 차트와 부분 강조, 상한 있는 계획 수정 후보, 보호된 문서 전체 교체/근거 이전/기존 도식 AI 교체를 구현했다. 휴리스틱의 `semantic_status=not_run`은 유지하며 의미 AI 검수 통과가 아니다. Q4b 생산 provenance/실제 렌더 어댑터/서명 receipt 검증/동일 바이트 게시 경로는 구현됐지만 Windows·목표 PowerPoint·실제 독립 서명·사람 판정은 미실행이다. Q5 도구와 단일 페이지 3개 합성 사례 측정도 전체 품질 수용이 아니다. 아래 날짜별 인계는 당시 결과이며 최신 미완료 경계는 일괄 기록을 따른다.
- 2026-09-29 개발 인계: `docs/handoffs/2026-09-29-q4a-review-records-handoff.md`. 내보낸 파일의 수동 검수 기록, 항목별 최신 판정과 입력/출력 변경 후 현재성 대조를 구현했다. 명시적 ETag와 fingerprint/PPTX 해시로 저장을 검증하고 충돌/이탈/내보내기 대기 중 폼을 보호한다. 수동 통과는 독립 검수나 제출본 승인이 아니다. 2026-09-30 별도 Q4b 관문을 구현했지만 실제 렌더/서명/현재성 증거가 없으면 제출 게시를 계속 차단한다. 전체 백엔드 1,772개 통과/Windows 전용 1개 미실행, 프런트 463개, 독립 리뷰와 합성 HTTP/Chrome QA를 완료했다. 새 도식 AI 후보는 `docs/handoffs/2026-09-29-diagram-ai-draft-handoff.md`, 실제 LUNA 재작성은 `docs/handoffs/2026-09-29-story-rewrite-edits-handoff.md`를 따른다. 이 인계 당시 실제 AI 호출은 0회였고 기존 승인 5회와 추가 3회는 모두 소진했다. 2026-09-30에는 새 승인에 따라 root만 LUNA `gpt-6-luna` 합성 입력을 12/12회(생성 9회+분리된 검토 3회) 실행했고 실패/재시도 0회, 비용 null이다. 단일 페이지 3사례에서 개선 우세는 입증하지 못했다. 구현자/독립 검토자의 실제 호출은 0회다. 실패와 형식 재시도도 상한에 포함하며 자동 제공자 전환은 없다. 실제 렌더/독립 검수/제출본 관문은 Q4b이며 PowerPoint와 독자 품질은 미검증이다. 직접 모델 선택과 사용량 결측의 2026-09-28 인계도 유지한다.
- AI 연결 인계: `docs/handoffs/2026-09-13-ai-connections-handoff.md`. Claude/ChatGPT 연결 화면과 생성 어댑터, 공식 로그인 시작과 취소, 모델 선택을 구현했다. 2026-09-28 사용자가 앱 전용 Codex 본인 인증을 완료했고 두 제공자의 장 생성을 실측했다. 현재 성공/미완료와 호출 예산은 위 최신 인계를 따른다. 연결 작업 당시의 품질 인계는 `docs/handoffs/2026-09-13-q2c-derived-values-handoff.md`였으며, 이후 품질 구현 상태는 위 최신 품질 인계와 로드맵을 따른다. 새 세션에서는 인계와 해당 태스크의 관련 파일만 읽고, 이전 조사 전체를 반복하지 않는다.
- 단계별 상세 계획서는 착수 시점에 새로 작성한다: 앞 단계에서 확정된 실제 인터페이스를 근거로 쓰기 위해서다 (로드맵 원칙)

## 명령 (macOS 기준, Windows 병기)

- 실행 스크립트: 저장소 루트의 `SlideCaptain실행.command`(macOS, 더블클릭) 또는 `SlideCaptain실행.bat`(Windows, 더블클릭). 서버를 켜고 브라우저를 연다.
- 테스트: `backend` 폴더에서 `.venv/bin/python -m pytest tests -q`(Windows `.venv/Scripts/python.exe -m pytest tests -q`. 시스템 파이썬에는 의존성이 없어 그대로 실행하면 수집 오류가 난다)
- 로컬 서버: `backend` 폴더에서 `.venv/bin/python -m slidecaptain serve`(Windows `.venv/Scripts/python.exe -m slidecaptain serve`) 실행 후 `http://127.0.0.1:8765/docs`
- CLI 내보내기: `backend` 폴더에서 `.venv/bin/python -m slidecaptain export <deck.json>`(Windows `.venv/Scripts/python.exe -m slidecaptain export <deck.json>`)
- 타입 재생성: `backend`에서 `.venv/bin/python scripts/dump_openapi.py`(Windows `.venv/Scripts/python.exe scripts/dump_openapi.py`) 실행 후 저장소 루트에서 `npm --prefix frontend run generate-types` (최초 1회는 `frontend` 폴더 안에서 `npm install` 선행. 루트에서 `npm --prefix frontend install` 형태는 Windows에서 동작하지 않는다)
- Windows 전용 참고(2026-08-31 해소): 종전에는 기본 Node가 32비트라 vite가 구동되지 않아 PATH 우회가 필요했으나, nvm4w의 v22.17.1 폴더를 64비트 배포본으로 교체해 기본 Node가 64비트가 되었다(우회 불필요). 만약 다시 32비트로 표류하면(`node -p process.arch`가 ia32) 예비본 `C:\Users\<사용자명>\.claude\tools\node64\node-v22.17.1-win-x64`를 PATH 앞에 두면 된다
- 프런트 테스트: `frontend` 폴더 안에서 `npm test`
- 프런트 개발 서버: `frontend` 폴더 안에서 `npm run dev` (백엔드 `serve`와 병행 실행)
- 화면 빌드: `frontend` 폴더 안에서 `npm run build` (백엔드 `serve`가 빌드된 `dist`를 함께 서빙한다)

## 푸시 전 검증과 CI (2026-09-03 단계 5A D1)

- 푸시 전에 공개 저장소 감사기를 돌린다: 저장소 루트에서 `backend/.venv/bin/python scripts/audit_public_repo.py` (Windows 는 `backend\.venv\Scripts\python.exe`). 과거 이력까지 보려면 `--history` 를 붙인다. 발견 0건이 종료 코드 0 이다. 이 저장소는 공개 GitHub 에 올라가므로 회사 자료, 오피스 파일, 인증정보가 추적되면 안 된다 (규칙은 `.gitignore` 와 감사기, 검사는 `backend/tests/test_repo_metadata.py`)
- `.github/workflows/ci.yml` 이 push 와 pull request 마다 Windows 와 macOS 에서 같은 순서로 실행한다: 체크아웃 줄바꿈 바이트 검사(배치 파일은 CRLF, 셸 픽스처는 LF), 감사기, 백엔드 전체 테스트, OpenAPI 와 프런트 타입 재생성 뒤 생성 파일 무변경 확인, 프런트 테스트, 화면 빌드. Python 3.13, Node 는 `.nvmrc` 의 22.17.1 을 쓴다
- CI 가 보증하지 않는 것: 실제 AI 로그인과 호출, PowerPoint 표시와 렌더 검증, 폰트 설치 실증. 이것들은 실기기 관통의 몫이다

## 관례

- 2026-09-30 게시 안전성: 기본 exporter도 no-follow/regular-file/고정 핸들 잠금을 사용하고 게시 대상 identity/hash와 디렉터리를 다시 검사한다. 비공개 `.slidecaptain-export-*` staging은 경로 교체 중 제3파일 삭제를 피하려고 보존한다. 자동 cleanup은 없고 저장 공간이 누적된다. 이 한계를 숨기거나 경로 기반 일괄 삭제로 바꾸지 않는다. Windows 실기기 통과를 macOS 테스트로 주장하지 않는다.

- TDD: 실패하는 테스트부터. 커밋은 태스크 단위, 한국어 커밋 메시지 (feat/fix/test/docs 접두)
- 작업은 feature 브랜치에서 진행하고 완료 후 main에 머지한다
- 품질 게이트: 계획서 확정 전 적대 리뷰, 태스크마다 독립 리뷰, 브랜치 전체 최종 리뷰 (superpowers 스킬 흐름을 따른다)
- 리뷰와 검증에서 나온 발견은 로드맵의 이월표 또는 방치 확정 문단에 반영한다. 사이드 문서에만 남기지 않는다
- 문서를 정정할 때는 날짜와 사유를 남긴다. 하위 문서가 상위 문서를 출처 표기만 달고 조용히 재정의하는 것을 금지한다 (2026-08-28 가설 리뷰에서 실증된 실패 유형)
- 생성 텍스트에 엠대시(U+2014)와 중점(U+00B7)을 쓰지 않는다
- 상태 변경 API(POST, PUT, DELETE)는 `X-Requested-With: SlideCaptain` 헤더를 요구한다. 새 라우트와 새 클라이언트 호출은 이 규약을 따르고, 백엔드 API 테스트는 `backend/tests/conftest.py` 의 `client` 픽스처(기본 헤더 포함)를 쓴다 (2026-09-04 단계 5A A)
- AI 생성 라우트(구조안, 장 생성, 축약)는 `X-AI-Consent: SlideCaptain` 헤더를 요구한다(없으면 428). 새 생성 라우트와 클라이언트 호출은 `frontend/src/api/aiGate.ts` 공통 관문을 지나고, 생성 라우트 테스트는 이 헤더를 준다 (2026-09-04 단계 5A B)
- 생성 결과 모델(`StructureResult`, `ChapterResult`)에 필드를 더하면 같은 커밋에서 OpenAPI 와 프런트 타입을 재생성하고 프런트 테스트의 결과 목(`frontend/src/test/usage.ts` 의 `emptyUsage()` 같은 공용 helper)을 함께 갱신한다. `backend/tests/test_openapi.py` 가 스키마 동기화를 강제하므로 뒤 태스크로 미룰 수 없다 (2026-09-05 단계 5A C. B2 와 C2 에서 두 번 겪은 파급)
- worktree(`~/Projects/slidecaptain-5a` 등)에서 백엔드 테스트를 돌릴 때는 `PYTHONPATH=<worktree>/backend` 를 앞에 붙인다. main 클론의 가상환경을 빌려 쓰면 editable 설치가 main 클론 패키지를 가리켜 worktree 코드가 검증되지 않는다 (2026-09-04 실측)
