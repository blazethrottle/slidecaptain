# Claude·ChatGPT 연결과 모델 선택 인계

작성일: 2026-09-13. 사용자 요청: 브라우저 기반 구독 로그인·연결과 모델 선택 UI를 확인하고 Claude와 ChatGPT를 모두 지원하도록 구현과 서비스 설계를 보완한다.

## 완료한 범위

- 프로젝트 목록과 프로젝트 안에 **AI 연결 및 모델** 화면을 추가했다. 서비스별 로그인 상태, 로그인 시작·취소·재확인, 모델 목록과 선택 저장을 제공한다.
- Claude는 본인용 공식 Claude Code 브라우저 로그인을 실행한다. 로그인 상태와 생성에 같은 네이티브 CLI를 사용한다. 기존 Windows 전용 재실행 안내를 제거했다.
- ChatGPT는 공식 Codex app-server로 인증과 모델 목록을 조회하고 구조화 생성을 호출한다. 기존 Codex 계정 파일을 읽거나 복사하지 않고 별도 프로필을 사용한다.
- 두 제공자는 기존 `complete(prompt, schema)`와 동일한 품질 파이프라인을 사용한다. OpenAI의 구조화 출력 규약에 맞춘 전송 스키마 변환을 추가하고 원래 데이터 모델은 유지했다.
- provider/model만 로컬 설정에 저장한다. 생성 시 확인한 선택 식별값을 서버에 보내며, 다른 탭의 변경은 409로 거절한다. 생성 중에는 서비스·모델·로그인 변경을 막아 재시도 대상을 고정한다.
- 로그인 대기는 브라우저가 닫혀도 만료된다. 로그인 완료 알림만 믿지 않고 계정 상태를 재확인한다. 원시 인증 오류는 표시하지 않는다. 요청 취소와 프로세스 종료 때 잠금과 자원을 정리한다.
- 두 서비스의 본인 로컬 연결과 타인용 배포 조건, 구독·SDK 크레딧·API 결제의 차이를 MVP 설계와 품질 제품 설계에 반영했다.

## 검증 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| 백엔드 전체 | 1,139개 중 실패 0 | pytest, 기존 Q1a~Q2c 회귀 포함 |
| 프런트 전체 | 284개 중 실패 0, 27개 파일 | Vitest |
| 화면 빌드 | 성공 | TypeScript + Vite |
| API 계약 | 재생성 및 검사 통과 | OpenAPI와 TypeScript 타입 |
| 공개 저장소 감사 | 발견 0 | 추적 파일 및 이번 변경·신규 파일 별도 검사 |
| 공백 오류 | 발견 0 | git diff --check |

실제 설치된 Claude Code 2.1.247에서 기존 본인 구독 로그인 상태를 확인했다. 재로그인으로 기존 계정을 바꾸지는 않았다.

실제 Codex CLI 0.154.0의 분리된 임시 프로필에서 다음을 확인했다. 모델 생성은 실행하지 않았다.

1. `account/read`가 미로그인을 정상 응답한다.
2. `model/list`가 표시 가능한 텍스트 모델 6개를 응답한다. 이는 계정 권한이나 잔여 한도를 입증하지 않는다.
3. 브라우저 로그인 시작이 OpenAI 공식 HTTPS 주소와 대기 상태를 반환하고, 로그인 취소가 완료된다.
4. 생성 전 ephemeral thread 생성이 성공하고 읽기 전용·네트워크 차단·지정 모델 설정을 반환한다.

Chrome에서 실제 백엔드와 빌드된 화면으로 다음 7개 시나리오를 확인했다. 전용 임시 저장소와 합성 자료를 사용했고 실제 AI 호출은 검증 서버에서 차단했다.

1. 프로젝트 목록에 현재 Claude 로그인 상태와 모델이 표시된다.
2. ChatGPT로 전환하면 Claude 모델 대신 Codex가 반환한 모델 6개가 표시된다.
3. 로그인 시작 후 공식 로그인 링크와 대기 취소 버튼이 나타나며 연결됨으로 오인하지 않는다.
4. 취소 후 링크가 사라지고 취소 상태가 표시된다.
5. ChatGPT 모델 선택을 저장하고 새로고침해도 설정이 유지된다.
6. 프로젝트 안에서 Claude Opus로 전환해 저장할 수 있다.
7. 생성 전 고지에 Claude/opus가 표시되고 Escape로 취소하면 생성 없이 편집 가능한 상태로 돌아온다.

