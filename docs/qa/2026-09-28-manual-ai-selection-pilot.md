# 직접 모델 선택과 합성 보고서 실제 호출 검증

작성: 2026-09-28. 실행 환경: macOS, 기존 개발 의존성을 공유한 격리 작업본. 백엔드는 작업본을 `PYTHONPATH`로 명시했다. [인계](../handoffs/2026-09-28-manual-ai-selection-handoff.md)의 검증 근거다.

로컬 증거 루트: `~/Projects/slidecaptain-work/live-pilot-20260928-cygnfscx/`. 생성 PPTX, 인증 프로필과 원시 사용량 자료는 공개 저장소에 넣지 않는다.

## 실행과 산출물

| 실행 | 증거 | 관측 |
| --- | --- | --- |
| Sonnet 실제 호출 | `live/report.json`, `live/usage-summary.json` | 2회, 완료. 장 생성/계획 재작성/초안 내보내기 |
| LUNA 실제 호출 | `live-codex/report.json`, `rewrite-result.json` | 3회, 재작성에서 차단. 장 생성 성공 |
| LUNA 무호출 원인 재현 | `live-codex/rejection-replay.json` | 보호 도식 주장 연결 변경 거절. 추가 호출 0회 |
| Sonnet 초안 | `live/projects/quality-pilot/exports/합성 도식 보고_v001.pptx`와 같은 버전 quality.json | 3장, 도식은 편집 가능한 도형. 품질 상태 draft |
| 화면 | `browser/model-selection-final.png`, `cover-fixed.png`, `action-fixed.png`, `diagram-fixed.png`, `diagram-dialog-fixed.png` | 선택 저장/복원/연결과 하단 표시 확인 |

Sonnet 실행 기록의 후보 무저장, 본문 보존, 슬라이드 수, 산출물 해시, 편집 가능한 도식과 final 거절 6항목을 확인했다. LUNA는 후보 생성 단계에서 실패해 같은 6항목 전체 완료로 세지 않는다. 별도 JSON 전체 내용 대조에서 LUNA 재작성 전 덱과 실패 후 저장본이 같았다. 입력 기록에는 줄 끝 개행 한 바이트가 더 있어 원시 바이트 동일로 기록하지 않는다. 증거는 `logs/luna-preservation.json`이다.

원시 실행 report의 browser/semantic/powerpoint/reader 값은 실행 시점의 `not_run`으로 보존한다. 후속 Chrome 검증은 이 문서와 별도 browser 증거에 기록하며 AI 실행 기록을 사후 덮어쓰지 않는다.

## 사용량

앱의 호출 기록을 합산한 값이다. SDK가 보고하지 않은 값은 0으로 추정하지 않는다.

| 모델 | 입력 토큰 | 출력 토큰 | 캐시 읽기 | 캐시 생성 | 호출 시간 합계 ms | SDK 턴 | SDK 비용 USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| claude-sonnet-5 | 9,866 | 6,557 | 0 | 182,910 | 63,718 | 5 | 0.806842 |
| gpt-6-luna | 31,813 | 1,377 | 0 | 0 | 65,260 | 3 | 미제공 |

Sonnet SDK 보고 비용은 실제 구독 청구액이 아니다. 두 실행의 턴, 캐시 및 완료 범위가 달라 토큰/시간으로 비용이나 품질 우위를 판단하지 않는다. 원시 SDK 결측 정규화를 독립 계측한 결과도 아니다.

## 자동 검사와 독립 리뷰

| 대상 | 결과 | 증거 |
| --- | --- | --- |
| 백엔드 전체 | 1,615 통과 / Windows 전용 1 미실행 | `logs/backend-full.log` |
| 프런트 전체 | 410 통과 / 38파일 | `logs/frontend-full-final.log` |
| tsc / Vite | 통과 | `logs/frontend-build-final.log` |
| OpenAPI / 생성 타입 | 기준 파일과 바이트 일치 | 로그와 현재 파일 대조 |
| 공개 저장소 감사 | 발견 0건 | 감사기 실행 결과 |
| 선택 기능 계획 / 구현 | 필수 수정 0건 | `review/plan-review.md`, `review/implementation-review.md` |
| Preview 추가 계획 / 구현 | 필수 수정 0건 | `review/preview-clipping-review.md`, `review/preview-clipping-implementation-review.md` |

신규 선택 테스트는 백엔드 13개/프런트 4개다. 구현 전 실패를 확인했고 정상 선택뿐 아니라 미인증/모델 누락/공유 예산/실패 후 자원 정리/미저장 상태/생성 중 잠금을 확인했다. 독립 모의 반례 7개는 정식 테스트 합계에 더하지 않는다.

## 화면 검사와 한계

수정 전 1364px 너비 미리보기의 캔버스는 767.25px인데 holder는 540px여서 하단 227.25px가 잘렸다. `browser/preview-red.json`에 포함 검사 실패를 남겼다. 높이 보정 후 표지/일반 장/도식 3개에서 캔버스와 holder가 일치하고 작성창의 620px 캔버스도 348.75px 높이 안에 들어온다. `browser/preview-checks.json`의 4개 중 실패 0개다.

viewport 도구는 설정을 수락했으나 실제 1920px 창이 바뀌지 않았다. 해당 중간 스크린샷 `diagram-half-scale.png`는 축소 증거가 아니며 통과 집계에서 제외했다. 임시 viewport 설정은 reset했다. 작성창은 실제로 축소된 별도 사례다. 창 resize/480px 검증으로 일반화하지 않는다.

PowerPoint 설치가 없고 Keynote 접근은 시간 초과로 검사하지 못했다. 목표 앱에서의 렌더/편집, 독자 평가와 품질 승인은 미완료다. Chrome의 각주/결론 표시 수정으로 제출 가능한 보고서라고 판정하지 않는다.
