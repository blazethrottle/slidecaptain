# Q1b 첫 단위: 내보내기 품질 기록 인계

작성: 2026-09-13. 저장소: `~/Projects/slidecaptain`.

**종료 지점: 현재 초안과 원문의 계산 문구 대조를 내보내기 품질 기록, API 응답과 화면에 연결했다. 구현과 로컬 검증을 마쳤으며 Q1b 전체 완료나 보고서 품질 통과는 아니다.**

## 목적과 승인 범위

사용자의 SlideCaptain 개발 재개 승인을 Q2d 인계의 다음 최소 단위로 수행했다. 내보내는 PPTX와 동일한 입력에서 수치 대조를 다시 수행하고, 그 파일에 대응하는 판정과 미수행 사유를 보존하는 것이 목적이다. 합성 자료만 사용했다. 실제 AI 호출, 회사 자료 외부 전송, 커밋/푸시/머지와 배포는 수행하지 않았다.

브랜치는 `codex/phase-5b`, 시작과 종료 HEAD는 `62d7b61`, remote는 `https://github.com/blazethrottle/slidecaptain.git`이다. 시작부터 기존 Q1a~Q2d와 AI 연결 작업이 미커밋/미추적 상태였으며 스테이징은 비어 있었다. pull/브랜치 전환/일괄 스테이징을 하지 않았다. 시작 파일 220개 중 이번 수정 파일 19개를 제외한 201개는 사본과 바이트가 같고, 삭제는 없다. 이번 신규 파일은 인계를 포함해 6개다.

## 완료한 동작

1. `assess_quality`가 현재 덱과 원문으로 Q2d 수치 대조를 직접 다시 계산한다. `preflight-v2` 점검 기록은 숫자 포함 칸 수, 검사/일치/미연결 수, 원문 연결과 기준 문구를 보존한다. 원문 내용을 반영한 수치 fingerprint도 품질 fingerprint에 포함한다.
2. 계산 문구 일치는 `numeric_expressions` 항목만 통과시킨다. 미연결 문구는 확인 필요이며 계획 없음/낡음, 원문 연결 불일치, 계산 없음과 대상 0건은 미수행이다. 미수행 항목의 evaluated/failed는 0이고 미연결 칸 수는 상세에 별도로 남긴다. evidence/narrative/representation/visual/target_renderer는 계속 미수행이며 제출본은 차단한다.
3. 내보내기는 같은 버전의 PPTX와 `.quality.json`을 쓰고 실제 PPTX SHA-256을 기록한다. API 성공 응답에 기존 path와 quality_path/quality를 포함하며 응답의 품질 결과는 게시한 JSON과 같다. API의 `?final=true`도 CLI `--final`과 같은 관문에서 거절한다. 오류 응답의 문자열 detail은 유지한다.
4. CLI quality/export는 덱 옆 `sources/`를 읽는다. 숨김 파일 제외, UTF-8 BOM/cp949 처리는 웹과 같고 읽기/디코딩 실패는 오류로 알린다. CLI의 기본 프리셋과 웹 전역 프리셋은 다를 수 있다. 자료 폴더가 없으면 빈 자료로 검사해 수치 대조를 통과시키지 않는다.
5. 화면은 '내보낸 초안'의 기록으로 수치 집계, 미수행 사유, 항목별 상태와 확인 필요 문구를 보여 준다. 기존 편집 플러시와 내보내기 직전 스냅샷 순서를 유지한다. 결과는 프로젝트 이름에 연결하며 다른 프로젝트에 이전 결과를 표시하지 않는다. 이후 편집본의 현재 판정으로 표시하지 않는다.
6. 과거 preflight-v1 기록은 numeric_review=None으로 읽고 판정을 새로 만들지 않는다. Deck와 q2a/q2b/q2c 저장 버전, 기존 초안/원문/스냅샷/사용량을 보존한다. 재열기와 스냅샷 복원 후 내보내기도 다시 검사한다.

## 검증 결과

| 대상 | 결과 |
|---|---|
| 백엔드 전체 pytest | 1,201개 중 실패 0개, 48.87초 |
| 프런트 전체 Vitest | 296개 중 실패 0개, 29개 파일 |
| 마지막 화면 문구 정리 후 관련 검사 | 19개 중 실패 0개 |
| TypeScript/Vite | 최종 타입 검사와 빌드 통과 |
| OpenAPI/생성 TypeScript | 재생성, 백엔드 스키마 대조 및 프런트 컴파일 통과 |
| 신규 회귀 | 백엔드 20개, 프런트 5개 |
| 같은 입력의 왕복 | 공유 JSON 4종을 실제 내보내기 기록과 프런트 표시에 사용; API/게시 JSON/CLI 결과와 PPTX 해시 대조 통과 |
| 보존 및 실패 | 편집/원문 변경, 재열기/복원, 디코딩 실패, 기존 파일/스냅샷/사용량 보존과 Q1a 게시 실패 회귀 통과 |
| 실제 Chrome | 정상/부호 오류/자료 변경/대상 0건 4개 시나리오 중 미해결 문제 0건 |
| 화면 크기 | 1920px 및 390px 확인; 390px의 문서 scrollWidth=390, 점검 영역 width/scrollWidth=358 |
| 공개 저장소 감사 | 추적 파일 감사와 이번 수정/신규 25개 경로의 별도 감사에서 발견 0개 |
| 공백 오류 | git diff --check 통과 |
| 실제 AI/PowerPoint/독자 평가 | 수행 0건, 미검증 |
| 독립 에이전트 리뷰 | 미수행 |

