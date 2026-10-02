# Q3b 첫 배치 단위 인계

작성: 2026-09-13. 사용자 요청은 "slide captain 개발 작업 계속 진행"이다. [Q3a 인계](2026-09-13-q3a-diagram-contract-handoff.md)의 다음 단위를 [배치 계획](../plans/2026-09-13-q3b-diagram-layout.md)으로 한정해 구현했다.

## 완료 범위와 종료 지점

검증한 DiagramSpec, 현재 Preset와 FontMetrics에서 노드/관계/근거/조건을 보존하는 독립 typed 배치 후보를 만든다. 좌표/크기, 줄바꿈, 관계별 레인과 앵커/화살표를 코드가 계산한다. 공간 부족과 미지원 입력은 부분 후보 없이 사유를 반환한다. 실제 앱의 도식 생성/편집/미리보기와 PPTX 출력에는 아직 연결하지 않았다.

시작과 종료 브랜치는 `codex/phase-5b`, HEAD는 `a8c6d7a`다. 기존 누적 미커밋 변경과 빈 스테이징을 보존했다. 원본을 백업하고 detached 작업 트리에서 구현/검증한 뒤 이번 단위 파일만 원래 프로젝트에 반영했다. 커밋/pull/push/merge/배포, 기존 서버 재시작과 실제 AI 호출은 수행하지 않았다. 사용자 저장 프로젝트 대신 합성 임시 저장소만 사용했다.

## 실제 구현 계약

- `layout/diagram.py`의 `build_diagram_layout(payload, preset, metrics, *, evidence)`가 Q3a 입력을 다시 파싱하고 중첩 Preset, 폰트 구조와 정규화 폭을 검증한다. 잘못된 입력은 ValueError 계열이며 유효하나 배치할 수 없는 입력에는 typed blocked를 반환한다. 파일/AI 호출과 입력 수정은 없다.
- `models/diagram_render.py`의 `DiagramLayoutResult(q3b-v1)`에 도식/근거/프리셋/폰트 수치의 fingerprint, computed/blocked, 전체 plan 또는 사유를 담는다. computed의 의미는 계산 완료이며 semantic/browser/powerpoint/reader는 모두 not_run이다.
- report/flow_horizontal의 첫 배치는 한 줄의 인접 노드다. flow의 위상 순서로 놓고 매 반복 동률은 원래 입력 인덱스가 가장 작은 노드를 선택한다. reference/proposal은 배치 순서를 정하지 않는다. 비인접 관계가 있으면 unsupported_topology로 차단하며 유효한 Q3a 입력을 다른 관계로 바꾸지 않는다.
- 노드에는 kind/role, 내용과 모든 조건을 box_pt로 표시한다. 관계 라벨은 body_pt로 표시하며 기존 본문 하한을 지킨다. 폭/높이가 부족해도 글자를 축소하거나 내용/조건을 삭제하지 않는다. 명시적 줄바꿈은 보존하고 줄바꿈기가 축약하는 공백, 제어문자와 폭이 확인되지 않은 글리프는 차단한다.
- 같은 간격의 복수 관계는 서로 다른 세로 레인을 쓴다. flow만 도착점 화살표가 있고 reference/proposal은 dotted/dashed 선과 관계명/주체/대상을 표시한다. 내용이 같은 노드는 ID로 구분하며 원래 의미 모델도 별도로 보존한다.
- 본문 경계와 글자/라벨 용량, 노드/선 굵기/화살표 외곽을 계산한다. 좌표는 기존 Preset의 pt와 content_box에서 나온다. 모든 출력 텍스트의 줄바꿈/높이와 앵커를 포함하므로 이후 소비자는 배치를 다시 계산하지 않아야 한다.

기존 DiagramSpec/Deck/StoryPlan/QualityReport, 저장 버전, API/OpenAPI/TypeScript와 생성 계약을 변경하지 않았다. 이 어댑터가 실제 원문/관계 의미나 OS 폰트 설치를 확인한 것은 아니다.

## 검증 결과

| 대상 | 관측 결과 |
|---|---|
| 새 Q3b 배치 검사 | 65개 중 실패 0개 |
| 백엔드 전체 | 1,424개 중 1,423개 통과, Windows 전용 1개 미실행, 실패 0개 |
| 프런트 전체 | 30개 파일의 312개 중 실패 0개 |
| 타입/빌드 | OpenAPI/TypeScript 재생성 파일 2개가 시작본과 바이트 동일, tsc/Vite 빌드 통과 |
| 실제 저장 왕복 | 레거시/q2a/q2b/q2c 4개 중 차이 0개, 계획 3종의 fingerprint 유지 |
| 계산의 저장 부작용 | 합성 저장 파일 8개의 SHA-256 유지, 계산으로 파일 변경 0개 |
| 독립 계획/구현 검토 | 발견 반영 후 마지막 재검토의 추가 필수 수정 0개 |
| 독립 합성 기하 대조 | 검토자가 1,200개에서 computed 558개/blocked 642개를 관측, 검사한 노드 밖 텍스트/라벨-노드/라벨끼리 겹침과 예외 0개로 보고 |
| 공개 저장소 감사 | 추적/미추적 일반 파일 244개 중 경로/내용 규칙 발견 0개 |
| 실제 AI/도식 화면/PowerPoint/독자 품질 | 대상 0개, 미검증 |

