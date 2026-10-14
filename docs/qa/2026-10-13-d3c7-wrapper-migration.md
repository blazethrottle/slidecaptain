# D3c-7 동기 생성 래퍼 제거: 시험 이전 대응표 (2026-10-13)

계획 `docs/plans/2026-10-13-revision-d3c-direct-edit.md` 4.9의 대응표다. 동기 생성 래퍼 여섯(구조안, 장 생성, 장 축약, 도식, 재작성, 구조 수리)은 등록하고 끝날 때까지 기다린 뒤 결과를 응답으로 돌려줬다. 이를 지우면서 래퍼를 부르던 시험을 작업 API(`POST /api/projects/{name}/jobs`와 `GET .../jobs/{id}`)로 옮겼다. 이 표는 시험마다 래퍼 단언이 작업 API의 어디로 갔는지 보여 주며, 단언이 약해진 이전이 없는지 리뷰하는 근거다.

## 세는 방법과 결과

- 계측: TestClient 전송 계층을 감싼 pytest 플러그인(`~/Projects/slidecaptain-work/d3c7-probe/wrapper_probe.py`, 계획 리뷰 S14의 것과 같다)으로 백엔드 전체 시험을 돌려 래퍼 경로 POST를 시험별로 기록했다.
- 제거 전(`89d137e`): 호출 238회, 시험 188개, 파일 22개(도식 65, 구조안 63, 장 생성 44, 재작성 42, 장 축약 20, 수리 4).
- 제거 뒤: 호출 0회. 문자열 검색이 아니라 같은 계측으로 판정했다(계획 4.9).
- 계측 밖: `httpx.ASGITransport`로 부르던 시험 3개(매개변수 포함 6경우)는 아래 "지운 시험"에 있다.
- 이전 도우미: `backend/tests/job_runs.py`. `post_generation`은 옛 래퍼 경로와 본문을 작업 등록으로 바꾸고 결과를 범주로 나눈다. 범주는 시험 실행 중 기록하고(`D3C7_MIGRATION_OUT`), 이 표는 그 기록과 제거 전 계측을 시험 단위로 맞대어 만들었다(`build_table.py`). 맞댄 결과, 등록 거절과 실행 실패에서 옛 응답 상태와 새 자리의 상태가 다른 호출은 0건이다.

## 범주

| 범주 | 래퍼에서 | 작업 API에서 보는 자리 |
|---|---|---|
| ① 등록 검사 | 404, 409, 422, 428 응답 | 등록 응답의 같은 상태와 본문, 행이 생기지 않음 |
| ② 실행 중 실패 | 응답 상태와 `code`, 형식 오류는 200과 `status: format_error` | 종결 행의 `state: failed`, `error.status`, `error.code`, `error.detail`. 형식 오류는 `error_class: ai_output`이고 AI 응답 원문과 사용량은 원장의 결과(`format_error_result`) |
| ③ 생성 뒤 판정 | 기준이 바뀌면 412나 409 | `state: succeeded`, `candidate_status: stale`(자료를 읽지 못하면 판정을 미뤄 `held`), `stale_reasons`의 구체 사유(`stale_result`). 재작성은 그 결과의 반영도 같은 이유로 거절됨을 함께 본다 |
| 성공 | 200과 결과 | `state: succeeded`, 후보 `held`, 원장의 결과(`JobView.result`) |

래퍼가 같이 고정한 부수 단언(제공자 호출 수, 사용량 기록, 저장본과 스냅샷 불변, 성공 시각 기록 여부)은 시험에 그대로 남겼다.

형식 오류의 원장 오류에는 상태가 없다(`error.status`가 `null`). 처음 판에 "② failed(500)"으로 적은 500은 도우미의 대체값이었고, 화면의 `jobResult`는 결과가 있으면 형식 오류 결과를 돌려주므로 500을 보지 않는다(D3c-7 리뷰 H7).

