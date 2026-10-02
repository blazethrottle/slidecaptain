# Q2a 첫 태스크 종료 및 다음 세션 인계

작성: 2026-09-12. 저장소는 `~/Projects/slidecaptain`이다.

**종료 지점: 사용자가 요청한 Q2 첫 태스크의 구현, 로컬 테스트와 빌드를 마쳤다. Q1b, Q2 다음 단위와 Q3~Q5는 시작하지 않고 여기서 멈춘다.**

## 목적과 승인 범위

[Q1a 인계](2026-09-12-q1a-validation-handoff.md)가 권장한 보고 질문과 주장별 근거 중심의 전체 보고 계획 최소 경로를 구현했다. 회사 비교 자료 대신 비기밀 합성 보고서를 사용했다. 실제 AI 호출, 비용/자료 전송, 앱 재시작, 배포, 커밋/푸시는 수행하지 않았다. 자동화 검사 통과를 독자의 이해도나 보고서 품질 개선으로 해석하지 않는다.

시작 시 브랜치는 `codex/phase-5b`, HEAD는 `acff346`이었고 원격은 `https://github.com/blazethrottle/slidecaptain.git`이었다. Q1a를 포함한 기존 미커밋/미추적 변경이 있었고 스테이징은 비어 있었다. 그 상태를 보존하며 같은 작업 트리에서 진행했다. 작업 트리가 깨끗하지 않아 pull/브랜치 전환/머지를 하지 않았다. 다음 세션도 Git 상태를 먼저 다시 확인한다.

## 완료한 동작

1. 구조안 화면에 선택적 '보고 질문'을 추가했다. 질문을 지정하면 기존 동의 관문을 거쳐 `generate/structure`에 ReportBrief를 보낸다. 질문을 비우면 기존 생성 스키마를 사용한다.
2. 구조화된 응답에서 근거 위치, 사실/추정/제안/미확인 주장, 핵심 답변의 주장 ID, 장별 역할/주장, 미확인 질문을 받는다. 장 ID와 source_refs는 코드가 연결한다. 핵심 답변의 주장은 답변 역할의 본문 장에 있어야 한다.
3. 코드가 추출 자료의 행 범위를 대조해 원문 발췌와 SHA-256 리비전을 만든다. 모델의 자료명과 원문 필드는 변형하지 않고 생성 문구만 기존 규칙대로 정규화한다. 없는 자료/행/참조, 중복 ID, 근거 없는 사실과 조건 없는 추정/미확인은 재시도 최대 1회 후 format_error로 반환한다.
4. `Structure.story_plan`을 승인, 저장, 다시 열기, 스냅샷 복원, 제목/순서/템플릿 편집과 undo/redo에서 보존한다. 계획을 장 생성과 축약 프롬프트에도 전달한다.
5. 계획 내용, 보고 정보, 구조안과 자료 집합의 fingerprint가 달라지면 장 생성/축약을 외부 호출 전에 409로 거절한다. 수동 수정은 저장되며 재계획을 요구한다. 슬라이드 슬롯/발표자/프리셋 편집은 이 계획을 무효화하지 않는다.
6. 화면에 핵심 판단, 주장별 원문 위치/발췌/조건과 확인할 질문을 표시한다. 위치 검사를 의미 검수 통과로 표시하지 않는다.

기존 Deck 버전은 1을 유지했다. OpenAPI와 생성 TypeScript, 합성 모의 응답을 함께 갱신했다. 최종 계약은 [아키텍처의 Q2a 실제 계약](../architecture/2026-09-12-quality-pipeline.md), 범위와 검토 기록은 [단위 계획](../plans/2026-09-12-q2a-story-plan.md)에 있다.

## 검증 결과

| 대상 | 결과 |
|---|---|
| 백엔드 전체 pytest | 987개 중 실패 0개, 15.39초 |
| 프런트 전체 Vitest | 257개 중 실패 0개, 파일 24개 통과 |
| 프런트 빌드 | tsc --noEmit 및 Vite 빌드 통과 |
| OpenAPI | 전체 pytest에서 현재 앱과 저장된 스키마 일치 |
| TypeScript 생성 계약 | 별도 임시 재생성 파일과 저장된 types.ts 바이트 일치 |
| 변경 범위/보존 검사 | Q1a 보호 파일 10개 중 변경 0개, git diff --check 문제 0개, 스테이징 비어 있음 |
| Q2a 새 회귀 사례 | 백엔드 33개, 프런트 5개 |
| 실제 AI/PowerPoint/독자 평가 | 대상 0개, 미수행 |

백엔드는 합성 자료 → 계획 응답 → 승인 저장 → 재읽기 → 장 생성/축약의 API 경로와 스냅샷 복원을 검증했다. 새 스키마가 실제 제공자에서 수용되는지는 모의 제공자로 입증되지 않는다. 프런트는 DOM 테스트이며 실제 앱 브라우저 조작을 수행한 것은 아니다. Q1a의 내보내기 회귀도 전체 테스트에 포함됐지만 Q2a 보고서를 실제 PowerPoint로 검수하지 않았다.

