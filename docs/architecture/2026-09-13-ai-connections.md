# Claude와 ChatGPT 연결 설계

2026-09-13 사용자 요청에 따라 브라우저 로그인, 연결 상태, 모델 선택과 생성 경로를 추가했다. 현재 실행 프로필은 소유자 1인의 로컬 앱이다. 품질 파이프라인과 Q1a~Q2c의 기존 데이터 계약은 유지한다.

## 사용자 흐름

프로젝트 목록 또는 프로젝트 안에서 **AI 연결 및 모델**을 연다. Claude 또는 ChatGPT를 고르고 공식 로그인 절차를 완료한 뒤 모델을 선택해 저장한다. 이미 연결된 Claude 계정은 재로그인할 필요가 없다. 연결 여부와 최근 생성 성공은 다른 정보이며, 최근 성공은 서비스와 모델별로 표시한다.

| 기능 | Claude | ChatGPT |
|---|---|---|
| 연결 주체 | 이 PC의 본인 Claude Code 계정 | SlideCaptain 전용 Codex 프로필 |
| 로그인 시작 | 수정하지 않은 공식 CLI의 `auth login`; CLI가 브라우저를 연다 | 공식 app-server의 `account/login/start(type=chatgpt)` |
| 로그인 완료 | CLI 종료 성공과 `auth status`를 함께 확인 | 해당 loginId의 완료 알림과 `account/read`를 함께 확인 |
| 브라우저 | Anthropic의 공식 흐름에서 직접 인증 | OpenAI가 발급한 공식 로그인 링크를 새 탭에서 연다 |
| 모델 | 공식 별칭 Sonnet, Opus, Haiku | app-server `model/list`의 표시 가능한 텍스트 모델 |
| 생성 | Claude Agent SDK | Codex app-server의 ephemeral thread + `turn/start(outputSchema)` |
| 취소와 만료 | 앱이 시작한 로그인 프로세스만 종료 | 현재 loginId에 `account/login/cancel` |

로그인 상태는 연결됨, 미로그인, 확인 불가를 구별한다. 로그인 시도는 idle, pending, succeeded, failed, cancelled로 구별하며 180초가 지나면 취소한다. 버튼을 누르거나 링크를 생성한 사실만으로 연결됐다고 표시하지 않는다. 연결 재확인은 모델을 호출하지 않는다. Claude의 브라우저가 열리지 않으면 공식 CLI에서 로그인하고 재확인할 수 있게 안내한다.

로그아웃 API는 추가하지 않았다. Claude는 다른 도구와 같은 계정을 사용하므로 앱의 로그인 대기 취소가 전역 Claude Code 로그아웃으로 이어져서는 안 된다. ChatGPT도 로그인 대기 취소와 저장된 인증 삭제는 다른 작업이다. 계정 변경은 다시 로그인으로 수행한다.

## 공통 생성 경계

`AIConnections`가 provider와 model을 관리한다. 선택 저장 시 해당 제공자의 모델 목록에 속하는지 검사하고 임시 파일과 `os.replace`로 `ai-settings.json`을 교체한다. 설정 파일에는 이 두 값만 저장한다. 읽을 수 없는 설정은 다른 서비스로 자동 대체하지 않는다.

생성 직전에 브라우저는 `/api/status`에서 현재 선택의 `selection_id`를 받고 그 상태를 전송 고지에 표시한다. 동의는 탭과 이 식별값에 묶는다. 모든 생성 요청은 `X-AI-Consent`와 `X-AI-Selection`을 보낸다. 모델, 서비스, 앱 재시작 또는 관측된 계정 상태 변경으로 식별값이 바뀌면 이전 요청을 409로 거절한다. 새 서비스로 문서를 보내는 자동 대체는 없다.

생성 1건 동안 제공자와 모델을 고정하고 연결 변경을 막는다. 형식 재시도와 자동 축약도 같은 제공자를 사용한다. 연결 확인은 스레드풀에서 수행해 이벤트 루프를 막지 않는다. 상위 파이프라인의 프롬프트, 응답 검증, 근거·비교·계산 검사는 두 어댑터가 공유한다.

OpenAI로 보내는 응답 스키마는 객체의 모든 필드를 required로 만들고 additionalProperties를 false로 닫는다. 기본값 필드는 명시적으로 출력하고 nullable 계약은 유지한다. 이 변환은 전송 스키마에만 적용하며 원래 모델과 Claude 스키마는 바꾸지 않는다. 지원하지 않는 합성 스키마는 호출 전에 거절한다. 응답의 최종 진본은 기존 Pydantic 검증이다.

## 자격 증명과 프로세스 경계