구현 전 백엔드 10개 실패와 프런트 컴포넌트 부재를 확인한 뒤 구현했다. `engineering:code-review` 기준 자체 검토에서는 원문 변경과 클라이언트 판정 재사용, 미수행/실패 집계, 호환과 실패 시 보존을 확인했다. 실제 화면에서 숫자 집계 설명의 반복과 내부 장 ID 표기를 정리했다. 자동화 통과를 보고서 품질 개선으로 판정하지 않았다.

## 미완료와 다음 행동

다음 최소 단위는 **웹과 CLI의 공통 내보내기 잠금 및 프로세스 간 동시 게시 검사**다. 현재 웹의 단일 프로세스 프로젝트 잠금은 유지하지만 직접 CLI와 잠금을 공유하지 않는다. 같은 출력 폴더의 버전 선택/게시 경합과 두 번째 파일 이동 실패를 실제 별도 프로세스로 검증하고 기존 PPTX/sidecar를 덮어쓰지 않아야 한다. 잠금이 필요한 경로와 해제/실패 조건을 먼저 계획에 명시한다.

전체 검수 이력 목록/조회와 현재 자료 대비 과거 기록의 유효성 표시는 그 다음 단위다. 현재 기록은 내보낸 당시의 자료에 대한 결과이며, 다른 프로그램에서 원문이나 PPTX를 바꾼 사실을 지속 감시하지 않는다. 과거 파일을 현재 판정으로 사용하지 않는다.

Q2d의 원문 메타데이터 해석과 자유로운 문장 의미 검수, 요약 정합성, 자동 수정, 단위 환산, Q3~Q5 및 실제 AI/PowerPoint/독자 평가는 남아 있다. 의미/시각 검수와 제출 관문을 이번 수치 연결만으로 열지 않는다. DiagramSpec 도입안과 기존 AI 연결 인계는 유지한다.

## 실행 환경과 파일 지도

검증용 앱은 `http://127.0.0.1:8771`에서 실행했다. 합성 자료 4개만 사용하는 별도 서버이며 AI 제공자는 연결하지 않았다. 데이터와 실행 스크립트는 임시 폴더 `slidecaptain-q1b1-YdX71L`에 있고 서버 PID는 `61770`이다. 종료 시점에는 사용자가 확인할 수 있게 서버와 브라우저 탭을 남긴다. 임시 폴더의 장기 보존과 재부팅 후 서버 동작은 보장하지 않는다.

- 계약과 검사: `backend/slidecaptain/models/quality.py`, `pipeline/quality.py`.
- 게시와 입력: `export/exporter.py`, `server/app.py`, `storage/file_store.py`, `__main__.py`.
- 화면: `frontend/src/screens/ExportQualitySummary.tsx`, `ProjectView.tsx`, `api/client.ts`, `styles.css`.
- 회귀: `backend/tests/test_export_quality.py`, `test_quality.py`, `fixtures/q1b1-quality.json`, `frontend/src/screens/ExportQualitySummary.test.tsx`, `ProjectView.test.tsx`.
- 진본: [단위 계획](../plans/2026-09-13-q1b1-export-quality.md), [로드맵](../plans/2026-08-27-mvp-roadmap.md), [실제 계약](../architecture/2026-09-12-quality-pipeline.md).

공통 `shared-work.md`와 작업 기준을 대조했다. 프로젝트 CLAUDE.md에서 바꾼 것은 최신 상태/인계 포인터 한 항목이며 관리 사본의 운용 규칙을 개정하지 않았다. 위키 정본과 설치된 shared-work.md는 바이트가 같고, 환경 적용은 changed_files=[], 정적 설치 검사는 current/pending_files=[]다. 새 앱 세션의 지침 로드는 미검증이다.

위키 `slidecaptain`과 `Contract-Measure-Roundtrip-Test` 본문을 읽고 현재 세션의 명시적 읽기 로그 2건을 확인했다. 오래된 위키 상태 대신 최신 프로젝트 인계와 현물을 기준으로 범위를 잡았으며, 왕복 검사 원칙을 같은 JSON의 실제 백엔드/프런트 검사에 적용했다. pages_read=2, frames_applied=1, wiki_irrelevant_justified=0, reflux=0이다. 환류는 프로젝트 업무 기록이며 위키 지식/메모리를 새로 쓰지 않았다.
