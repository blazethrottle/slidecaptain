# 핸드오프: D4a 모델 지원 정보와 ChatGPT 추론 강도 (2026-10-19)

## 현재 상태와 커밋

사용자의 계속 진행 지시에 따라 C3 준비 PR [#1](https://github.com/blazethrottle/slidecaptain/pull/1)을 병합하고 main에서 `feat/d4-model-capabilities`를 분기했다. 이번 구현 범위는 [D4a 계획](../plans/2026-10-19-revision-d4a-model-effort.md)이며 D4 전체 완료가 아니다.

| 커밋 | 내용 |
|---|---|
| `8eb5823` | C3 회사 PC 검수 여섯 항목과 저장/복원. 이전 PR/push 양 OS CI 성공 |
| `1f1c4ef` | C3 PR #1 main 병합. 기준 개발선. [CI 39182096593](https://github.com/blazethrottle/slidecaptain/actions/runs/39182096593) Windows/macOS 최종 성공 |
| 이 문서가 포함된 커밋 | D4a 지원 강도, 저장/검증/요청 전달, 화면/상태/동의 표시와 회귀 |

Codex의 현재 모델 목록 전체에서 지원 강도와 기본값을 읽으며 저장과 생성 시작 때 재검증한다. 수동 선택한 값은 생성 lease와 각 재시도 요청에 고정된다. 강도만 바꿔도 동의 리비전이 바뀐다. 사라진 지원값은 자동 대체하지 않고 다시 고르도록 안내한다. 제공자 기본값 선택은 기존 두 필드 설정 파일과 요청 형태를 유지한다.

## 검증

계획 독립 리뷰의 생성 전 강도 표시 누락과 백엔드 리뷰의 임의 문자열 문법 제한을 반영했다. T2와 브랜치 전체 최종 독립 리뷰에서 추가 결함은 없었다. 실제 사용 가능한 Codex 리뷰 경로였으며 Claude 전용 리뷰 도구를 사용했다고 기록하지 않는다.

새 실패 시험은 백엔드 14건과 프런트 8건이 구현 전에 실패했다. 문자열 규약 보완 후 백엔드/API 관련 51개와 화면 28개가 통과했다. 최종 전체 검증은 백엔드 2,951개 통과/플랫폼 관련 5개 건너뜀(239초), 프런트 86파일/1,333개 통과(72초)다. 빌드/타입 검사, 디자인 토큰 96개 검사, 공개 저장소 이력 감사와 `git diff --check`를 통과했다. OpenAPI와 타입을 함께 재생성했다. 새 커밋의 양 OS CI 결과는 해당 PR Checks가 진본이다.

초기 전체 검사에서 오류 코드 대응표의 새 경로와 공용 오류 응답 예시의 문구 동기화 누락을 찾아 반영했다. 프런트 첫 전체 실행은 실행 중 파일 변경에 따른 모듈 캐시 혼합과 백엔드 병렬 부하의 시간 초과로 실패했다. 최종 검증은 코드를 고정하고 두 전체 검사를 순차 실행한 결과다. 기존 빌드의 500 kB 번들 크기 경고는 로드맵 성능 담당에 남겼다.

실제 Chromium에서 빌드된 화면과 합성 API 응답으로 저장, 다시 열기, 재조회 중 미저장 값 보존, 지원 철회 후 저장 차단, 기본값 요청 생략을 확인했다. 상태 변경 요청의 클라이언트 헤더도 확인했다. 실제 계정 로그인과 AI 호출은 0회다. 현재 환경의 브라우저 증거는 `/workspace/scratch/d4-effort-browser.png`, 재현 스크립트는 `/workspace/scratch/d4-browser-check.mjs`이며 저장소에 넣지 않았다.

## 다음 즉시 행동

1. 이 브랜치 PR과 해당 커밋의 Windows/macOS Checks를 확인한다. CI 완료 여부의 진본은 GitHub Checks이며 진행 중을 성공으로 해석하지 않는다.
2. 다음 D4 구현은 Claude 공식 모델/정확 버전/지원 범위 또는 공식 계정 프로필을 D1 기술 검증 결과에 맞춰 상세화한다. 아직 완료되지 않은 두 계정 격리와 OS 키체인 확인을 건너뛰지 않는다.
3. 회사 PC에서는 C3 합성 검수 양식 여섯 항목을 PowerPoint와 실제 앱에서 확인한다. [C3 기록 준비](../qa/2026-10-19-c3-review-kit.md)를 따른다.

## 미완료와 운영 주의

실제 Effort 적용 확인, 정확 모델 버전, Claude Effort/공식 목록, 계정 프로필/영구 동의/추천과 D4 전체 수용은 미완료다. 원장/사용량에는 아직 요청 Effort를 별도로 남기지 않는다. 마지막 생성 성공 시각은 기존 제공자/모델 범위이므로 현재 강도의 성공 증거가 아니다. 로드맵 D4a 이월표에 담당을 적었다. 실제 AI 예산은 0회다.

명시 Effort 설정이 있는 상태에서 구버전으로 돌리면 알 수 없는 필드 때문에 설정 읽기가 거절된다. 먼저 새 앱에서 제공자 기본값으로 저장한 뒤 되돌린다. 설정 파일 삭제나 비공식 인증 복사는 하지 않는다. C3 PowerPoint 표시와 Windows 앱 아이콘은 이 Linux 작업으로 판정하지 않았다.

## 파일 인덱스

- 계약/저장: `backend/slidecaptain/pipeline/connections.py`, `backend/slidecaptain/server/app.py`
- 공식 요청: `backend/slidecaptain/pipeline/codex.py`
- 화면: `frontend/src/screens/AISettingsPanel.tsx`, `AiConsentDialog.tsx`, `ProjectList.tsx`, `frontend/src/ui/AiStatusLine.tsx`
- 생성 계약: `backend/openapi.json`, `frontend/src/api/types.ts`, `client.ts`
- 회귀: `backend/tests/test_ai_connections.py`, `test_codex_provider.py`, `test_jobs_error_codes.py`, 프런트 설정/동의 시험
- 범위/이월: D4a 계획과 `docs/plans/2026-08-27-mvp-roadmap.md`
