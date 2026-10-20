# Windows C3 검수 이어가기 (2026-10-19)

## 현재 상태

main을 GitHub `1f1c4efc21e9999720a078476f2c366cc7aea551`로 fast-forward. PR #1 병합 확인, PR #2 open/draft 유지. 기존 변경과 이전 검수 기록 보존. `Windows검수준비.bat`로 새 합성 6개/16쪽 생성. 실제 AI 호출 0회, 회사 자료 사용 없음.

검수 진본: [Windows C3 확인 기록](../qa/2026-10-19-windows-c3-check.md). PowerPoint 접근 거절 때문에 실기기 대조는 미완료. 브라우저 관찰과 직접 이동 결과만 저장. 최종 C3 판정은 여섯 개 모두 미평가. 사용자 배치/이동 판정도 대기.

## 다음 즉시 행동

1. 새 작업 세션에서 `computer-use` 스킬을 읽고 PowerPoint 접근부터 확인. 사용자가 현재 PC의 모든 앱 항상 허용을 요청했고 설정 파일에 현재 감지한 앱 식별자 172개 저장 완료. 이전 세션의 새 도구 연결에서는 여전히 거절되어 실제 적용은 미확인. 같은 설정을 중복 추가하지 말 것.
2. 회차 `projects/windows-review/run-20261019-112243-237724`를 재사용. 새 검수 회차를 다시 만들 필요 없음. 서버가 살아 있는지 먼저 확인. 앱 포트 8870, 양식 포트 8871. 재시작 시 이 회차의 `store`만 지정.
3. PowerPoint에서 bar, bar15, column 각 1쪽과 templates 9쪽을 실제로 열어 미리보기와 비교. bar 그림 영역 1pt 기준과 column 획 위치는 실제 측정 필요.
4. 사용자에게 templates 9쪽 배치 및 라벨 이동/테두리 판정을 받기. `c3-evidence/process-label-selected.png`, `process-label-x144.png` 참고. 관찰만으로 사용자 통과를 대신하지 말 것.
5. 실제 앱의 `apply_unconfirmed` 아이콘은 재현하지 못하면 미평가 유지. 실제 AI 호출 없이 진행.
6. 새 후속 JSON에 결과 저장. 기존 `c3-feedback-observed.json`, manifest, 이전 피드백 보존. 로드맵과 C3 기록에 후속 상태 반영. PR #2 임의 병합 금지.

## 파일과 검증

- 새 회차: manifest와 6개 PPTX 해시 일치. 브라우저 캡처 8개, 렌더 계획 JSON 4개, 관찰 피드백 JSON.
- 원래 검수 기록/`.claude` 보존 증거: `projects/windows-review/c3-session-2026-10-19T02-02-10-430Z/preservation-before.json`, `preservation-after.json`. 최초 읽기 불가한 비공개 staging 48곳은 해시 비교 제외.
- 설정 백업: `%USERPROFILE%/.codex/config.toml.before-computer-use-20261019-113128.bak`. 다른 설정은 바꾸지 않음. 복원할 경우 이후 사용자 설정 변경 유무부터 확인.
- 최초 제한 상황에서 만든 소스 사본 `projects/c3-source-20261019-1f1c4ef/`는 최종 검수에 사용하지 않음.
- 화면 빌드 통과. 전체 테스트 및 독립 코드 리뷰 미실행(제품 코드 변경 없음). PowerPoint/아이콘/사용자 판정 미완료.
- 기록 문서는 로컬 미커밋 상태. 커밋/푸시 없음. 개발 단계 완료 또는 C3 통과로 간주하지 말 것.

## 후속 권한 진단 (2026-10-19 13:06)

PowerPoint 앱 ID와 실제 실행 파일 경로 모두 승인 오류 재현. 설정의 172개 식별자 유지, 추가 변경 없음. PowerPoint 설치 파일의 Microsoft 서명 유효, 버전 `16.0.20430.20182`. 실행 검증은 여전히 미수행.

오류는 앱 사용 승인 실패까지만 확정. 앞 응답의 "자동 승인 검토"는 확인되지 않은 원인 단정이므로 재사용하지 말 것. 확인한 사용자/시스템 정책 파일에 차단 규칙은 없지만 클라우드 정책 적용 여부는 미확인. ChatGPT 주 프로세스가 허용 목록 저장 이전부터 실행 중이므로, 다음 세션은 전체 앱 재시작과 설정 > Computer use > Always-allowed apps의 PowerPoint 표시부터 확인. 재시작의 해결 효과는 미검증. 현재 세션 연결을 종료하는 앱/데몬 재시작은 실행하지 않음.

상태 재확인: 원격 main 일치, PR #2 초안 유지, 합성 6개/16쪽 해시 일치, 각 프로젝트 작업 0건, 포트 8870/8871 HTTP 200. C3 판정 여섯 개 모두 null. 세부 증거는 해당 회차 `c3-evidence/permission-diagnosis-20261019-130602.json`.
