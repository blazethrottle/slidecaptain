# Q2e 명시적 단위 환산

2026-09-30. 사용자가 승인한 잔여 개발의 단위 환산을 처리한다. 임의 환율/기간 환산/분모 합성/% 환산/AI 실호출은 포함하지 않는다.

## 계약

- EvidenceComparison에 optional `unit_normalization`을 추가한다. 입력은 `rule_version='unit-scale-v1'`, target_unit(원/천원/만원/백만원/억원/명/천명/건/천건)만 가진다. source 단위는 각 Evidence.metric_basis.unit에서 읽으며 원문 값을 보존한다. factor와 normalized 값은 AI 응답에 허용하지 않는다.
- 단위 registry는 KRW, people, events 세 dimension과 정수 scale이다. 같은 dimension만 허용하고 conversion 요청이 없으면 기존 exact-unit comparison을 그대로 유지한다. 정의/주체/기간/분모와 결측 처리는 기존 판정을 유지한다. 환산은 절대값·분모 none·집계 ratio 아님에만 허용한다. %/통화환전/서로 다른 dimension은 blocked 비교로 남긴다.
- DerivedValue에 optional(빈 목록 직렬화 제외) `unit_conversions` 감사 metadata를 추가한다. 항목은 rule_version, evidence_id, original_value/original_unit, target_unit, 서버 factor_numerator/factor_denominator, exact normalized_value이다. 기존 value/unit는 환산 뒤 canonical target 단위의 결과이며 percent_change의 최종 단위는 기존 %다.
- 원문 숫자는 기존 source unit으로 전체 토큰·발췌 검증을 거친 후 Fraction으로 scale/target scale을 적용한다. 근거 값과 metric_basis는 바꾸지 않는다. 차이/증감률의 기존 sign/baseline/period 제한과 최종 6자리 반올림 규약은 유지한다.
- normalization 없는 기존 q2a/q2b/q2c의 모델 JSON/fingerprint를 바이트 보존한다. 새 optional fields는 None/empty일 때 serializer에서 제외한다. normalization은 q2e-v1에서만 사용하며 old version 우회는 거절한다. 새 계획 parser는 normalization이 존재할 때 q2e-v1, 없을 때 기존 q2c-v1을 생성해 현재 provider/tests 계약을 보존한다. 기존 q2e 재작성은 보호 그래프 normalization을 합치고 q2e version을 유지한다.
- stored computed metadata는 입력을 다시 validate/recompute하여 신뢰하지 않는다. 후보 model response schema에는 input normalization만 있으며 result/factor는 extra forbid로 거절한다. 본문 생성 지침과 재작성은 원자료 단위/환산 metadata/canonical result를 구분한다.

## 검증과 소유권

기존 세 version fixture 저장/fingerprint 불변, old-version normalization 거절, raw source suffix/발췌/근거 변조 거절, exact Fraction scale/downscale/반올림/zero baseline, dimension/%/분모 불일치, unsupported input factor/model result, protected rewrite 보존, computed metadata 재계산을 먼저 실패 테스트로 확인한다. 백엔드 비교/산식/계획/재작성/수치검수 회귀를 실행한다. root가 API/OpenAPI/프런트 타입과 환산 설명 UI를 연결하며 본인은 해당 파일을 수정하지 않는다.

소유권: models/comparison.py, derivation.py, story.py; pipeline/story.py, rewrite.py, prompts.py 최소 지침; 관련 backend tests/fixture. 다른 담당의 chart/render/qualification 변경을 보존한다. 독립 리뷰 후 필수 발견을 반영한다.

## 구현 검사 결과

비교 compatible은 입력 metadata와 환산 registry 차원의 일치다. malformed 원문 값은 비교 metadata가 일치하더라도 계산 단계에서 blocked로 남긴다. 환산 계산 완료는 원문 조건·생성 문장·보고서 의미 검수 통과가 아니다. 동일 단위 identity 환산도 명시적으로 요청했다면 q2e 규칙과 factor 1의 감사 정보를 남긴다.

신규 Q2e 37개를 포함한 비교/산식/계획/재작성/수치 대조/품질 관련 327개 검사 통과. 기존 q2c 실제 fixture의 JSON와 fingerprint를 그대로 유지하고 q2a/q2b 실제 fingerprint 회귀도 통과했다. 독립 리뷰 및 통합 타입/프런트 검증은 배치 인계에서 구분한다. 실제 AI 호출은 0회다.
