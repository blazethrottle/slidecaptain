# 명시적 문서 교체와 보호 근거 이동

승인 범위: 로컬 backend 계약과 합성 검증. 실제 AI 호출/commit/push 없음. 다른 작업자 변경을 보존한다. root는 API 저장 경계/프런트, q4 backend는 아래 순수 모델/함수/도식 요청 경계만 소유한다.

## 계약

- `preview_document_change(base, candidate, sources, confirmation_key)`는 저장하지 않는다. 현재 계획/근거를 확인하고 후보를 다시 검증한다. 장 추가/삭제/재배치, 본문/도식/메타 교체를 허용하되 기존 도식·차트의 보호 장 연결/주장/근거/비교/산식은 동일 ID/내용으로 보존한다. 보호 장 삭제는 이 일반 계약에서 거절한다. 새 근거도 서버의 현재 원문 whole hash/locator/excerpt와 일치해야 한다. 최종 의미 승인을 하지 않는다.
- 서버가 모든 변경 경로의 `LossItem(id,path,kind,before,after)`를 만든다. before/after는 원문 JSON이다. 사용자가 보는 전체 변경량(삭제뿐 아니라 추가/재배치 포함)을 확인 대상으로 삼는다. 미리보기에는 base/source/candidate SHA-256, inventory, HMAC-SHA256 token, 검수 미수행 안내를 반환한다.
- `apply_document_change`는 같은 base/candidate/source와 token을 다시 계산하고 확인한 inventory ID의 정확한 집합을 요구한다. 서버별 32byte 이상 비밀키가 필요하다. API는 별도로 저장 프로젝트 잠금/If-Match/스냅샷을 처리한다. token은 승인된 후보를 암호화하지 않으며 키와 저장 경계가 로컬 trust boundary다. 클라이언트 verdict, approved=true 또는 client inventory는 신뢰하지 않는다.
- `preview_evidence_migration`/`apply_evidence_migration`은 별도 typed request의 evidence_id, old_evidence_fingerprint, new_selection(같은 ID), expected_source_fingerprint를 검증한다. 이동할 근거 이외의 등록 근거는 현재 원문이어야 한다. 대상의 이전 발췌 whole hash가 바뀌었어도 명시적 이동은 가능하며 old evidence 객체 SHA가 현재 저장본과 같아야 한다. 새 발췌는 서버가 current source에서 materialize한다. 주장/비교/산식/도식의 IDs와 연결은 보존한다. 계산 결과는 새 선택으로 다시 계산한다. 의미가 같은 근거라는 자동 승인은 하지 않는다.
- 후보에 document_review(reason/document replacement 또는 evidence migration, base fingerprint, changed paths, requires_independent_review=true)를 서버가 기록한다. 일반 후보가 이 server marker를 임의 변경하지 못하게 하고 새로운 변경 때 새 marker로 갱신한다. 레거시 필드 부재는 기존 dump/fingerprint를 보존한다. 현재 bytes의 Q4 실제 native render+독립 서명 검수가 제출 경계이며 marker 자체는 승인 기록이 아니다.
- GenerateDiagramRequest는 mode=create(default)/replace를 구분한다. replace는 기존 diagram 장만, 동일 role/claim_ids만, 현재 계획/근거만 허용한다. 기존 도식 의미 입력은 참고 데이터로 전송하되 보호 장부는 AI가 수정하지 않는다. 생성은 후보만 반환하며 기존 저장본에 덮어쓰지 않는다. 적용은 위 전체 문서 confirmation flow로 수행한다. format retry 포함 기존 호출 상한을 유지한다.

## 제한과 검증

후보/변경 inventory 최대 JSON 1MiB, 항목 1000개. 전체 source fingerprint는 `sources_fingerprint` 기존 함수와 동일하다. HMAC은 canonical JSON UTF8(sort keys, compact separators, no NaN)으로 exact payload를 서명한다. base 변경/source 변경/candidate 변경/token 변조/ack 누락·중복·추가/보호 그래프 수정/old evidence 변경/new excerpt 위조를 실패 테스트로 만든다. preview/apply 자체는 파일/네트워크 I/O가 없다. 실제 AI 생성·Windows PowerPoint·독자 품질은 미검증으로 보존한다.

독립 계획 검토는 `review/document-change-plan-independent-review.md`에 남겼다. 보호 claim에 새 비교/보호 비교에 새 산식을 붙이는 변경도 일반 교체에서 차단한다. 기존 도식 교체의 evidence refs는 원래 보호 장부 범위로 제한한다. 기존 수동 도식 프로젝트의 cover/divider 장은 장별 plan assignment가 없어도 허용하며 모든 본문 장은 연결되어야 한다. 장별 source_refs와 plan 순서는 서버가 계산하고 이 변경도 inventory에 포함한다.

명시적 근거 이동은 대상의 과거 전체 원문을 복원하지 않는다. 따라서 대상 원문이 바뀐 경우 이전 input_fingerprint의 의미 현재성을 재증명하지 않는다. 저장된 old Evidence 객체 SHA, 나머지 모든 등록 근거의 현재성, 새 자료 전체 fingerprint와 새 발췌를 확인하고 사용자에게 전체 변경을 다시 확인받아 새 후보 fingerprint를 부여하는 절차다. 같은 자료의 여러 근거가 낡았다면 한 근거씩 이동하는 계약은 거절한다. 자동 의미 승인, 일괄 stale 근거 이동, 보호 장 삭제는 미지원이다.

구현 독립 검토에서 일반 후보의 numeric substring 근거와 보호 도식→일반 본문 전환 이후 두 번째 후보에서 보호 장부를 바꾸는 반례를 발견해 수정했다. 일반 후보의 수치 근거도 전체 원문 토큰을 검증한다. 보호 도식 template 종류, 보호 chart의 존재/등록 comparison ID를 일반 교체에서 제거할 수 없으며 본문 도식 내용 교체와 bar/column 종류 변경은 가능하다. 이 제한은 명시적 whole-document replacement 함수 경계다. 기존 일반 편집의 표현 토글을 영속 보호 레지스트리로 확장하지는 않는다.

추가 독립 반례에서는 claim에 연결되지 않고 도식 node/edge만 참조하는 근거를 첫 후보에서 제거하면 다음 후보에서 보호 범위가 줄었다. 기존 도식의 evidence refs 전체 합집합을 교체 도식에 보존하도록 제한했다. 생성 replace는 기존 claim 범위와 원래 도식 refs의 현재 등록 발췌만 전송하며 적용 후보가 실제 ref 보존 계약을 지키는지는 확인 flow에서 다시 검사한다. 참조를 없애는 도식 교체는 이 계약에서 미지원이다.
