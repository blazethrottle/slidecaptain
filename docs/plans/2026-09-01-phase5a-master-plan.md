# 단계 5A 로컬 안전성과 이식성 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement each bundle task-by-task. Each bundle receives its own detailed plan, failing tests first, a task review after every commit, and a whole-branch review before integration.

**Goal:** 현재 1인 로컬 앱의 데이터 안전성과 실제 파일럿 완주 능력을 높이고, Mac Mini를 주 개발 환경으로 전환하면서 상업화 선택지를 막지 않는 계약과 검증 기반을 만든다.

**Architecture:** 문서 생성 코어는 그대로 유지하고 로컬 실행 프로필에서만 필요한 저장, 요청 보호, 파일 입력, AI 연결, OS 실행 경로를 교체 가능한 연결 계층에서 보강한다. 인증, 결제, 다중 사용자 저장소, 앱 마켓 포장은 외부 고객과 결제 의사가 검증될 때까지 구현하지 않는다.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, python-pptx 1.0.2, React 19, TypeScript, Vitest, pytest, GitHub Actions, macOS, Windows

**Spec:** `docs/specs/2026-08-27-mvp-design.md`의 2.5절, 2.6절, 9.1절과 `docs/plans/2026-08-27-mvp-roadmap.md`의 단계 5A 확정 범위

## Global Constraints

- 현재 제품은 1인 로컬 앱이며 서버는 `127.0.0.1`이라는 이 PC 전용 주소에서만 연다.
- 현재 로컬 API는 LAN 또는 인터넷에 공개하지 않는다.
- 문서 생성 코어는 인증, 결제, 특정 저장 위치, 특정 AI 제공자에 의존하지 않는다.
- 프로젝트 파일은 로컬에 저장되지만 AI 생성에 필요한 내용은 제공자에게 전송된다는 사실을 숨기지 않는다.
- 구조안 생성, 장별 생성과 재생성, 축약, 형식 재시도를 포함한 모든 AI 요청은 공통 전송 확인 관문을 통과한다.
- 본인 Claude 구독 프로바이더는 소유자 로컬 파일럿에서만 사용한다.
- 회사 원자료, 인증정보, 생성 PPTX, 로컬 프로젝트 데이터, 의존성 폴더, 임시 리뷰 기록은 공개 GitHub에 올리지 않는다.
- 모든 푸시 전에 Git이 추적하는 파일을 감사하고, XLSX를 포함한 자동 테스트 자료는 새로 만든 비기밀 픽스처만 사용한다.
- Mac Mini를 주 개발 환경으로 사용하고 Windows와 macOS의 자동 테스트를 유지한다.
- 생산 코드 변경은 실패하는 테스트를 먼저 확인한 뒤 최소 구현으로 통과시킨다.
- 생성 텍스트에는 엠대시(U+2014)와 중점(U+00B7)을 사용하지 않는다.
- 각 태스크는 한국어 커밋 메시지로 기록하고 검토가 끝난 커밋을 `origin/codex/phase-5a`에 푸시한다.

---

## 실행 순서

### 묶음 D1: 양 OS 자동 검증과 공개 저장소 경계

**산출물:** GitHub가 제공하는 Windows와 macOS 테스트 컴퓨터에서 같은 검증을 실행하는 GitHub Actions, 운영체제별 줄바꿈 규칙, macOS 임시 파일과 로컬 산출물 무시 규칙, 추적 파일 감사 명령.

**상세 계획 작성 입력:** `.gitignore`, `.gitattributes`, 추적 파일 목록, `backend/pyproject.toml`, `frontend/package.json`, OpenAPI와 프런트 타입 생성 명령, 현재 Python과 Node 버전.

**완료 관문:** Windows 로컬 기준 테스트와 빌드가 유지되고, 원격 Windows와 macOS 작업이 모두 성공한다. 추적 파일 감사에서 회사 원자료, 인증정보, 생성 산출물, 로컬 프로젝트 데이터, 의존성, 임시 리뷰 기록이 0건이어야 한다. 실제 AI 로그인과 PowerPoint 화면 검증은 자동 검증 범위가 아님을 명시한다.

### 묶음 A: 저장과 로컬 API 안전성

