# slidecaptain

보고 슬라이드(PPTX) 제작 로컬 웹앱. 핵심 원칙은 "AI는 내용만, 배치는 코드가"이다: AI는 구조화된 콘텐츠까지만 산출하고, 좌표와 글자 크기는 결정론적 레이아웃 엔진이 프리셋에서 계산한다.

## 진본 문서 (작업 시작 전 필독)

- 진행 상태, 아키텍처 결정, 이월 사항의 진본: `docs/plans/2026-08-27-mvp-roadmap.md` (단계 구성, 이월표, 방치 확정 문단까지 이 문서가 관리한다)
- 설계 진본: `docs/specs/2026-08-27-mvp-design.md`
- 단계별 상세 계획서는 착수 시점에 새로 작성한다: 앞 단계에서 확정된 실제 인터페이스를 근거로 쓰기 위해서다 (로드맵 원칙)

## 명령 (Windows 기준)

- 테스트: `backend` 폴더에서 `.venv/Scripts/python.exe -m pytest tests -q` (시스템 파이썬에는 의존성이 없어 그대로 실행하면 수집 오류가 난다)
- 로컬 서버: `backend` 폴더에서 `.venv/Scripts/python.exe -m slidecaptain serve` 실행 후 `http://127.0.0.1:8765/docs`
- CLI 내보내기: `backend` 폴더에서 `.venv/Scripts/python.exe -m slidecaptain export <deck.json>`
- 타입 재생성: `backend`에서 `.venv/Scripts/python.exe scripts/dump_openapi.py` 실행 후 저장소 루트에서 `npm --prefix frontend run generate-types` (최초 1회는 `frontend` 폴더 안에서 `npm install` 선행. 루트에서 `npm --prefix frontend install` 형태는 Windows에서 동작하지 않는다)
- 프런트 테스트: `frontend` 폴더 안에서 `npm test`
- 프런트 개발 서버: `frontend` 폴더 안에서 `npm run dev` (백엔드 `serve`와 병행 실행)
- 화면 빌드: `frontend` 폴더 안에서 `npm run build` (백엔드 `serve`가 빌드된 `dist`를 함께 서빙한다)

## 관례

- TDD: 실패하는 테스트부터. 커밋은 태스크 단위, 한국어 커밋 메시지 (feat/fix/test/docs 접두)
- 작업은 feature 브랜치에서 진행하고 완료 후 main에 머지한다
- 품질 게이트: 계획서 확정 전 적대 리뷰, 태스크마다 독립 리뷰, 브랜치 전체 최종 리뷰 (superpowers 스킬 흐름을 따른다)
- 리뷰와 검증에서 나온 발견은 로드맵의 이월표 또는 방치 확정 문단에 반영한다. 사이드 문서에만 남기지 않는다
- 문서를 정정할 때는 날짜와 사유를 남긴다. 하위 문서가 상위 문서를 출처 표기만 달고 조용히 재정의하는 것을 금지한다 (2026-08-28 가설 리뷰에서 실증된 실패 유형)
- 생성 텍스트에 엠대시(U+2014)와 중점(U+00B7)을 쓰지 않는다