- 비밀번호, 인증 코드, 쿠키나 OAuth 토큰을 입력받는 자체 폼을 만들지 않는다. SlideCaptain은 인증 파일을 읽어 토큰을 추출하지 않는다.
- Claude는 상태와 생성에 같은 네이티브 CLI 경로를 사용한다. `.cmd`와 `.bat`는 실행 후보에서 제외한다.
- ChatGPT는 `<data-dir>/.slidecaptain-codex/`를 공식 CLI의 프로필로 사용한다. 기존 Codex 프로필이나 인증 파일을 복사하거나 수정하지 않는다. 네이티브 `codex`/`codex.exe`를 찾으며 필요한 경우 `SLIDECAPTAIN_CODEX_CLI`로 경로를 지정한다.
- ChatGPT 프로필의 인증 저장은 공식 CLI가 맡는다. 앱 설정 JSON과 덱에는 계정 토큰을 담지 않는다. Git은 프로필 폴더와 로컬 선택 설정을 제외한다.
- app-server는 자식 프로세스의 stdio로만 연결한다. 앱용 WebSocket이나 외부 리스너를 만들지 않는다. 공식 로그인 콜백 리스너는 Codex가 관리한다.
- 네이티브 실행 파일과 인자 배열을 사용하고 shell 문자열로 문서 내용을 실행하지 않는다. 문서는 stdin JSON으로 전달한다. 표준 오류나 원시 인증 오류를 UI에 전달하지 않는다.
- ChatGPT 프로세스에는 별도 작업 폴더를 주고 사용자 API 키 환경 변수를 넘기지 않는다. 셸, 브라우저, 컴퓨터 제어, 앱, 플러그인, 훅, 메모리 기능을 끄고 읽기 전용 샌드박스를 적용한다. 서버가 요청한 도구 승인이나 외부 토큰 갱신은 처리하지 않는다. 권한 우회 옵션을 쓰지 않는다.
- 생성별 임시 thread는 종료·실패·시간 초과·요청 취소 시 닫는다. 인증과 상태 API는 `Cache-Control: no-store`이며 기존 로컬 Host, Origin, 커스텀 헤더 방어를 적용한다.

이 설정은 로컬 파일럿용 방어다. 실행 중인 모든 버전의 Codex가 모든 내장 기능을 동일하게 처리한다는 보증이나 악성 운영체제 프로세스에 대한 경계는 아니다. 공식 CLI의 업데이트와 실제 생성 관통 검증은 배포 전에 다시 수행한다.

## 사용량과 비용 표시

Claude의 기존 SDK 사용량 해석은 유지한다. ChatGPT는 `thread/tokenUsage/updated.total`에서 받은 토큰만 기록한다. 반환하지 않은 비용과 처리 시간 세부값은 null로 남긴다. 조회된 모델 목록은 계정의 호출 권한이나 잔여 한도를 보증하지 않는다. 사용량이 없는 값은 0이나 추정 청구액으로 채우지 않는다.

## 서비스 배포 설계와 공식 근거

2026-09-13 확인한 정책을 기준으로 두 제공자를 서비스 설계의 일급 연결 대상으로 둔다. 현재 구현은 본인용 로컬 구독 연결이며 API 키를 받는 배포용 UI, 결제와 다중 사용자 관리는 이번 범위에 없다.

1. **OpenAI**: 제품 내부 인증과 모델·대화 제어용으로 [Codex app-server](https://learn.chatgpt.com/docs/app-server)를 문서화한다. 구독 인증은 Codex가 관리하는 브라우저 흐름을 사용한다. 외부 토큰 직접 전달 방식은 채택하지 않는다. 실측 CLI는 0.154.0이다. app-server의 실험적 상태와 버전별 계약을 배포 관문에서 재확인한다.
2. **Anthropic**: [Agent SDK 구독 사용 안내](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)는 본인 프로젝트와 SDK 사용의 월 크레딧을 안내한다. [법률 및 준수 문서](https://code.claude.com/docs/en/legal-and-compliance)는 제품의 제3자 Claude.ai 로그인·인증 중계와 수정하지 않은 Claude Code 실행을 구분한다. 두 문구를 자체 OAuth 서비스의 포괄적 허용으로 해석하지 않는다. 타인에게 배포할 때는 Claude API, 지원 클라우드 또는 그 시점에 명시적으로 허용된 계약과 방식으로 제공한다.
3. **모델 계약**: Claude는 [공식 모델 별칭](https://code.claude.com/docs/en/model-config), ChatGPT는 `model/list`를 따른다. 특정 버전을 앱에 임의로 고정하지 않는다. [OpenAI 구조화 출력 규약](https://developers.openai.com/api/docs/guides/structured-outputs)에 맞춘 전송 스키마 변환을 둔다.

Claude SDK 월 크레딧, 사용 크레딧과 ChatGPT의 Codex 한도를 웹 채팅 한도 또는 API 결제와 동일하다고 설명하지 않는다. 과거 설계의 “구독이면 별도 청구가 없다”는 단정은 이 개정으로 폐기한다.

## 검증 경계

자동 검사는 두 제공자로의 라우팅, 설정 보존, 잘못된 모델, 낡은 동의, 생성 중 변경, 인증 대기·완료 알림의 일치, 취소·만료, JSONL 통신, 도구 요청 거절, 스키마 변환, UI 상태를 검증한다.

실제 CLI에서는 Claude의 기존 로그인 상태와 ChatGPT의 비로그인 상태, 모델 목록, 로그인 시작·취소, 생성 전 ephemeral thread 설정을 확인했다. 브라우저 확인과 실제 계정 인증 완료, 문서 생성 호출, Windows 실기기 검증은 서로 다른 증거다. 최종 결과와 미검증 항목은 [인계 문서](../handoffs/2026-09-13-ai-connections-handoff.md)에 기록한다.
