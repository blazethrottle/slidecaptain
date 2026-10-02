# Q2f 미등록 비교·산식과 요약 방향 검토 후보

작성 2026-09-30. Q2 잔여 중 자동으로 의심 지점을 찾을 수 있는 범위를 구현한다. 원문 의미·자유 문장의 정확성·요약 전체의 일관성을 통과로 판정하지 않는다. AI 호출 없이 실행하며 Claim/Evidence/본문/검수 판정을 수정하지 않는다.

## 결과 계약과 대상

별도 `SemanticSuspectReport`를 반환한다. `rule_version='semantic-suspect-v1'`, 입력 fingerprint, status(not_run/needs_review/no_signals_detected), semantic_status='not_run', evaluated_fields/findings와 reason을 가진다. findings는 code, chapter_id, field path, 원래 text/탐지 구간, 관련 claim/comparison/derivation IDs, 사람이 확인할 이유를 가진다. 탐지 대상 0개와 계획/자료가 낡은 상태는 not_run이다. no_signals_detected는 정의한 탐지 규칙에서 후보를 발견하지 못했다는 뜻이며 의미 검수나 제출 통과가 아니다.

읽는 대상은 현재 StoryPlan.claim.statement와 실제 슬라이드의 보이는 문구다. 메타 ID/캔버스/자동 번호·표지 날짜 등은 제외한다. `_require_current_evidence`와 require_current_story로 원문/계획 현재성을 먼저 검사한다. 원본 숫자는 다른 결과로 덮어쓰지 않는다. 입력이 달라지면 같은 요청에서도 다시 계산한다. 필드별 개수와 전체 한도를 정해 잘린 검사를 완료로 표시하지 않는다.

## 탐지 규칙

1. **미등록 수치 비교 후보**: 숫자가 있는 주장/본문에서 대비/보다/격차/차이/증감률/증가율/감소율 등의 비교 표지를 찾고 해당 claim 또는 장/핵심 답변에 연결된 declared comparison이 없으면 unregistered_comparison 후보로 남긴다. 정성 비교와 '자료를 보다' 같은 표현은 수치 계약을 요구하는 대상으로 자동 승격하지 않는다.
2. **미등록 산식 후보**: 숫자 양옆의 명시적 산술(+/×/÷/곱셈/등호) 또는 숫자와 증감률·증가율·감소율 표지에서, 연결된 declared derivation이 없으면 unregistered_formula 후보로 남긴다. 날짜·기간·단순 원문 값은 산식으로 처리하지 않는다. 임의 eval/숫자 계산은 실행하지 않는다.
3. **계산 방향 후보**: computed 차이/증감률의 부호와 반대 방향 표지(증가/상승/개선 대 감소/하락/악화)가 같은 지표 정의를 명시한 문장에 있으면 calculated_direction_mismatch 후보를 남긴다. 주체·기간·인과·비용 효과·부정문을 해석해 오류로 확정하지 않는다.
4. **요약-본문 방향 후보**: summary 템플릿의 결론/요점과 공유한 claim/comparison 지표 정의를 포함하는 다른 본문의 방향 표지가 반대일 때 summary_direction_conflict 후보를 남긴다. 원래 두 문장과 정의/claim 연결을 함께 반환한다. 다른 지표/공유 주장 없음/단순 재표현은 자동 모순 판정을 만들지 않는다.

등록된 comparison/derivation이 있다는 이유로 그 문장의 의미가 검증됐다고 표시하지 않는다. 복잡한 산식, 은유·부정/조건 문장과 비교적 서술은 탐지 누락/오탐이 가능하며 독립 검수 대상이다. Q2d exact numerical expression 검사는 별도로 유지한다. 이 휴리스틱 결과는 Q4 독립 signed receipt나 필수 의미 검수를 대신하지 않는다.

## 소유권·연결·검증

본 담당: 새 models/semantic_review.py, pipeline/semantic_review.py, 관련 tests. 기존 story.py/comparison.py/derivation.py는 이 단위에서 추가 편집하지 않는다. root 담당: GET 또는 readonly POST API(명시적 현재 deck 입력이면 기존 숫자검토 POST와 같은 헤더 보호), OpenAPI/프런트 타입, 편집 화면의 탐지 후보 설명. root가 API/UI 소유권을 넘기기 전에는 수정하지 않는다.

실패 테스트: 미등록 수치 비교/명시적 산식 후보, 등록된 연결의 범위, 다른 장 산식이 경고를 숨기지 않음, 날짜/원문 번호/정성 표현 제외, computed 방향과 summary 공유지표 후보, 다른 지표/장 역할/보호 도식 보존, stale source/계획/대상0 not_run, 보고서 fingerprint 변경, 검사한 문구 수와 실사용명확성. 기존 근거/수치/품질 회귀를 실행한다. 본인의 결과는 독립 리뷰 후 수용하며 실제 AI·독자 판정은 별도다.

## 구현·검증 결과

2026-09-30: 결정론 read-only core를 구현했다. 필드 5,000개/문자 200,000자/후보 1,000개를 넘으면 부분 결과 대신 review_limit 미실행으로 반환한다. 숫자와 비교·증감률 표지는 같은 문장 범위에서 찾으며, ISO 날짜와 년-월 표시는 산식에서 제외한다. 요약 방향 비교는 실제 장에 연결된 공유 주장과 이름이 같은 지표 정의를 요구한다. 불변성·현재성·다른 범위 억제·상한·요약 반례를 자동 검사했다. API/UI와 독립 검수는 root의 별도 연결/검토 대상이다.

차트의 원래 근거 보호는 pipeline/rewrite.py에 연결했다. 차트 장의 assignment/claim/evidence/comparison/derivation과 명시적 단위 정규화 입력을 서버가 병합하며, 본문은 그대로 보존한다. 차트 보호 3개는 구현 전 실패와 구현 후 통과를 확인했다. 전체 원자료 hash가 바뀌면 선택 행이 남아 있어도 ProtectedEvidenceChanged로 차단한다.

2026-10-01: 프로젝트별 API와 Editor의 검토 후보 패널을 연결했다. 독립 검토 반례와 현재성/늦은 응답 검사를 통과했고 Chrome에서 미수행 의미 검수 안내를 확인했다. 결정론 후보가 0개여도 의미 검수 통과로 표시하지 않는다. 실제 AI 블라인드 비교와 범위 한계는 [검증 기록](../qa/2026-10-01-remaining-batch.md)을 따른다.