D3c-7 리뷰 반영(H1, H2)부터 아래 표의 "행 없음"과 "성공 held"는 기록의 관측이 아니라 도우미의 단언이다. `run_job`은 등록이 거절되면 작업 목록이 그대로인지 보고, `post_generation`은 실행 단계의 4xx 실패를 `expect="run_failure"`를 넘긴 시험만 받으며(3곳), 성공은 후보 `held`와 빈 사유일 때만 받는다(낡은 후보와 판정 불가를 기대하는 15곳은 `expect="stale"`). 등록 단계 503 세 곳은 실행 단계 503과 상태가 같아 `run.rejected`를 직접 본다.

## 지운 시험 (래퍼에만 있던 성질)

| 시험 | 성질 | 이유 |
|---|---|---|
| `test_ai_connections.py::test_request_cancelled_during_login_check_releases_generation_lease`(4경우) | 요청이 취소되면 작업에 취소를 보내고 임대를 푼다 | 요청과 작업을 묶던 래퍼가 없다. 작업 취소는 작업 API의 취소 시험이 지킨다 |
| `test_ai_connections.py::test_request_cancelled_during_generation_releases_lease` | 같다 | 같다 |
| `test_jobs_api.py::test_wrapper_cancelled_during_registration_cancels_the_job` | 등록 중 요청 취소가 만들어진 작업을 취소한다 | 같다 |
| `test_jobs_api.py::test_wrapper_marks_its_result_delivered_and_lists_stay_short` | 래퍼가 돌려준 결과를 `delivered`로 기록한다 | `delivered`를 쓰는 주체가 없다. 원장은 이전 빌드의 행을 읽으려고 값과 전이를 남긴다 |
| `test_jobs_candidates.py::test_stale_chapter_result_returned_by_the_wrapper_is_delivered` | 낡은 장 결과도 돌려주면 `delivered` | 같다. 장 결과의 낡음 판정은 `test_chapter_candidate_is_judged_by_its_own_inputs`가 지킨다 |
| `test_jobs_api.py::test_ledger_write_failures_keep_the_result_for_the_wrapper[everything]` | 원장이 모두 고장 나도 래퍼가 결과를 응답으로 돌려준다 | 결과를 응답으로 돌려줄 래퍼가 없다. 나머지 두 경우는 "원장 실패로 끝난다"는 작업 API 성질로 남겼다 |
| `test_job_steps.py::test_the_sync_structure_route_records_the_same_steps` | 동기 래퍼도 같은 실행 단계를 남긴다 | 같은 성질을 작업 API로 `test_steps_move_from_generating_to_retrying_format_and_clear_at_the_end`가 지킨다 |

## 시험 밖 소비자

`backend/scripts/quality_pilot.py`의 래퍼 호출 둘(장 생성, 재작성 미리 보기)을 작업 API로 옮겼다. 작업 함수는 등록하고 300초(화면의 "최대 5분" 안내와 같다)까지 조회하며, 결과 없이 끝나면 멈춘다. 재작성은 래퍼가 막던 "만드는 동안 기준이 바뀐 후보"를 후보 상태(`held`가 아니면 멈춤)로 확인한다. 호출 수 상한은 제공자를 감싼 `BudgetedProvider`가 세므로 뜻이 바뀌지 않는다. 품질 파일럿 시험 35건(상한 공유, 형식 재시도, 상한 중단 시험 포함)이 통과한다.

## 대응표