**산출물:** 고유 임시 파일과 프로젝트별 잠금, 내용 ETag(저장본 내용으로 만든 최신본 확인표) 기반 충돌 거절, 프런트 저장 직렬화와 재시도, 화면 이탈 게이트, 로컬 상태 변경 요청 보호, 동시 내보내기 번호 보호, 프리셋과 표 레이아웃 안전 검증.

**상세 계획 작성 입력:** `backend/slidecaptain/storage/file_store.py`, `backend/slidecaptain/server/app.py`, `backend/slidecaptain/export/exporter.py`, `frontend/src/api/client.ts`, `frontend/src/state/useDeckEditor.ts`, `frontend/src/screens/ProjectView.tsx`와 대응 테스트.

**완료 관문:** 동시 저장과 오래된 탭 재현 테스트가 데이터 유실 없이 통과하고, 저장 실패 시 탭 이동과 목록 복귀와 내보내기가 중단되며, 다른 Origin(요청을 보낸 웹페이지 주소 출처)의 상태 변경 요청이 거절된다.

### 묶음 B: XLSX 파일럿 입력과 데이터 전송 고지

**산출물:** `uploads/`의 XLSX 원본과 `sources/`의 AI 입력용 UTF-8 추출 자료 분리, 시트와 셀 출처, 압축과 셀과 문자 상한, 수식과 저장된 계산값과 링크의 한계 표시, 업로드 중 화면 이동 방지, 브라우저 탭의 첫 AI 호출 전 전송 확인.

**상세 계획 작성 입력:** 실제 파일럿 원본의 형식은 내용 없이 시트 수와 파일 크기만 확인하고, 구현과 테스트에는 새로 만든 비기밀 XLSX 픽스처를 사용한다. `backend/slidecaptain/server/app.py`, `backend/slidecaptain/storage/file_store.py`, `frontend/src/screens/ProjectView.tsx`, `frontend/src/screens/SourcesScreen.tsx`, `frontend/src/screens/StructureScreen.tsx`, `frontend/src/editor/GeneratePanel.tsx`와 공통 API 클라이언트를 기준으로 한다.

**완료 관문:** 원본 회사 파일을 저장소에 넣지 않고 비기밀 픽스처로 자동 테스트가 통과하며, 실제 파일럿 XLSX가 로컬에서 추출된다. 구조안 생성, 장별 생성과 재생성, 사용자 축약, 형식 재시도와 자동 축약을 포함한 모든 AI 호출이 공통 관문을 통과하고, 탭의 첫 호출 전에 취소 가능한 고지가 표시된다.

### 묶음 C: AI 사용량과 원가 근거

**산출물:** 원시 AI 호출의 실제 모델, 입력과 출력과 캐시 토큰, 처리 시간, 호출 수, SDK 제공 비용값을 선택적으로 수집하고 생성 작업 단위로 합산해 API에 반환하며 프로젝트 로컬 기록에 내용 없이 누적한다.

**상세 계획 작성 입력:** `backend/slidecaptain/pipeline/provider.py`, `backend/slidecaptain/pipeline/subscription.py`, `backend/slidecaptain/pipeline/service.py`, 생성 API 응답 모델과 화면 표시를 기준으로 한다. 고정된 `claude-agent-sdk==0.2.145`의 `ResultMessage` 필드를 계약 근거로 사용한다.

**완료 관문:** 형식 재시도와 자동 축약을 포함한 호출 수와 사용량이 빠짐없이 합산되고, 비용값이 없을 때 숫자를 만들지 않으며, 로컬 기록에 프롬프트와 자료와 생성 원문이 포함되지 않는다.

### 묶음 D2: Mac Mini 개발 전환 마무리

**산출물:** Mac Mini에서 저장소를 새로 받아 개발 환경을 구성하고 앱을 실행하는 문서와 실행 스크립트, 플랫폼별 폰트 안내, README와 개발 명령 최신화, Windows와 Mac Mini 실기기 관통 기록.

**상세 계획 작성 입력:** A부터 C까지 확정된 최종 설치와 테스트 명령, `CLAUDE.md`, `README.md`, `SlideCaptain실행.bat`, `backend/slidecaptain/__main__.py`, `backend/slidecaptain/fonts/installer.py`, 묶음 D1의 GitHub Actions 결과.

