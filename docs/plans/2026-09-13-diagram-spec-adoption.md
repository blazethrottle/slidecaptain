# DiagramSpec 도입안

작성: 2026-09-13. 근거: `tonywjs/html-diagram`의 편집 가능한 HTML 도식 계약과 현재 SlideCaptain 품질 중심 파이프라인.

## 목적

현재 SlideCaptain의 `RenderPlan`은 `Frame`과 `TablePlan` 중심이라 관계도와 복합 도식을 일반적인 제품 계약으로 표현하기 어렵다. html-diagram의 구현을 복사하지 않고, 의미적 관계와 검증 가능한 레이아웃을 SlideCaptain 내부 계약으로 수용한다.

## 범위

초기 계약 후보는 다음과 같다.

```text
DiagramSpec
  canvas: page_size, reading_profile
  nodes: id, role, content, size_hint, evidence_ids
  edges: id, from, to, relation, label, anchor, style, evidence_ids
  layout_variant: named deterministic strategy
```

- 모델 출력은 노드의 의미, 관계, 라벨, 근거 ID와 레이아웃 힌트까지만 허용한다.
- 백엔드가 좌표, 크기, 줄바꿈, 앵커, z-order를 계산한다.
- `from`과 `to`는 현재 계획 안의 노드만 참조한다.
- 관계에는 `flow`, `comparison`, `reference`, `proposal` 같은 의미를 둔다. 근거 없는 인과 표현은 허용하지 않는다.
- `evidence_ids`는 기존 `Evidence`와 연결한다. 도식은 장식이 아니라 주장 표현이므로 근거를 잃지 않는다.

## 품질 관문

1. 구조 검사: ID 중복, 끊긴 참조, 페이지 밖 좌표, 잘못된 관계와 근거를 차단한다.
2. 결정론 배치: 같은 `DiagramSpec`, 프로필, 폰트 입력이 같은 후보 배치를 만든다.
3. 화면 검사: 겹침, 라벨 충돌, 최소 글자, 여백, 화살표 방향과 실제 관계를 확인한다.
4. PPTX 검사: 미리보기와 같은 렌더 계획을 사용하고, 목표 PowerPoint 환경의 표시를 별도로 확인한다.
5. 독립 검수: 내용·근거·시각 계층을 생성과 다른 검수 컨텍스트에서 판정한다.

점유율 하나를 통과 조건으로 삼지 않는다. 배경판 하나로 점유율을 높일 수 있으므로 겹침·라벨 충돌·가독성과 함께 본다.

## 단계적 도입

### 1단계: 계약과 fixture

2026-09-13 Q3a에서 독립 Pydantic 모델과 합성 fixture를 구현했다. 실제 범위는 [단위 계획](2026-09-13-q3a-diagram-contract.md)과 [인계](../handoffs/2026-09-13-q3a-diagram-contract-handoff.md)를 따른다. 중복 ID, 끊긴 edge, 근거 없는 사실 관계와 파서 재검증을 검사하며 기존 Deck과 레거시 저장본 왕복은 변경하지 않았다.

범위 정정(2026-09-13): 초기 계약은 좌표/크기/anchor/style을 입력으로 받지 않는다. 따라서 페이지 밖 좌표 실패 사례는 좌표 필드 자체의 거절로 고정하고, 계산된 배치의 페이지 경계 검사는 2단계 이후로 옮긴다. page_size는 기존 Preset 참조, reading_profile은 report, layout_variant는 flow_horizontal만 받는다. Q3a 당시 배치 기능은 없었으며 이후 Q3b 첫 단위는 아래 2단계 기록을 따른다.

관계 타입은 flow/reference/proposal이고 순환 flow는 Q3a에서 미지원이다. comparison은 Q2b 비교 조건과의 연결 계약이 필요하므로 이후로 미룬다. 인과 타입 거절은 열거값 검사이며 자유 문구의 인과 의미와 근거의 실제 뒷받침은 검사하지 않는다. 아래 전체 도입 완료 조건 중 배치/렌더/독립 독자 검수는 미완료다.

### 2단계: 결정론 레이아웃 어댑터

도식 노드와 엣지를 기존 `Frame` 또는 새 typed render object로 변환한다. 프런트와 PPTX 라이터가 같은 백엔드 결과를 소비하도록 하며, 레이아웃 계산을 TypeScript에 중복 구현하지 않는다.

2026-09-13 [Q3b 첫 단위](2026-09-13-q3b-diagram-layout.md)에서 독립 typed 배치 후보와 불가 사유를 구현했다. 현재 report/flow_horizontal은 한 줄의 인접 관계만 지원한다. 본문/관계 라벨/조건의 실제 폭과 높이, 선/화살표 외곽과 본문 경계, 흐름과 참조/제안의 구별을 계산한다. 미지원 토폴로지/폰트/문자와 공간 부족에는 부분 후보를 내지 않는다. 실제 미리보기와 PPTX 라이터 연결은 3단계로 남아 있으며 [인계](../handoffs/2026-09-13-q3b-diagram-layout-handoff.md)에 검증 범위를 기록한다.

### 3단계: 검수와 실제 렌더

합성 도식으로 구조 검사, Chrome 미리보기, PPTX 렌더, 라벨·겹침 검사를 연결한다. 실제 AI 생성과 목표 PowerPoint 독자 품질은 별도 검증으로 남긴다.

