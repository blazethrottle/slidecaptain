# Q3b 도식 장과 기존 보고 계획 연결 인계

작성: 2026-09-20. [단위 계획](../plans/2026-09-20-q3b-story-plan-reconciliation.md)에 따라 작성/수정된 도식 장을 기존 `StoryPlan`에 연결하는 최소 계약을 구현하고 로컬 검증했다. 이전 단위는 도식 의미 입력의 직접 작성/수정 UI다.

## 완료한 동작

- 도식 장은 기존 `StoryPlan.claims`의 주장 ID를 하나 이상 선택하고, `answer`, `context`, `evidence`, `risk`, `action` 중 하나의 보고 역할을 지정한다. `cover`와 `divider`는 연결할 수 없다.
- 연결 확인은 같은 `chapter_id`의 `StoryChapter`를 교체해 중복을 만들지 않는다. 기존 주장, 근거, 비교, 계산 결과, 미답 질문과 다른 장의 연결은 보존한다.
- 서버는 저장본 ETag를 확인하고, 후보에서 대상 도식 장과 해당 slide를 제외한 나머지 덱이 저장본과 같은지 검사한다. 도식과 무관한 낡은 변경을 함께 승인하지 않는다.
- 모든 기존 근거의 source revision과 현재 원문 발췌문을 다시 확인한다. 저장본의 계획 자체가 이미 낡았으면 새 도식 연결로 fingerprint를 갱신하지 않고 `409`를 반환한다.
- 연결 API는 현재 자료를 사용해 후보 `Deck`만 반환한다. 저장, 스냅샷, undo/redo, AI provider 또는 lease를 호출하지 않는다. 화면은 이 후보를 기존 도식 배치 확인 API에 통과시킨 뒤 기존 적용/저장 경로로 넘긴다.
- 연결 정보가 의미 검수, 주장과 도식의 실제 일치, 시각 품질 또는 제출 승인이라는 오해를 막도록 화면에 별도 안내를 둔다.

## 변경 파일과 계약

- `backend/slidecaptain/pipeline/story.py`: 근거 현재성, 도식 외 변경, 기존 계획 fingerprint를 검사하고 연결된 후보를 생성한다.
- `backend/slidecaptain/server/app.py`: `POST /api/projects/{name}/story-plan/diagram`을 추가했다. 저장하지 않는 후보 왕복이며 현재 저장본과 선택적 `If-Match`를 확인한다.
- `frontend/src/api/client.ts`, `frontend/src/editor/diagramDraft.ts`, `frontend/src/editor/DiagramAuthoringDialog.tsx`, `frontend/src/screens/EditorScreen.tsx`: 역할/주장 선택과 연결 확인 후 배치 확인을 연결했다.
- `backend/tests/test_story_plan_reconciliation.py`, `frontend/src/editor/DiagramAuthoringDialog.test.tsx`, `frontend/src/api/client.test.ts`: 정상 왕복, 중복 교체, 잘못된 ID/역할, 자료 변경, 저장 충돌, 낡은 저장 계획, 저장/AI 호출 부재와 입력 검증을 고정했다.

## 검증

| 대상 | 결과 |
|---|---|
| 백엔드 연결 단위 | 11개 통과 |
| 백엔드 전체 회귀 | 1,497개 통과, Windows 전용 1개 미실행 |
| 프런트 전체 회귀 | 345개 통과/34파일 |
| 생성 계약 | OpenAPI와 TypeScript 생성 타입 갱신 및 테스트 통과 |
| 프런트 빌드 | TypeScript와 Vite 빌드 통과 |
| 독립 리뷰 | 미수행. 로컬 자체 검증은 독립 리뷰를 대신하지 않는다. |
| 이번 단위의 실제 Chrome | 미수행. 이전 작성 UI의 브라우저 결과를 이번 연결 UI 검증으로 간주하지 않는다. |

## 미완료와 다음 경계

도식 작성/수정 UI와 연결 계약에 대한 독립 리뷰가 남아 있다. 도식의 의미가 주장과 실제로 일치하는지, 원문 해석이 맞는지, 보고서 독자가 이해하는지는 이 계약이나 테스트 통과로 승인하지 않는다.

다음 단위는 별도 승인 없이 도식 AI 생성이나 전체 `StoryPlan` 재계획으로 확장하지 않는다. 검수 승인 저장/만료, 자유 토폴로지와 분기 배치, 실제 AI 인증/생성 관통, 목표 PowerPoint 앱과 독자 품질은 계속 미검증이다.

## 보존과 재개

원본은 `~/Projects/slidecaptain`, 브랜치는 `codex/phase-5b`, 시작 HEAD는 `a8c6d7a`다. 기존 누적 미커밋 변경과 스테이징은 건드리지 않았고, 이번 단위에서 커밋/푸시/머지/배포를 수행하지 않았다. 재개 시 이 인계, 단위 계획, 실제 `git status`, 백엔드/프런트 현재 테스트 결과를 함께 확인한다.
