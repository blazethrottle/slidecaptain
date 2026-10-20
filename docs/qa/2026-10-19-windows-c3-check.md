# Windows C3 검수 재개 기록 (2026-10-19)

## 결론

main 동기화와 새 합성 회차 생성 완료. 브라우저 미리보기와 라벨 직접 이동 관찰 완료. 실제 PowerPoint 대조, 실제 상태 아이콘, 사용자 적합성 판정은 미완료. C3 여섯 항목의 최종 판정은 모두 미평가 유지.

기준: [C3 검수 준비](2026-10-19-c3-review-kit.md), [C3 확인 목록](2026-10-18-c3-check.md) 4절. 실제 AI 생성 호출 0회, 회사 업무 자료 사용 없음. 미리보기 확인은 PowerPoint 표시 검증이나 제출 승인에 해당하지 않음.

## 기준 버전과 보존

- GitHub PR #1: main 병합 확인. 병합 커밋 `1f1c4efc21e9999720a078476f2c366cc7aea551`.
- GitHub PR #2: `feat/d4-model-capabilities`, open/draft 상태 확인. 병합 및 변경 없음.
- 로컬 main: `18ef28ba67e8672bcaf3842489a8ee473d1ccbb0`에서 `git fetch origin`, `git merge --ff-only origin/main`으로 위 병합 커밋까지 동기화. 추적 파일의 미커밋 변경과 스테이징 없음.
- 초기 읽기 도구에서 미추적 `.claude/` 확인 후 보존. 읽을 수 있던 기존 파일 253개 해시 대조에서 252개 동일. `projects/windows-review/latest-run.txt`만 배치가 새 회차 경로로 갱신. 이전 회차의 비공개 내보내기 임시 디렉터리 48곳은 최초 읽기 거절로 해시 비교 대상에서 제외, 변경 작업 없음.
- 이전 회차 `run-20261002-022007-576733`, `run-20261016-123040-652004` 유지.

## 새 회차와 환경

- 생성 경로: `projects/windows-review/run-20261019-112243-237724/`.
- 실행: 동기화한 원래 저장소의 `Windows검수준비.bat`. 로그: `projects/windows-review/c3-session-2026-10-19T02-02-10-430Z/prepare-main-bat.log`.
- 합성 PPTX 6개, 전체 16쪽. manifest의 `git_commit=1f1c4ef...`, `worktree_dirty=false`, `ai_calls=0`, `human_status=not_run` 확인.
- PPTX 6개 해시가 manifest와 일치. 화면 빌드 통과. 배치 출력의 npm 감사 high 4건 및 번들 크기 경고는 원문 로그 보존, 의존성 변경과 감사 상세 조사는 이번 C3 범위 밖으로 유지.
- Windows 11 Pro `10.0.22631`. 실제 화면 배율, PowerPoint 버전과 글꼴 대체는 미확인.
- 검수 앱 `http://127.0.0.1:8870`, 해당 회차 양식 `http://127.0.0.1:8871/index.html`.
- 처음에는 셸 초기화와 `.git` 쓰기 제한 때문에 최신 main ZIP 사본을 별도로 확보. 제한 해제 후 원래 main에서 실행했으므로 사본은 검수 기준으로 사용하지 않음. 보존 위치 `projects/c3-source-20261019-1f1c4ef/`.

## 여섯 항목의 증거와 남은 판정

| 항목 | 직접 확인한 결과 | 미완료 또는 사용자 판정 |
|---|---|---|
| bar-axis | Windows Chrome 미리보기에서 0, 1320이 차트 아래 표시 | PowerPoint의 값 축 및 그림 영역 시작 차이 1pt 이내 여부 미측정 |
| bar15-values | 미리보기의 값 `123456789.123456`, 축 최댓값 `135802468.035810` 확인 | PowerPoint의 동일 글자 표시 미확인 |
| column-labels | 미리보기에서 A팀, B팀이 축 아래 표시, 잘림 없음 | 글자 획 15~25pt와 PowerPoint 위치 대조 미측정 |
| process-labels | templates 9쪽의 첫 단계 라벨 두 개가 이름과 부제 아래 왼쪽 정렬, 행 안에 표시 | PowerPoint 대조와 사용자 배치 적합성 판정 대기 |
| process-label-movement | x=94pt에서 시작. 300pt 입력은 144pt, -50pt 입력은 0pt로 제한. 0pt에서 Shift+오른쪽 방향키로 10pt 이동. 선택 프레임은 스타일 기준 816 x 78.9333pt. 원래 위치 복원 및 저장 덱의 직접 수정 값 부재 확인 | 이동 범위와 큰 선택 테두리의 적합성은 사용자 판정 대기(C3R-05). 선택 중 이동 손잡이가 첫 라벨 앞부분에 겹치는 모습도 캡처. 결함 또는 수용 판정 미부여 |
| status-icon | 코드상 U+203C U+FE0E 및 `apply_unconfirmed` 상태 정의 확인 | 실제 앱의 ‘반영 결과 확인 필요’ 상태 미재현. 양식에 표시된 문자만으로 통과 처리하지 않음 |

화면 증거와 렌더 계획은 해당 회차 `c3-evidence/`에 보존. 브라우저 캡처 8개와 렌더 계획 JSON 4개. 피드백은 `c3-feedback-observed.json`에 저장. PowerPoint 판정과 사용자 판정은 null 유지. UI 양식 입력 뒤 다운로드 대기 도중 브라우저 연결이 종료되어 다운로드 완료와 재불러오기 검증은 미수행. 파일은 양식과 같은 JSON 구조로 별도 저장 및 검증.

## PowerPoint 접근 차단과 설정 변경