최초 실행은 새 모듈 부재로 테스트 수집 오류 1개였다. 계획 검토의 라벨 보강 뒤 기존 기대 문자열 1개를 새 계약에 맞췄다. 구현 검토의 폰트 단위 언더플로와 필수 속성 결손은 7개 실패를 재현한 뒤 수정했다. 마지막 코드 변경 후 백엔드 전체를 실행했다. 프런트는 변경하지 않았으므로 성공한 전체 테스트/빌드를 반복하지 않았다.

실제 검사는 격리 작업 트리의 backend를 PYTHONPATH로 지정해 원본 가상환경에서 수행했다. 독립 기하 대조는 실제 글리프 렌더나 가독성을 검증하지 않는다. 자동 검사 수를 보고서 품질 점수로 해석하지 않는다.

## 리뷰 반영과 보존

저장소의 독립 검토 요구에 따라 `engineering:code-review` 지침과 별도 읽기 전용 검토자를 사용했다. superpowers는 설치 검색에서 0건이었다. 계획에서 공백 축약과 참조/제안의 주체/대상 표시 누락을 반영했다. 구현에서는 정규화된 폰트 폭 0과 속성 결손을 거절하고, 표시명끼리의 충돌과 빈 computed 도식의 직렬화 검사를 보강했다. 이번 리뷰를 기존 누적 브랜치 전체의 검수로 소급하지 않는다.

원본 일반 파일 239개를 백업했다. 시작 해시를 대조한 뒤 기존 상태 문서 6개와 신규 5개 파일만 반영했다. 기존 233개 파일은 바이트 동일하며 삭제는 0개다. 빈 스테이징과 기존 생성 타입을 보존했다. 공개 저장소 감사에는 미추적 파일도 포함했다.

백업, detached 작업 트리와 검증 기록은 저장소 밖 임시 폴더 `slidecaptain-q3b-qa8z8kjk/`에 보존한다. `baseline/`, `baseline.json`, `initial-index.patch`, `review-red.log`, `backend-tests-final.log`, `frontend-tests.log`, `frontend-build.log`, `synthetic-layout.json`, `compatibility-check.json`, `applied-preservation.json`이 주요 기록이다. 임시 폴더는 영구 보관소가 아니며 이 인계와 로드맵이 지속 기록이다.

## 다음 행동과 재심 대상

다음 구현 후보는 같은 Q3b 결과를 소비하는 도식 공통 렌더의 첫 단위다. 미리보기와 편집 가능한 PPTX에서 같은 줄바꿈/폰트/선 스타일/화살표 점과 조건을 보존하는 경로를 계획 리뷰로 확정한다. 제목/각주만 예약한 현재 content_box와 공통 부제/분류 라벨의 결합도 먼저 다룬다. 프런트에 좌표/줄바꿈 계산을 중복하지 않는다.

현재 단일 행/인접 관계와 폭 배분은 잠정 제한이다. 분기/비인접 경로, 다른 읽기 프로필/폰트, 연속 공백과 미지원 글리프는 후속 지원 확대 대상이다. comparison은 Q2b 조건 연결이 필요하며 원문 현재성/자유 문장 의미, 생성/편집/저장 연결과 도식 변경의 검수 만료도 미구현이다.

직렬화된 후보의 스키마 통과만으로 좌표와 fingerprint의 무결성을 보증하지 않는다. 후속 소비자는 원래 의미/근거/프리셋/폰트 입력에서 재계산하고 현재 계산 결과를 공유해야 한다. UI/PPTX/독자 검수가 미수행이므로 제출본 승인으로 승격하지 않는다. Windows 네이티브/새 CI와 기존 Q2 의미/요약 정합성 이월도 그대로 남아 있다.

주요 파일은 다음과 같다.

- `backend/slidecaptain/layout/diagram.py`, `backend/slidecaptain/models/diagram_render.py`
- `backend/tests/test_diagram_layout.py`, 재사용한 `backend/tests/fixtures/q3a-diagram.json`
- 이번 단위 계획/인계, 로드맵, 도입안, 품질 개발 계획/아키텍처/제품 요구와 `CLAUDE.md` 최신 포인터

## 위키 참조와 환경 관측

`wiki/projects/slidecaptain.md`는 과거 맥락으로 참고하고 실제 최신 상태는 Q3a 인계/현재 구현으로 확인했다. `Editable-HTML-Diagram-Contract`의 의미/배치 분리, 관계 근거 보존과 구조 검사의 품질 승격 금지를 대조했다. 기존 후속 계획과 같은 결론이어서 기존 측정 원장에 no_effect 1건을 추가했다. `pages_read=2`, `frames_applied=1`, `wiki_irrelevant_justified=0`, `reflux=0`이며 새 지식 축적 없이 프로젝트 기록으로 환류했다. 사용자 품질 판정을 작성하지 않았다.

새 위키 세션의 환경 동기화는 current/changed_files=[]였다. 설치 파일 검사와 새 앱 세션의 읽기 검증은 다르며 runtime_verified는 false다. 위키 지식 본문과 무관한 대기 큐는 수정하지 않았다.
