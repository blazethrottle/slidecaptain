# slidecaptain

보고 슬라이드(PPTX) 제작을 돕는 로컬 웹앱. 결정론 코어(단계 1), 저장소 + API 서버(단계 2), AI 파이프라인(단계 3: 구조안 생성과 장별 생성, 수동 축약 API, 검증 게이트 3종, 본인 구독 호출)이 구현되어 있다.

비개발자가 리서치나 검토 결과를 발표용 덱으로 만드는 과정을 자동화하는 것을 목표로 한다. 반복 제작에서 축적한 방법론과 실패 교훈이 이 앱의 요구사항을 이룬다. 핵심 원칙은 "AI는 내용만, 배치는 코드가"이다: AI는 구조화된 콘텐츠까지만 산출하고, 좌표와 폰트는 결정론적 레이아웃 엔진이 프리셋에서 계산해 균일성을 구조적으로 보장한다.

## 문서

- [배경 히스토리](docs/background/methodology-history.md): 본격 개발에 앞서, 실제 덱을 반복 제작하며 정리한 방법론 진화와 기술 교훈. 요구사항의 원천이다.
- [MVP 설계서](docs/specs/2026-08-27-mvp-design.md): 프로덕트 정의, 아키텍처, 데이터 모델, AI 파이프라인, 오버플로 정책, MVP 범위.
- [구현 로드맵](docs/plans/2026-08-27-mvp-roadmap.md): MVP를 5단계로 분해한 구현 순서와 단계 공통 아키텍처 결정, 기술 사실 검증 결과, 이월 사항. **진행 상태의 진본은 이 문서의 "진행 상태" 절이다.**
- [단계 1 상세 계획](docs/plans/2026-08-27-phase1-core-pipeline.md): 결정론 코어(deck.json → PPTX)의 태스크별 TDD 구현 계획.
- [단계 2 상세 계획](docs/plans/2026-08-28-phase2-storage-api.md): 저장소, FastAPI 서버, 타입 공유 파이프라인의 구현 계획.

## 상태 (2026-08-28 기준)

- [x] 단계 1: 결정론 코어 (deck.json → 규칙 준수 PPTX, CLI)
- [x] 단계 2: 저장소 + API 서버 (프로젝트 폴더, FastAPI, OpenAPI → TS 타입 파이프라인)
- [ ] 단계 3: AI 파이프라인 (다음 작업. 첫 태스크 = Agent SDK 구독 로그인 실증)
- [ ] 단계 4: 편집 화면 (React)
- [ ] 단계 5: 마무리 통합

## 실행

- 테스트: `backend` 폴더에서 `.venv/Scripts/python.exe -m pytest tests -q`
- 로컬 서버: `backend` 폴더에서 `.venv/Scripts/python.exe -m slidecaptain serve` 실행 후 `http://127.0.0.1:8765/docs`
