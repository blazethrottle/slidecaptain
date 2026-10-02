# Q4b: 실제 렌더와 독립 검수 영수증의 제출 관문

작성: 2026-09-30. 사용자의 계획 잔여 개발 일괄 처리 요청에 따라 Q4a 다음 단위를 구현한다. 실제 AI 호출, 커밋과 push는 범위에 없다.

## 계약

- 기존 preflight-v1/v2, manual-review-v1과 초안 PPTX를 변경하지 않는다. 새 export에 서버가 생산자 `slidecaptain`, UUID 생산 실행 ID, 입력 fingerprint와 PPTX SHA-256을 provenance sidecar로 게시한다. provenance 없는 과거 출력은 독립성 대조 불가로 제출 차단한다.
- 실제 렌더는 서버의 고정 Windows PowerPoint COM 어댑터만 목표 환경 증거로 인정한다. PowerPoint 버전, 운영체제와 설치 폰트 fingerprint, 전체 페이지 PNG의 실제 hash와 크기를 서버가 수집한다. 실행 불가/실패는 미수행이며 브라우저가 보낸 렌더러 문자열이나 외부 이미지 자기신고는 제출 자격으로 인정하지 않는다. Mac PowerPoint 자동화는 미지원이고 이 Mac의 PowerPoint 부재를 성공으로 표시하지 않는다.
- native 실행 전에 수행중 `not_run` 이벤트/witness를 먼저 남기고 완료 결과를 새 이벤트로 게시한다. 실행 중 프로세스 중단이나 예기치 않은 파일 오류로 완료 기록이 없더라도 최신 수행중 기록이 과거 렌더 통과를 차단한다. 한 렌더는 시작/완료 두 기록 공간을 요구한다.
- 독립 검수는 로컬 `review-trust.json`의 독립 reviewer key로 HMAC-SHA256을 검증한 영수증을 불변 추가한다. canonical JSON은 UTF-8, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False이다. key는 화면/API에 노출하지 않는다. 생성자 identity, 같은 생산/검수 run ID, 중복 key와 신뢰 미설정은 거절한다. 이것은 설정된 key 소유 경계이며 검수자의 실명이나 내용 진실을 인증하지 않는다.
- 영수증은 생산 실행/입력/출력/render/env/모든 페이지에 묶이고 보고 흐름, 근거, 표현, 시각, 목표 앱 다섯 항목의 판정과 근거를 갖는다. 최신 실패나 손상 기록을 건너뛰어 과거 통과를 부활시키지 않는다.
- 실제 페이지 hash/크기, 서버 실행 ID/순번/시각, 입력/출력, PowerPoint version/build와 설치 환경을 포함한 native record 전체의 canonical SHA-256을 `render_fingerprint`로 계산한다. 독립 영수증은 이 값에도 서명하며 조회/게시 때 서버가 manifest를 다시 계산한다. 제출 영수증은 전체 render/독립 검수 기록과 서명을 포함하고 128KiB를 넘으면 두 파일 게시 전에 거절한다. 개별 증거 이벤트도 128KiB, 합계 8MiB/1,000개 한도다.
- 각 증거 이벤트에는 별도 prefix의 불변 sequence witness(event ID/hash/순번)를 먼저 게시한다. 이벤트 또는 witness 하나의 삭제/손상과 두 번째 파일 게시 전 중단은 unavailable로 차단하며 과거 통과를 복원하지 않는다. 서명은 레코드 내용에 대한 검증이고 존재의 인증은 아니다. 최신 event와 witness를 함께 지우거나 저장소 전체와 신뢰 설정을 과거 상태로 롤백하는 행위는 로컬 신뢰 관리 경계 밖이며 검출을 보장하지 않는다.
- 현재 readable preflight-v2, matched artifact, current input, 생산 provenance, 최신 실제 렌더, 최신 검증된 독립 영수증, 다섯 항목/전체 페이지 통과, 미해결 critical/major 0과 수동 최신 실패 없음이 제출 조건이다. 사전 점검의 실패는 차단한다. 대상 0이나 미수행은 통과하지 않는다.
- GET qualification은 현재성, 미수행/차단 사유, 기준 ETag와 hash를 제공한다. POST render/independent-reviews/publish-final은 앱 헤더, 명시적 If-Match와 expected input/artifact를 요구한다. 저장 직전 입력과 실제 파일을 재대조한다. 잠금 순서는 프로젝트 다음 exports이다.
- 제출본은 검수한 PPTX의 동일 바이트를 불변 게시하고 서명 검수/렌더 범위를 receipt에 남긴다. 기존 export --final은 새 출력이므로 계속 차단하고 별도 publish-final 경로를 쓴다. 손상/경합/심볼릭 링크/읽기 한도는 fail closed다.
- 페이지 선택적 만료는 입력 영향 분석 정보로 제공하고, 새 artifact에 과거 검수를 자동 재바인딩하지 않는다. 실제 PowerPoint/독자 판정과 AI critic 실호출의 미수행은 자동화 합성 검사와 분리한다.

## 소유권과 검증

백엔드 담당은 qualification 모델/저장/관문/PowerPoint 어댑터/새 API와 관련 테스트, 게시 잠금 담당은 exporter와 locking의 안전 경계/provenance, 통합 담당은 CLI/화면/생성 타입/문서와 후속 수정·비교 도구를 맡는다. 다른 담당 변경을 보존한다. 변경 전 실패 검사, 서명 변조/부재/생산자 겹침/낡은 artifact/최신 실패/저장 경합/동일 바이트 게시 반례, 기존 검수/내보내기 회귀와 전체 검사로 검증한다. Windows COM 실제 실행은 이 Mac에서 수행하지 못하며 별도 실기기 검증 대상으로 남긴다.

2026-09-30 구현 경계 보완: 제한 시간 종료는 서버가 시작한 PowerShell 자식만 종료한다. PowerPoint COM 자식이 남을 수 있으며 사용자 PowerPoint를 프로세스 이름으로 강제 종료하지 않는다. 이미 실행 중인 PowerPoint는 렌더 시작 전에 거절한다. 전역 thread/OS 잠금으로 서로 다른 프로젝트와 서버 프로세스의 native 렌더를 직렬화하고 대기는 5초로 제한한다. 사용자 앱이 guard 직후 시작하는 COM singleton 경쟁에서 소유권을 입증할 수 없으므로 Application.Quit나 글로벌 AutomationSecurity 변경을 수행하지 않고 서버가 연 Presentation만 닫는다. COM 앱이 남으면 사용자가 닫은 뒤 다음 렌더를 재시도해야 한다. 설치 폰트 inventory와 실행 파일 SHA는 환경 변경 감지이며 개별 글리프의 실제 대체 여부를 인증하지 않는다. 불변 게시의 숨김 임시 이름은 stat-then-unlink 소유권 경쟁으로 타 파일을 삭제하지 않도록 자동 삭제하지 않는다. 렌더 파일/환경 속성은 [Presentation.Export](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.presentation.export), [Application.Version](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.application.version), [Application.Build](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.application.build)를 따른다.