원시 로그는 임시 디렉터리 `slidecaptain-q2a-validation-sr18ptwk`의 backend-tests.log, frontend-tests.log, frontend-build.log에 있다. 장기 보존은 보장하지 않으며 위 표가 지속되는 검증 기록이다. 기존 변경의 작업 전 사본은 임시 디렉터리 `slidecaptain-q2a-baseline-h0yv11w9`에 두었다. 보호 파일 10개는 Q1a 인계, 점검 모델/정책/검증, CLI/내보내기와 ProjectView 계열이며, 함께 수정한 생성 프롬프트/API의 Q1a 동작은 전체 회귀 테스트로 확인했다.

## 미완료와 재심할 전제

- Q1b의 검수 상세/이력/무효화, 웹과 직접 CLI의 공통 내보내기 잠금은 미완료다.
- 원문 위치와 value 문자열 포함 여부를 확인해도 주장의 진실성, 올바른 수치 해석, 단위/기간/주체/분모의 비교 가능성이 입증되는 것은 아니다. 이 필드의 의미는 아직 모델이 분류한 초안이다. 계산기와 derivation/DerivedValue는 없다.
- 핵심 답변과 본문을 주장 ID로 연결했지만 생성된 각 장의 의미, 요약의 모순과 조건 누락을 독립적으로 검사하지 않는다. Q1a 품질 기록의 의미/근거/시각 검수는 계속 not_run이다.
- 수동 구조안을 바꾸면 기존 계획은 보존되지만 새 장 생성에는 전체 구조안 재생성이 필요하다. 부분 재계획, 주장/근거 장부의 수동 편집 UI와 상세 무효화 표시는 후속 범위다. 재생성 승인 시 기존 내용 교체는 기존 확인/스냅샷 경로를 따른다.
- 실제 제공자의 새 계획 스키마 수용성, 응답 품질/분량/호출 비용과 지연, 앱 서버의 새 백엔드 로드, PowerPoint 표시와 블라인드 비교는 검증하지 않았다. 현재 실행 중인 앱에 새 코드가 적용됐다고 가정하지 않는다.
- 프로젝트가 참조한 superpowers/requesting-code-review 스킬은 설치 검색에서 각각 0건이었다. engineering:code-review 기준의 자체 검토는 수행했지만 독립 에이전트 리뷰는 미수행이다. 검토에서 발견한 Brief 지시 충돌과 표지 주장 누락은 실패 테스트로 확인하고 수정했다.

위 항목은 [로드맵의 Q2a 이월](../plans/2026-08-27-mvp-roadmap.md)과 [Q0~Q5 계획](../plans/2026-09-12-quality-first-rebuild.md)에도 반영했다. Q2 전체 완료나 제품 품질 통과로 표시하지 않는다.

## 파일 지도

- 모델/파서/바인딩: `backend/slidecaptain/models/story.py`, `backend/slidecaptain/pipeline/story.py`.
- 기존 계약 연결: `models/deck.py`, `pipeline/service.py`, `pipeline/prompts.py`, `server/app.py` (모두 backend/slidecaptain 아래).
- 화면과 편집 보존: `frontend/src/screens/StructureScreen.tsx`, `StoryPlanView.tsx`, `frontend/src/editor/slotOps.ts`, `templateSwitch.ts`.
- API 타입: `backend/openapi.json`, `frontend/src/api/types.ts`, `frontend/src/api/client.ts`.
- 합성 검증: `backend/tests/test_story_plan.py`, `frontend/src/screens/StructureScreen.story.test.tsx`, `frontend/src/editor/storyPreservation.test.ts`, `frontend/src/test/story.ts`.
- 기존 Q1a 인계와 점검 구현은 보존했다. 별도 신규 위키 지식 페이지나 메모리를 작성하지 않았다.

## 다음 즉시 행동

이 인계와 Q2a 실제 계약을 먼저 읽고 저장소의 변경/스테이징 상태를 확인한다. 다음 Q2 단위는 **근거 항목의 지표 정의, 단위, 기간과 분모를 비교 계약으로 구조화하고 비교 불가 사유를 반환하는 최소 경로**부터 범위를 확정하는 것이 좋다. 계산기, 전체 의미 검수와 부분 재계획을 한 번에 묶지 않는다. 실제 AI 실증을 하려면 합성 자료 범위와 호출 수/비용 승인을 먼저 확인한다.

재개 요청 예시:

> 최신 Q2a 인계를 읽고, 다음 Q2 단위인 지표 비교 계약과 비교 불가 판정의 최소 범위만 구현·테스트·빌드해줘. 기존 변경을 보존하고 다음 인계 지점에서 멈춰줘.

## 위키 참조와 적용 기록

위키의 slidecaptain 페이지는 2026-09-06 상태였으므로 현재 상태는 Q1a 인계와 실제 코드로 재확인했다. Contract-Measure-Roundtrip-Test의 계약 왕복 기준을 저장/API/장 생성과 프런트 편집 보존 테스트에 적용했다. 두 페이지의 Codex 명시적 읽기 로그를 확인했다. pages_read=2, frames_applied=1, wiki_irrelevant_justified=0, reflux=0이다. 환류는 이 프로젝트의 업무 기록으로만 남겼으며 신규 위키 수집은 하지 않았다.

프로젝트 CLAUDE.md의 현재 상태/인계 포인터 변경을 공통 shared-work.md의 승인 범위, 편집 보존과 검증 구분 기준에 대조했다. 이 파일은 llm-wiki 관리 사본이 아니므로 공통 정본/설치 사본을 수정하지 않았다. 환경 동기화와 최종 정적 검사 결과는 current, pending_files=[]였으며 새 앱 세션의 로드는 검증하지 않았다.