테스트와 CLI 대조에서 찾은 문제는 반영했다. 설치된 Codex는 스키마·도움말에 남은 `untrusted` 승인 정책을 실제로 거절했으므로 동작을 확인한 `on-request`와 도구 요청 거절을 사용한다. OpenAI 객체 스키마의 required/닫힌 객체 계약, 조회 실패 시 동의 버튼 차단, 취소 중 잠금 누수, 창 종료 후 로그인 대기, 인증 오류 원문 노출도 보완했다.

## 미검증과 다음 행동

- ChatGPT의 본인 인증 입력과 최종 로그인 완료, Claude의 새 브라우저 재로그인 완료는 실증하지 않았다. 완료 알림과 계정 재조회 경로는 모의 응답으로 검증했다.
- 실제 계정에서 두 제공자로 문서를 생성하고 SDK/Codex 토큰 사용량을 대조하는 관통은 미수행이다. 실제 AI 생성 요청 0회다.
- Windows 실기기에서 네이티브 CLI와 브라우저 콜백을 검증하지 않았다. 공개 CI를 새로 실행하거나 원격에 올리지 않았다.
- 앱 서버의 실험적 프로토콜과 Anthropic 배포 조건은 배포 전에 다시 확인한다. 현재 로컬 구독 연동을 무제한 배포 허가로 간주하지 않는다.
- 다음 실증은 사용자가 연결 화면에서 본인 로그인을 완료한 뒤 합성 자료로 제공자별 생성 1건을 수행하고 실제 결과·모델·토큰을 대조하는 것이다. 내용과 시각 품질은 별도 검수한다.
- 품질 개발은 기존 Q2c 이후 계획을 따른다. 이번 요청 범위를 마치고 다음 품질 단위로 자동 진행하지 않는다.

## 파일과 재현

- 연결 관리: `backend/slidecaptain/pipeline/connections.py`
- ChatGPT 어댑터: `backend/slidecaptain/pipeline/codex.py`
- Claude 경로와 상태: `backend/slidecaptain/pipeline/subscription.py`, `auth_status.py`
- 조립과 API: `backend/slidecaptain/__main__.py`, `server/app.py`
- 화면: `frontend/src/screens/AISettingsPanel.tsx`, `AiConsentDialog.tsx`, `ProjectList.tsx`, `ProjectView.tsx`
- 전송 동의: `frontend/src/api/aiGate.ts`, `client.ts`
- 설계 진본: [MVP 2.4](../specs/2026-08-27-mvp-design.md), [연결 아키텍처](../architecture/2026-09-13-ai-connections.md)
- 로그: `/tmp/slidecaptain-connections-backend-tests.log`, `/tmp/slidecaptain-connections-frontend-tests.log`
- 변경 보존 대조: `/tmp/slidecaptain-connections-preservation.json`

backend에서 `.venv/bin/python -m pytest tests -q`, frontend에서 `npm test`와 `npm run build`를 실행한다. OpenAPI는 backend의 `scripts/dump_openapi.py`, 타입은 frontend의 `npm run generate-types`로 재생성한다. 실제 화면은 기존 실행 스크립트로 연다.

## 보존과 작업 상태

브랜치 `codex/phase-5b`, 시작 HEAD `acff346`의 누적 미커밋 작업 위에서 진행했다. 이번 작업 전 198개 파일을 별도로 보존했고 173개는 바이트 단위로 유지했다. 기존 25개 파일을 수정하고 이번 범위의 신규 8개 파일을 추가했으며 삭제는 없다. 기존 Q1a~Q2c 파일과 스테이징을 초기화하지 않았다. 커밋·푸시·머지는 하지 않았다.

검증용 탭과 서버는 종료했고 포트가 닫힌 것을 확인했다. 별도 위키 지식 문서나 메모리는 쓰지 않았다. 이 구현과 자동 검사 결과를 실제 보고서 품질 검증으로 기록하지 않는다.
