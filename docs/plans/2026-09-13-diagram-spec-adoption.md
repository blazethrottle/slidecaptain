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

`DiagramSpec`의 Pydantic 모델과 최소 fixture를 만든다. 파서, 중복 ID, 끊긴 edge, 근거 없는 관계, 페이지 밖 좌표를 실패 사례로 고정한다. 기존 `Deck`과 레거시 저장본 왕복은 변경하지 않는다.

### 2단계: 결정론 레이아웃 어댑터

도식 노드와 엣지를 기존 `Frame` 또는 새 typed render object로 변환한다. 프런트와 PPTX 라이터가 같은 백엔드 결과를 소비하도록 하며, 레이아웃 계산을 TypeScript에 중복 구현하지 않는다.

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