| 시험 | 래퍼 호출(종류, 상태) | 작업 API에서 보는 자리 |
|---|---|---|
| `test_ai_connections.py::test_api_selection_consent_and_both_routes` | structure 409, structure 200, structure 409, structure 200 | ① 등록 409, 행 없음; 성공 held; ① 등록 409, 행 없음; 성공 held |
| `test_api_generate.py::test_condense_chapter_endpoint` | condense 200 | 성공 held |
| `test_api_generate.py::test_condense_chapter_template_mismatch_422` | condense 422 | ① 등록 422, 행 없음 |
| `test_api_generate.py::test_condense_chapter_without_ai_consent_header_428` | condense 428 | ① 등록 428, 행 없음 |
| `test_api_generate.py::test_condense_chapter_writes_usage_record` | condense 200 | 성공 held |
| `test_api_generate.py::test_generate_chapter_ok` | chapter 200 | 성공 held |
| `test_api_generate.py::test_generate_chapter_unknown_chapter_404` | chapter 404 | ① 등록 404, 행 없음 |
| `test_api_generate.py::test_generate_chapter_with_format_retry_writes_usage_record` | chapter 200 | 성공 held |
| `test_api_generate.py::test_generate_chapter_without_ai_consent_header_428` | chapter 428 | ① 등록 428, 행 없음 |
| `test_api_generate.py::test_generate_ok_even_if_usage_log_write_fails` | structure 200 | 성공 held |
| `test_api_generate.py::test_generate_structure_returns_draft_without_saving` | structure 200 | 성공 held |
| `test_api_generate.py::test_generate_structure_with_ai_consent_header_passes` | structure 200 | 성공 held |
| `test_api_generate.py::test_generate_structure_without_ai_consent_header_428` | structure 428 | ① 등록 428, 행 없음 |
| `test_api_generate.py::test_generate_structure_without_model_writes_none_requested_model` | structure 200 | 성공 held |
| `test_api_generate.py::test_generate_structure_without_sources_422` | structure 422 | ① 등록 422, 행 없음 |
| `test_api_generate.py::test_generate_structure_writes_usage_record` | structure 200 | 성공 held |
| `test_api_generate.py::test_generate_without_any_marker_headers_is_403_not_428` | structure 403 | ① 등록 403, 행 없음 |
| `test_api_generate.py::test_generate_without_provider_returns_503` | structure 503 | ① 등록 503, 행 없음 |
| `test_api_generate.py::test_provider_failure_returns_503` | chapter 503 | ② failed(503) |
| `test_api_generate.py::test_provider_failure_writes_failed_usage_record` | chapter 503 | ② failed(503) |
| `test_api_generate.py::test_sources_over_total_limit_422` | structure 422 | ① 등록 422, 행 없음 |
| `test_api_generate.py::test_target_chapters_zero_422` | structure 422 | ① 등록 422, 행 없음 |
| `test_api_generate.py::test_usage_log_has_no_content_leak` | structure 200, chapter 200, chapter 503 | 성공 held; 성공 held; ② failed(503) |
| `test_api_status.py::test_status_not_updated_when_generation_fails` | structure 503 | ② failed(503) |
| `test_api_status.py::test_status_records_last_success_after_chapter_generation` | chapter 200 | 성공 held |
| `test_api_status.py::test_status_records_last_success_after_condense` | condense 200 | 성공 held |
| `test_api_status.py::test_status_records_last_success_after_structure_generation` | structure 200 | 성공 held |
| `test_api_upload.py::test_generated_route_reads_xlsx_extract_as_source` | structure 200 | 성공 held |
| `test_candidate_relevance.py::test_structure_registration_rejects_a_brief_that_differs_from_the_report_info` | structure 422 | ① 등록 422, 행 없음 |
| `test_derived_values.py::test_api_save_restore_generate_and_condense_carry_calculation[False]` | structure 200, chapter 200, condense 200 | 성공 held; 성공 held; 성공 held |
| `test_derived_values.py::test_api_save_restore_generate_and_condense_carry_calculation[True]` | structure 200, chapter 200, condense 200 | 성공 held; 성공 held; 성공 held |
| `test_derived_values.py::test_changed_formula_blocks_external_calls_but_preserves_edit[condense]` | structure 200, condense 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_derived_values.py::test_changed_formula_blocks_external_calls_but_preserves_edit[generate]` | structure 200, chapter 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_derived_values.py::test_number_warning_uses_only_computed_values_in_generation_and_condense[False]` | structure 200, chapter 200, condense 200 | 성공 held; 성공 held; 성공 held |
| `test_derived_values.py::test_number_warning_uses_only_computed_values_in_generation_and_condense[True]` | structure 200, chapter 200, condense 200 | 성공 held; 성공 held; 성공 held |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[blank-topic]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[cover-role]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[divider-role]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[duplicate-claims]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[existing-cover]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[existing-diagram]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[forged-deck]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[forged-evidence]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[forged-nodes]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[invalid-claim]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[invalid-id]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[long-instructions]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[long-topic]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[no-claims]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_bad_request_is_rejected_before_provider[unknown-claim]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_candidate_enters_existing_manual_validation_and_save_path[False]` | diagram 200 | 성공 held |
| `test_diagram_generation.py::test_candidate_enters_existing_manual_validation_and_save_path[True]` | diagram 200 | 성공 held |
| `test_diagram_generation.py::test_changes_during_lease_acquisition_do_not_reach_provider[deck]` | diagram 412 | ② failed(412) |
| `test_diagram_generation.py::test_changes_during_lease_acquisition_do_not_reach_provider[source]` | diagram 409 | ② failed(409) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[add_source]` | diagram 409 | ③ succeeded, stale(sources_changed) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[deck]` | diagram 412 | ③ succeeded, stale(deck_changed) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[deck_invalid]` | diagram 412 | ③ succeeded, stale(unknown_deck) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[remove_all_sources]` | diagram 409 | ③ succeeded, stale(sources_changed) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[remove_source]` | diagram 409 | ③ succeeded, stale(sources_changed) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[source]` | diagram 409 | ③ succeeded, stale(sources_changed) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[source_invalid]` | diagram 409 | 성공 held(unknown_sources) |
| `test_diagram_generation.py::test_changes_while_awaiting_provider_discard_candidate[source_too_large]` | diagram 409 | 성공 held(unknown_sources) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[claim_ids]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[coordinates]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[cycle]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[duplicate_edge]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[duplicate_node]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[fixed_id]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[missing_relation_support]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[missing_uncertainty]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[new_evidence]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[no_edges]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[no_nodes]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[not_selected]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[role]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[unknown_evidence]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_invalid_ai_output_retries_once_and_preserves_saved_deck[unknown_node]` | diagram 200 | ② failed(ai_output, 상태 없음) |
| `test_diagram_generation.py::test_numbers_only_use_selected_registered_excerpts` | diagram 200 | 성공 held |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[absent-422]` | diagram 422 | ① 등록 422, 행 없음 |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[forged_excerpt-409]` | diagram 409 | ① 등록 409, 행 없음 |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[forged_hash-409]` | diagram 409 | ① 등록 409, 행 없음 |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[forged_locator-409]` | diagram 409 | ① 등록 409, 행 없음 |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[source_added-409]` | diagram 409 | ① 등록 409, 행 없음 |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[source_changed-409]` | diagram 409 | ① 등록 409, 행 없음 |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[source_deleted-409]` | diagram 409 | ① 등록 409, 행 없음 |
| `test_diagram_generation.py::test_plan_and_actual_source_must_be_current_before_provider[stale-409]` | diagram 409 | ① 등록 409, 행 없음 |
| `test_diagram_generation.py::test_preview_returns_server_owned_spec_without_saving_or_sending_other_context` | diagram 200 | 성공 held |
| `test_diagram_generation.py::test_provider_failure_records_usage_without_saving[1]` | diagram 503 | ② failed(503) |
| `test_diagram_generation.py::test_provider_failure_records_usage_without_saving[2]` | diagram 503 | ② failed(503) |
| `test_diagram_generation.py::test_required_gates_precede_generation[If-Match-428]` | diagram 428 | ① 등록 428, 행 없음 |
| `test_diagram_generation.py::test_required_gates_precede_generation[X-AI-Consent-428]` | diagram 428 | ① 등록 428, 행 없음 |
| `test_diagram_generation.py::test_required_gates_precede_generation[X-Requested-With-403]` | diagram 403 | ① 등록 403, 행 없음 |
| `test_diagram_generation.py::test_retry_success_preserves_unknown_usage_and_does_not_normalize_text` | diagram 200 | 성공 held |
| `test_diagram_generation.py::test_selection_consent_and_etag_gate_before_lease_and_release` | diagram 412, diagram 409, diagram 409, diagram 200 | ① 등록 412, 행 없음; ① 등록 409, 행 없음; ① 등록 409, 행 없음; 성공 held |
| `test_diagram_generation.py::test_stale_etag_precedes_generation_setup` | diagram 412 | ① 등록 412, 행 없음 |
| `test_failure_bodies.py::test_failure_bodies_match_the_fixture_the_screen_tests_use` | structure 428, structure 503, structure 409, structure 503, structure 503 | ① 등록 428, 행 없음; ① 등록 503, 행 없음; ① 등록 409, 행 없음; ② failed(503); ② failed(503) |
| `test_job_steps.py::test_the_sync_structure_route_records_the_same_steps` | structure 200 | 삭제(래퍼 전용 성질) |
| `test_jobs_api.py::test_expired_login_makes_no_call[False-503]` | structure 503 | ② failed(503) |
| `test_jobs_api.py::test_expired_login_makes_no_call[True-409]` | structure 409 | ② failed(409) |
| `test_jobs_api.py::test_ledger_write_failures_keep_the_result_for_the_wrapper[everything]` | structure 200 | 삭제(래퍼 전용 성질) |
| `test_jobs_api.py::test_ledger_write_failures_keep_the_result_for_the_wrapper[succeeded]` | structure 200 | 이름 변경 `test_ledger_write_failures_end_the_job_as_a_ledger_failure[succeeded]`: ② failed(ledger), run_job |
| `test_jobs_api.py::test_ledger_write_failures_keep_the_result_for_the_wrapper[validating]` | structure 200 | 이름 변경 `test_ledger_write_failures_end_the_job_as_a_ledger_failure[validating]`: ② failed(ledger), run_job |
| `test_jobs_api.py::test_provider_is_not_called_when_the_send_time_cannot_be_written` | structure 503 | ② failed(503) |
| `test_jobs_api.py::test_record_success_uses_the_fixed_model` | structure 200 | 성공 held |
| `test_jobs_api.py::test_unreadable_ledger_blocks_only_generation` | structure 503 | ① 등록 503, 행 없음 |
| `test_jobs_api.py::test_wrapper_marks_its_result_delivered_and_lists_stay_short` | structure 200, structure 200, structure 200, structure 200 | 삭제(래퍼 전용 성질) |
| `test_jobs_api.py::test_wrapper_result_is_also_kept_in_the_ledger` | structure 200 | 성공 held |
| `test_jobs_candidates.py::test_remote_sent_time_is_recorded_only_when_the_provider_is_called` | chapter 404 | run_job: 성공한 작업의 원격 호출 시각(없는 장 404는 등록 검사라 행이 없다) |
| `test_jobs_candidates.py::test_repair_result_is_stopped_in_the_ledger_and_the_response_when_the_deck_changes` | repair 200 | ③ succeeded, stale(deck_changed) |
| `test_jobs_candidates.py::test_sources_changed_while_drawing_keep_the_candidate_as_stale` | diagram 409 | ③ succeeded, stale(sources_changed) |
| `test_jobs_candidates.py::test_stale_chapter_result_returned_by_the_wrapper_is_delivered` | chapter 200 | 삭제(래퍼 전용 성질) |
| `test_jobs_candidates.py::test_unreadable_basis_after_drawing_is_not_delivered` | diagram 409 | 이름 변경 `test_unreadable_basis_after_drawing_keeps_the_candidate_held`: 성공 held(unknown_sources) |
| `test_jobs_error_codes.py::test_generation_with_a_missing_cli_records_provider_missing_not_login_required` | structure 503 | ② failed(503) |
| `test_jobs_error_codes.py::test_registration_selection_change_puts_the_code_in_the_body` | structure 409 | ① 등록 409, 행 없음 |
| `test_jobs_error_codes.py::test_wrapped_generation_connection_errors_put_the_code_in_the_body` | structure 503 | ② failed(503) |
| `test_metric_comparison.py::test_comparison_api_save_reload_and_generation_context` | structure 200, chapter 200, condense 200, chapter 409, condense 409 | 성공 held; 성공 held; 성공 held; ① 등록 409, 행 없음; ① 등록 409, 행 없음 |
| `test_numeric_review.py::test_generation_and_condense_use_canonical_expressions_without_new_calls[condense]` | condense 200 | 성공 held |
| `test_numeric_review.py::test_generation_and_condense_use_canonical_expressions_without_new_calls[generate]` | chapter 200 | 성공 held |
| `test_project_diagrams.py::test_diagram_generation_rejected_before_provider_setup[generate/chapter/cover/condense]` | condense 422 | ① 등록 422, 행 없음 |
| `test_project_diagrams.py::test_diagram_generation_rejected_before_provider_setup[generate/chapter/synthetic-flow/condense]` | condense 422 | ① 등록 422, 행 없음 |
| `test_project_diagrams.py::test_diagram_generation_rejected_before_provider_setup[generate/chapter/synthetic-flow]` | chapter 422 | ① 등록 422, 행 없음 |
| `test_project_diagrams.py::test_whole_structure_generation_cannot_replace_diagram_ledger` | structure 422 | ① 등록 422, 행 없음 |
| `test_quality_pilot.py::test_condense_budget_stop_is_not_hidden_by_successful_draft` | chapter 200 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot.py::test_format_retries_share_one_budget_and_leave_original_draft` | chapter 503 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot.py::test_journal_failure_after_response_stops_next_dispatch` | chapter 500 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot.py::test_offline_never_touches_real_connection` | chapter 200, rewrite 200 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot.py::test_offline_roundtrip_exports_three_editable_slides_and_preserves_rewrite` | chapter 200, rewrite 200 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot.py::test_pilot_connection_enforces_consent_and_selection_before_calls[headers0-409]` | chapter 409 | ① 등록 409, 행 없음 |
| `test_quality_pilot.py::test_pilot_connection_enforces_consent_and_selection_before_calls[headers1-409]` | chapter 409 | ① 등록 409, 행 없음 |
| `test_quality_pilot.py::test_pilot_connection_enforces_consent_and_selection_before_calls[headers2-428]` | chapter 428 | ① 등록 428, 행 없음 |
| `test_quality_pilot.py::test_provider_failure_records_unavailable_usage_without_raw_exception` | chapter 503 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot.py::test_rewrite_budget_stop_keeps_generated_body` | chapter 200, rewrite 503 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot.py::test_two_format_failures_do_not_start_rewrite` | chapter 200 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot_selection.py::test_cli_selection_without_live_mode_never_opens_a_connection[claude-sonnet-offline]` | chapter 200, rewrite 200 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot_selection.py::test_cli_selection_without_live_mode_never_opens_a_connection[codex-gpt-6-luna-offline]` | chapter 200, rewrite 200 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot_selection.py::test_codex_budget_remains_shared_between_chapter_and_rewrite` | chapter 200, rewrite 503 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot_selection.py::test_live_codex_uses_selected_profile_and_never_falls_back[False-models1-0-blocked]` | chapter 503 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot_selection.py::test_live_codex_uses_selected_profile_and_never_falls_back[True-models0-2-completed]` | chapter 200, rewrite 200 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_quality_pilot_selection.py::test_live_codex_uses_selected_profile_and_never_falls_back[True-models2-0-blocked]` | chapter 503 | 품질 파일럿 스크립트의 작업 API(작업 함수) |
| `test_story_plan.py::test_api_save_reload_edit_and_condense_preserve_plan` | structure 200, chapter 200, condense 200 | 성공 held; 성공 held; 성공 held |
| `test_story_plan.py::test_blank_question_is_rejected_before_provider` | structure 422 | ① 등록 422, 행 없음 |
| `test_story_plan.py::test_planned_request_still_requires_ai_consent` | structure 428 | ① 등록 428, 행 없음 |
| `test_story_plan.py::test_snapshot_restore_preserves_binding_and_detects_later_source_changes` | structure 200, chapter 200, chapter 409 | 성공 held; 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[condense-meta]` | structure 200, condense 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[condense-plan]` | structure 200, condense 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[condense-source]` | structure 200, condense 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[condense-structure]` | structure 200, condense 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[generate-meta]` | structure 200, chapter 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[generate-plan]` | structure 200, chapter 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[generate-source]` | structure 200, chapter 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan.py::test_stale_plan_is_preserved_but_blocks_generation_before_provider[generate-structure]` | structure 200, chapter 409 | 성공 held; ① 등록 409, 행 없음 |
| `test_story_plan_rewrite.py::test_apply_revalidates_candidate[fingerprint]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_apply_revalidates_candidate[meta]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_apply_revalidates_candidate[review]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_apply_revalidates_candidate[slide]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_apply_revalidates_candidate[topic]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_apply_twice_rejects_second_attempt_and_preserves_one_snapshot` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_apply_without_etag_is_rejected` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_bad_ai_output_is_retried_once_without_saving[claim]` | rewrite 200 | ② failed(ai_output, 상태 없음) |
| `test_story_plan_rewrite.py::test_bad_ai_output_is_retried_once_without_saving[duplicate]` | rewrite 200 | ② failed(ai_output, 상태 없음) |
| `test_story_plan_rewrite.py::test_bad_ai_output_is_retried_once_without_saving[evidence]` | rewrite 200 | ② failed(ai_output, 상태 없음) |
| `test_story_plan_rewrite.py::test_bad_ai_output_is_retried_once_without_saving[invented]` | rewrite 200 | ② failed(ai_output, 상태 없음) |
| `test_story_plan_rewrite.py::test_bad_ai_output_is_retried_once_without_saving[missing]` | rewrite 200 | ② failed(ai_output, 상태 없음) |
| `test_story_plan_rewrite.py::test_bad_ai_output_is_retried_once_without_saving[role]` | rewrite 200 | ② failed(ai_output, 상태 없음) |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[after-add_source]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[after-deck]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[after-remove_source]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[after-source]` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[during-add_source]` | rewrite 409 | ③ succeeded, stale(sources_changed) |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[during-deck]` | rewrite 412 | ③ succeeded, stale(deck_changed) |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[during-remove_source]` | rewrite 409 | ③ succeeded, stale(sources_changed) |
| `test_story_plan_rewrite.py::test_changed_base_cannot_apply[during-source]` | rewrite 409 | ③ succeeded, stale(sources_changed) |
| `test_story_plan_rewrite.py::test_new_rewrite_text_is_normalized_but_protected_claim_is_preserved` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_overlong_context_blocks_before_ai` | rewrite 422 | ① 등록 422, 행 없음 |
| `test_story_plan_rewrite.py::test_preview_apply_preserves_edits_and_keeps_old_snapshot` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_preview_requires_all_gates[If-Match-428]` | rewrite 428 | ① 등록 428, 행 없음 |
| `test_story_plan_rewrite.py::test_preview_requires_all_gates[X-AI-Consent-428]` | rewrite 428 | ① 등록 428, 행 없음 |
| `test_story_plan_rewrite.py::test_preview_requires_all_gates[X-Requested-With-403]` | rewrite 403 | ① 등록 403, 행 없음 |
| `test_story_plan_rewrite.py::test_preview_stale_or_missing_base_never_calls_provider` | rewrite 412 | ① 등록 412, 행 없음 |
| `test_story_plan_rewrite.py::test_protected_source_change_blocks_before_ai[append]` | rewrite 409 | ① 등록 409, 행 없음 |
| `test_story_plan_rewrite.py::test_protected_source_change_blocks_before_ai[delete]` | rewrite 409 | ① 등록 409, 행 없음 |
| `test_story_plan_rewrite.py::test_protected_source_change_blocks_before_ai[move]` | rewrite 409 | ① 등록 409, 행 없음 |
| `test_story_plan_rewrite.py::test_rewrite_checks_numbers_in_caveats_and_unanswered_questions` | rewrite 200 | 성공 held |
| `test_story_plan_rewrite.py::test_usage_records_rewrite_and_format_retry_without_source_text` | rewrite 200 | ② failed(ai_output, 상태 없음) |
| `test_story_repair.py::test_api_requires_consent_etag_and_never_saves_candidate` | repair 428, repair 428, repair 200 | ① 등록 428, 행 없음; ① 등록 428, 행 없음; 성공 held |
| `test_story_rewrite_edits.py::test_api_retries_invalid_edits_then_applies_without_saving_preview[answer_role]` | rewrite 200 | 성공 held |
| `test_story_rewrite_edits.py::test_api_retries_invalid_edits_then_applies_without_saving_preview[protected_echo]` | rewrite 200 | 성공 held |
| `test_usage_missing_values.py::test_sdk_to_api_retry_and_jsonl_match_shared_frontend_fixture` | structure 200 | 성공 held |
