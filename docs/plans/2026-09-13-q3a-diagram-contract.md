# Q3a 첫 단위: DiagramSpec 계약과 실패 경계

작성: 2026-09-13. 사용자 요청: "slide captain 프로젝트 계속". 최신 Q1b 세 번째 단위 인계의 다음 후보를 한정해 이어간다. 상태: 구현/로컬 검증과 독립 리뷰 수정을 완료하고 [인계](../handoffs/2026-09-13-q3a-diagram-contract-handoff.md)한다.

## 목적과 종료 지점

의미적 노드, 관계, 라벨과 기존 근거 ID를 보존하는 독립 Pydantic 계약을 만든다. 합성 fixture의 파싱/직렬화와 오류 거절을 검증한 뒤 인계한다. Deck, StoryPlan, 프리셋, 저장 버전, 생성/API 계약과 실행 중인 앱은 변경하지 않는다. 배치, 프런트/PPTX 렌더와 AI 연결은 다음 단위다.

기존 누적 변경 234개 파일을 저장소 밖에 백업하고 detached worktree에 현재 내용을 복사했다. 이 격리본에서 구현/검사하고 원본의 시작 해시가 같은 이번 단위 파일만 반영한다. 스테이징은 비어 있으며 커밋/pull/push/merge는 하지 않는다.

## 계약 초안과 가정

1. `models/diagram.py`의 `DiagramSpec`은 명시적 `q3a-v1`, `id`, `canvas`, `nodes`, `edges`, `layout_variant`를 가진다. 모든 계층은 알 수 없는 필드를 거절한다. 페이지는 `preset` 크기 참조, 읽기 프로필은 `report`, 첫 배치 이름은 `flow_horizontal`이다. 이 이름은 향후 배치 입력이며 배치 구현을 뜻하지 않는다. 현재 Preset의 960x540 기본값을 새 상수로 복제하지 않는다.
2. 노드는 `id`, `role`(step/entity/decision/outcome), `content`, `kind`(fact/inference/proposal/unknown), `evidence_ids`, `caveats`를 가진다. 사실은 근거가 필요하고 추정/미확인은 조건이 필요하다. 노드 2~12개, 관계 1~24개, 내용 500자, 관계 라벨 120자를 상한으로 둔다. 이는 첫 계약의 자원/분량 경계이며 화면에 들어간다는 보증이 아니다.
3. 관계는 `id`, `from_node_id`, `to_node_id`, `relation`(flow/reference/proposal), `label`, `evidence_ids`를 가진다. flow/reference는 관계 자체의 근거를 요구하며 양끝 노드의 근거로 대신하지 않는다. proposal은 무근거 제안을 명시적으로 허용한다. 인과와 지표 comparison은 이번 버전의 관계 타입으로 받지 않는다. 이는 열거값 검사이며 자유 content/label에 담긴 인과 의미와 근거가 관계를 실제로 뒷받침하는지는 미검증이다. comparison은 Q2b 비교 조건과 연결할 계약이 필요하므로 이후로 미룬다.
4. 노드/관계 전체의 ID 중복, 같은 목록의 근거 ID 중복, 없는 노드/근거, 자기 연결, 중복 관계(같은 방향/관계), flow 순환을 거절한다. reference/proposal은 순서나 인과를 주장하지 않으며 flow 순환 검사에 넣지 않는다.
5. `parse_diagram_spec(payload, *, evidence)`가 유일한 지원 파서다. evidence는 기존 `Evidence` 목록이며 ID가 중복되면 거절한다. Pydantic context 없이 DiagramSpec을 직접 검증하면 근거 존재 검사를 우회하지 못하도록 거절한다. 기존 Evidence의 필수 원문 위치/해시 필드를 재검증하지만 파일을 읽거나 원문 의미를 검증하지 않는다.
6. dict 또는 JSON 문자열을 파싱한다. 중복 JSON 키, 지원하지 않는 버전, 누락, 빈 문구와 명백히 잘못된 자료형을 거절한다. 모든 Diagram 계층에 strict/extra forbid/revalidate_instances always를 적용해 모델 인스턴스도 직접 재검증한다. Evidence는 중첩 위치 정보와 미정의 필드까지 원래 입력으로 풀어 재검증한다. 독립 리뷰에서 dump가 미정의 필드를 버리는 문제를 확인해 이 방식으로 정정했다. model_construct/model_copy는 검증 우회 API이며 제품의 지원 입력 경로는 아니다. 그런 인스턴스를 지원 파서에 넣으면 다시 검증하고 반환 뒤 편집도 재파싱해야 한다. 입력을 수정하지 않으며 저장된 판정이나 임의 quality/pass 필드를 받지 않는다.
7. 좌표/크기/anchor/style/z-order와 HTML/SVG/script 전용 필드는 전 계층에서 거절한다. 일반 content는 실행하지 않는 평문이다. 도입안의 페이지 밖 좌표 사례는 이번에는 좌표 입력 자체를 거절하는 검사로 고정하고, 계산된 배치의 경계 검사는 Q3b 이후로 남긴다. 이 축소는 도입안과 로드맵에도 날짜/사유를 명시한다.