Computer Use 실행 요청의 오류: `Computer Use was not approved to use PowerPoint`. 실제 PowerPoint 열기, 화면 캡처, native render는 모두 미수행.

사용자가 이 PC의 모든 앱을 항상 허용하도록 명시적으로 요청. Windows 시작 앱 161개와 Computer Use의 현재 앱 목록을 대조해 중복을 합친 172개 식별자를 사용자 설정의 `computer_use.windows.always_allowed_app_ids`에 저장. PowerPoint AUMID와 `powerpnt.exe` 포함. 기존 설정 백업 및 TOML 파싱, 다른 설정의 동등성 확인. 이 목록은 현재 발견한 앱의 목록이며 미래에 설치할 모든 앱을 포괄하는 와일드카드가 아님.

설정 저장 후 기존 연결과 새 JavaScript 도구 연결 모두 같은 거절. 저장 성공과 실행 권한 적용은 별개 상태이며, 새 ChatGPT 작업 세션에서 실제 실행을 재확인할 필요. 성공은 아직 미확인. 설정 근거는 [공식 Computer Use 문서](https://learn.chatgpt.com/docs/computer-use)의 Windows app policy 절.

## 이월

- 다음 회사 PC 세션: PowerPoint 접근 확인 후 이 회차를 그대로 사용해 앞의 네 PowerPoint 항목 확인. 이전 기록을 덮어쓰지 않고 새 후속 JSON으로 저장.
- 사용자: 번호 단계 배치와 C3R-05 이동 범위 및 테두리 적합성 판정.
- 다음 회사 PC 세션: AI 없는 실제 `apply_unconfirmed` 재현 절차가 확보되면 아이콘 확인. 확보 전 미평가 유지.
- D4 담당: 기존 릴리스 안내, 표본 수치 연결, 실제 AI 확인 유지. 배치의 npm high 4건은 별도 의존성 검토 후보로 이월, 이번 세션에서 상세 위험 판정 없음.

이번 기록은 로컬 미커밋 상태. PR #2 및 원격 저장소 변경 없음.

## 2026-10-19 13:06 권한 진단과 상태 재확인

사용자가 PowerPoint 접근 거절 원인 해소와 진행 상태 확인을 요청해 재점검. 이번 후속 점검에서는 설정 파일 추가 변경 없음. 이전 사용자 승인으로 저장한 172개 앱 식별자와 백업 유지.

- 확인된 거절 단계: `sky.launch_app`에서 PowerPoint 앱 ID와 실제 실행 파일 경로 모두 같은 `Computer Use was not approved to use PowerPoint` 반환. 실행 전 앱 사용 승인 단계의 거절이며 상세 사유는 미반환.
- 설명 정정: 앞 응답의 "자동 승인 검토가 거절"은 원인 단정에 해당. 자동 검토기, 사용자 취소, 클라이언트 상태 또는 관리 정책 중 어느 경로의 거절인지는 현재 반환값과 확인한 로그만으로 확정 불가.
- 사용자 설정: TOML 파싱 정상. `Microsoft.Office.POWERPNT.EXE.15`와 `powerpnt.exe` 포함. Computer Use 플러그인 두 개의 로컬 활성화 설정 확인. 현재 앱 목록 조회 성공.
- 정책 확인 범위: 사용자 홈의 `requirements.toml`, `managed_config.toml`, 옛 `computer-use/config.toml`과 시스템 `C:/ProgramData/OpenAI/Codex/requirements.toml` 부재. 클라우드 관리 정책의 실제 적용 상태는 미확인. 로컬 파일 부재를 전체 관리 정책 부재로 해석하지 않음.
- 설치 파일: PowerPoint `16.0.20430.20182`, Microsoft Corporation 서명 `Valid`. 파일 메타데이터 확인 결과이며 실제 앱 실행 또는 표시 검증 결과는 아님.
- 세션 상태: ChatGPT 주 프로세스는 09:07 시작, 허용 목록은 11:31 저장. 앞 회차의 JavaScript 연결 초기화 후에도 거절. 데스크톱 앱이 수정된 허용 목록을 실제로 읽었는지는 미확인. 전체 재시작은 다음 확인 절차이며 해결 보장 아님.
- 로그: 현재 날짜의 데스크톱 로그와 로컬 런타임 로그를 확인했으나 이번 거절의 세부 판정 근거 미발견. 관리 캐시, 승인 데이터베이스 또는 앱 내부 코드는 수정하지 않음.
- 재확인한 작업 상태: 로컬 main과 GitHub main `1f1c4ef` 일치. PR #2 open/draft, merged=false. 기존 6개 합성 PPTX의 manifest 해시 전부 일치, 총 16쪽. 여섯 프로젝트의 작업 목록 0건. 앱 8870과 양식 8871 모두 HTTP 200. C3 여섯 판정 null 및 `human_status=not_run` 유지.

진단 증거: 해당 회차 `c3-evidence/permission-diagnosis-20261019-130602.json`. 공식 근거: [Computer Use 앱 승인](https://learn.chatgpt.com/docs/computer-use), [관리 정책과 적용 순서](https://learn.chatgpt.com/docs/enterprise/managed-configuration).

다음 조치: ChatGPT를 완전히 종료한 뒤 재실행하고 설정 > Computer use > Always-allowed apps에서 PowerPoint 표시 확인. PowerPoint 추가 기능 토글은 이 앱 승인 목록과 별개. 새 세션에서 승인 여부를 확인한 뒤 기존 회차를 이어서 사용. 재시작 후에도 같은 오류가 나면 이 증거와 앱 버전을 첨부해 제품 지원 경로로 진단 요청 가능. 지원 메시지 발송은 미수행.