**완료 관문:** Mac Mini 새 클론에서 환경 구성, 서버 실행, 비기밀 샘플과 XLSX 업로드, AI 전송 확인, 저장, PPTX 내보내기와 재열기가 성공한다. Windows에서도 같은 흐름이 유지된다. CI로 확인한 항목과 실기기에서만 확인한 AI 로그인, 폰트 설치, PowerPoint 표시를 구분해 기록한다.

### 단계 5A 통합 검증

**검증 명령:**

```text
backend/.venv/bin/python -m pytest backend/tests -q              # macOS
backend/.venv/Scripts/python.exe -m pytest backend/tests -q      # Windows
npm test                                                         # frontend 폴더
npm run build                                                    # frontend 폴더
```

Windows 로컬에서는 `.venv/Scripts/python.exe`를 사용하고, GitHub Actions에서는 운영체제별 `python` 실행 파일을 사용한다.

자동 검증과 실기기 검증은 다음처럼 나눈다.

| 검증 | Windows | macOS | 자동 검증으로 대체 가능 여부 |
|---|---|---|---|
| 백엔드 전체 테스트, 프런트 전체 테스트와 빌드, OpenAPI 타입 일치, 공개 저장소 추적 파일 감사 | 로컬과 GitHub Actions | GitHub Actions | 가능 |
| 새 클론에서 개발 환경 구성과 실행 스크립트로 서버 시작 | Windows 실기기 | Mac Mini | 불가 |
| 비기밀 텍스트와 XLSX 업로드, 첫 AI 호출 전 취소와 확인 | Windows 실기기 | Mac Mini | 불가 |
| AI 구조안과 장 생성, 저장, PPTX 내보내기와 코드 재열기 | Windows 실기기 | Mac Mini | AI 로그인은 불가, 나머지는 일부 자동화 가능 |
| PowerPoint 실제 표시와 폰트 설치 반영 | Windows 실기기 | Mac Mini | 불가 |

최종 관통은 새 비기밀 프로젝트 생성, 텍스트와 XLSX 업로드, AI 전송 확인, 구조안과 장 생성, 덱 편집과 저장, PPTX 내보내기, 코드 재열기, PowerPoint 표시 순서로 수행한다.

> 2026-09-05 정정(사용자 결정, D2 계획서): 위 표의 Windows 열 "Windows 실기기" 와 "불가" 는 D1 과 D2 에서 CI windows-latest 성공으로 갈음했다(물리 Windows 관통 없음). 실기기 확인은 Mac Mini 에서만 하며, 구조안과 장 생성의 실호출은 승인된 1회(구조안 생성)로 한정하고 장 생성 승인 루프는 실행하지 않는다.

## 5A에서 만들지 않는 것

- 사용자 계정, 팀, 작업공간, 역할과 권한
- 결제, 요금제, 구독 한도, 세금과 환불
- 다중 사용자 데이터베이스와 객체 저장소
- LAN 또는 인터넷 공개 서버
- 앱 마켓 포장, 코드 서명, 자동 업데이트
- PDF, Word, OCR 입력
- macOS PowerPoint 자동 캡처와 화면 비교
- 원격 사용 분석 서버

## 이 계획이 틀렸을 가능성

- 외부 검증에서 팀 협업과 중앙 관리가 구매의 핵심으로 확인되면 유료 로컬 앱보다 관리형 서비스가 먼저 필요할 수 있다.
- Mac Mini에서 실제 PowerPoint 렌더링이 Windows와 크게 다르면 코어 테스트 통과만으로 산출물 품질을 보증할 수 없다. 이 경우 단계 5B 전에 macOS 실제 화면 검증을 앞당긴다.
- XLSX 원본의 수식 캐시가 오래됐거나 비어 있으면 추출값을 사실로 사용할 수 없다. 앱은 수식과 저장값을 구분하고 확인 경로를 표시해야 한다.
- 본인 구독 프로바이더의 정책이 바뀌면 로컬 파일럿 AI 연결도 교체해야 할 수 있다. 공식 정책을 배포 관문뿐 아니라 파일럿 재개 전에도 확인한다.