## 검증

- 구현 전에 새 모듈 부재를 확인하고 실제 계약/관계 오류 사례를 테스트로 작성한다. 모듈 부재의 수집 오류를 여러 테스트 실패로 세지 않는다.
- 합성 fixture: 근거가 있는 흐름과 명시적 제안. JSON 왕복 후 의미/근거 ID/관계 방향이 같고 기존 입력은 바이트/구조 동일하다.
- 중복 ID/JSON 키, 끊긴 참조, 노드 근거만 있는 관계, 무근거 사실, 추정 조건 누락, 자기 연결/flow 순환, comparison/인과 관계 타입, 좌표와 실행 필드, 개수/문자열/타입/버전 경계를 확인한다.
- q2a/q2b/q2c 저장 fixture의 저장/재읽기와 fingerprint 검사를 실행한다. Deck와 OpenAPI/프런트 타입은 수정하지 않고 현재 API 스키마 일치를 검사한다.
- 백엔드 전체와 기존 프런트 검사/빌드, 공개 저장소 감사와 변경 경로 보존 대조를 실행한다. 설치된 가상환경은 원본 것을 쓰되 PYTHONPATH는 격리 작업 트리/backend로 고정한다.
- 독립 계획/구현 리뷰의 발견을 반영하고 로드맵/단위 계획/인계에 결과를 남긴다. 실제 AI, Chrome 도식 화면, PowerPoint, 독자 품질 대상은 이번에 0건이며 미검증이다.

## 관련

- [도입안](2026-09-13-diagram-spec-adoption.md), [품질 개발 계획](2026-09-12-quality-first-rebuild.md), [로드맵](2026-08-27-mvp-roadmap.md)
- [직전 인계](../handoffs/2026-09-13-q1b3-export-history-handoff.md)
- 위키 `Editable-HTML-Diagram-Contract`: 의미/배치 분리와 근거 없는 관계/품질 승격 방지에 적용했다. 새 지식 저장은 하지 않는다.

## 관측 결과

- 최초 검사에서 새 모듈 부재의 수집 오류 1건을 확인했다. 구현 리뷰 결함은 별도 회귀 8개가 실제 실패한 뒤 수정했으며, 마지막 도식 검사 100개가 통과했다.
- 마지막 코드 수정 후 백엔드 전체 1,359개 중 1,358개 통과, Windows 네이티브 이력 검사 1개 미실행, 실패 0개다. 프런트 30개 파일/312개 검사와 tsc/Vite 빌드가 통과했다.
- 기존 저장본 4종(계획 없는 레거시와 q2a/q2b/q2c)의 실제 저장/재읽기에서 차이 0건, 도식 파싱 전후 저장 파일 변경 0건, 계획 3종의 fingerprint 유지다. OpenAPI/TypeScript 생성 파일 2개는 재생성 후 시작본과 바이트 동일하다.
- 독립 검토자가 4개 노드 방향 그래프 4,096종의 순환 판정을 대조해 불일치 0건으로 보고했다. 마지막 파서 수정의 재검토는 추가 필수 수정 없음이다. 이번 리뷰는 누적 브랜치 전체의 검수로 소급하지 않는다.
- 배치, 실제 도식 화면과 PPTX 생성/렌더, AI 호출, 독자 품질 검사 대상은 0건이므로 미검증이다. 다음 후보는 Q3b의 결정론 배치 첫 단위다.