## 제외 범위

- `tonywjs/html-diagram`의 JavaScript·CSS 엔진 복사
- 라이선스가 확인되지 않은 코드의 런타임 의존성화
- LLM이 HTML, SVG, 임의 스크립트와 절대 좌표를 직접 제품 데이터로 저장하는 경로
- HTML 정적 export를 PPTX 품질의 대리 지표로 사용하는 것
- 현재 5B 미커밋 변경과 동시 수정

## 완료 조건

- 계약과 실패 경계가 테스트로 고정된다.
- 같은 입력에서 미리보기와 PPTX가 같은 관계와 배치를 보인다.
- 실제 렌더와 독립 검수의 미수행 상태를 `not_run`으로 구분한다.
- 기존 저장본과 레거시 템플릿이 자동 변경되지 않는다.
- 구현 단위가 끝난 뒤 테스트, 빌드, 인계 문서를 갱신한다.


## 2026-09-13 Q3b 공통 렌더 단위 결과

[렌더 계획](2026-09-13-q3b-diagram-render.md)과 [최신 인계](../handoffs/2026-09-13-q3b-diagram-render-handoff.md)에 따라 공통 문구를 포함한 도식 RenderPlan을 기존 Preview와 편집 가능한 PPTX 라이터에 연결했다. 이번 개정은 배치 계산, 두 소비자의 구조 정합과 실제 보고서 품질을 구분하기 위해서다. 원래 의미 입력에서 재계산하며 노드/관계/근거/조건, 좌표/줄바꿈/폰트/선/화살표를 보존한다. 기존 Deck/StoryPlan/저장 버전과 일반 템플릿은 유지하고 출력 스키마와 생성 타입을 갱신했다. 빈 도식 필드로 기존 품질 fingerprint가 바뀌지 않도록 했다.

백엔드 1,456개 통과/Windows 전용 1개 미실행, 프런트 316개와 타입/빌드를 확인했다. Chrome에서 번들 regular/bold를 로드한 합성 3개와 PPTX XML/재열기/텍스트 수정을 확인했다. 독립 리뷰의 수치 표현 범위와 공통 문구 overflow를 반영했고 최종 필수 수정은 0개다. 앱의 도식 저장/편집/생성 연결과 검수 만료, 실제 AI/목표 PowerPoint/독자 품질은 남는다. 다음은 의미 입력 저장과 미리보기 연결의 첫 단위다.

## 2026-09-20 프로젝트 도식 저장/읽기 전용 미리보기

공통 렌더 다음의 [프로젝트 연결 단위](2026-09-20-q3b-project-diagrams.md)를 완료했다. Deck의 도식 슬롯에는 좌표 없이 의미 입력만 저장하고 StoryPlan.evidence를 참조한다. 저장/복원 후 기존 Preview와 전체 덱 초안 PPTX에서 재계산하며, 읽기 전용 경계와 생성 차단을 연결했다. 독립 DiagramSpec 파서의 근거 검증은 유지한다.

검증은 백엔드 1,486개 통과/Windows 전용 1개 미실행, 프런트 323개, 타입/빌드, 독립 리뷰와 실제 내장 브라우저 합성 2개다. 기존 저장본 3개의 직렬화/품질 fingerprint를 유지했다. 실제 AI/목표 PowerPoint/독자 품질과 검수 승인 저장은 미완료이며 [최신 인계](../handoffs/2026-09-20-q3b-project-diagrams-handoff.md)를 따른다.

## 2026-09-20 도식 작성/수정 UI

[직접 작성 계획](2026-09-20-q3b-diagram-authoring.md)에 따라 빈 덱/기존 도식의 작성 창을 연결했다. 기존 장부에서 노드와 관계의 근거를 선택하고 좌표 입력 없이 배치를 확인한 뒤 적용한다. 화면 미리보기는 계속 읽기 전용이며 실제 의미 검수/품질 승인은 하지 않는다. 검증 결과와 독립 리뷰 미수행, 후속 재계획 경계는 [최신 인계](../handoffs/2026-09-20-q3b-diagram-authoring-handoff.md)를 따른다.

## 2026-09-20 기존 보고 계획과 도식 장 연결

[연결 계획](2026-09-20-q3b-story-plan-reconciliation.md)에 따라 새 도식 장이 기존 `StoryPlan.chapters`의 보고 역할과 기존 주장 ID를 명시적으로 참조하도록 하는 최소 계약을 연결했다. 서버는 저장본 ETag와 도식 외 덱 동일성, 자료 revision/excerpt, 저장본 계획의 현재 fingerprint를 확인한 뒤 후보 덱만 반환한다. 같은 장을 다시 확인하면 기존 연결을 교체하며, 저장/스냅샷/AI 호출은 기존 적용 경로에 남긴다.

백엔드 전체 1,497개 통과/Windows 전용 1개 미실행, 프런트 345개/34파일, 생성 타입과 빌드를 확인했다. 이번 단위의 실제 Chrome 검증과 독립 리뷰, 도식 의미 검수, 도식 AI 생성/전체 재계획, 실제 AI/목표 PowerPoint/독자 품질은 미완료이며 [최신 인계](../handoffs/2026-09-20-q3b-story-plan-reconciliation-handoff.md)를 따른다.
