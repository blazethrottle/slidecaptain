# Q1b 세 번째 단위 인계: 검수 이력 조회

작성: 2026-09-13. 사용자 요청: "slide captain 개발 작업 계속 진행 승인".

## 종료 지점과 승인 범위

최신 Q1b 두 번째 단위 인계의 다음 작업인 검수 이력 목록/상세와 현재 저장본 대비 대조를 구현하고 검증했다. 저장 당시 결과를 보존하고 실제 PPTX/현재 입력과 다른 상태를 구분하는 읽기 전용 기능이다. 사용자 입력 보존에 필요한 자료 저장 경합 수정도 포함한다. [단위 계획](../plans/2026-09-13-q1b3-export-history.md)과 [로드맵](../plans/2026-08-27-mvp-roadmap.md)을 갱신하고 여기서 멈춘다.

시작/종료 브랜치는 `codex/phase-5b`, HEAD는 `a8c6d7a`다. 기존 누적 미커밋 변경과 빈 스테이징을 보존했다. 커밋, pull, push, merge, 배포와 실제 AI 호출은 하지 않았다. 사용자 사용 중인 서버/프로젝트를 수정하지 않고 합성 자료용 임시 서버에서 검증했으며, 검증용 서버와 생성한 Chrome 탭은 종료했다.

## 실제 구현

- `GET /api/projects/{name}/exports?offset=0&limit=20`과 `GET /api/projects/{name}/exports/{export_id}`. 모든 이력 응답은 no-store이며 목록 상한은 100개다. 제목 변경 전 파일과 고아 파일도 포함하고 실제 파일 수정 시각으로 정렬한다.
- 품질 기록, 실제 PPTX SHA-256, 현재 저장된 덱/프리셋/원문 식별값을 독립 상태로 반환한다. 기록 손상, 누락, 미지원 버전, 없는 해시와 구형 preflight-v1을 구분하며 결손을 모델 기본값으로 보충하지 않는다.
- 덱/원문 읽기 실패는 현재 입력 대조만 unavailable로 만든다. 복구가 필요한 프로젝트에서도 과거 기록을 열 수 있다. 이력 조회는 덱, 자료, 스냅샷, 사용량, 출력과 잠금 파일을 만들거나 수정하지 않는다.
- 파일과 디렉터리 교체 중 외부 내용을 읽지 않도록 POSIX 디렉터리 fd를 고정했다. Windows에는 네이티브 핸들/최종 경로 대조 분기를 두었다. 플랫폼 경계와 미검증은 아래와 [아키텍처](../architecture/2026-09-12-quality-pipeline.md)의 실제 계약을 따른다.
- `검수 이력` 탭에서 목록, 상세, 새로고침과 페이지 이동을 제공한다. 저장 당시 결과와 조회 시점을 표시하고 손상된 이력에 내보내기 성공 문구를 붙이지 않는다. 늦은 목록/상세 응답이 다른 선택이나 프로젝트를 덮지 않는다.
- 미저장 자료 본문은 수동 저장 후 이동하도록 보호한다. 보고 정보 저장 전후로 본문 변경을 확인하고 자료 읽기/저장 응답의 요청 소유권을 검사한다. 이전 자료의 늦은 저장 응답이 현재 자료를 저장된 것으로 바꾸지 않는다. 성공적으로 이동하면 앞선 이탈 오류를 해제한다.

기존 Deck/StoryPlan/QualityReport 저장 버전, 내보내기 응답, AI 동의와 변경 API 헤더 규약은 유지했다. 과거 결과를 수정하거나 제출 가능 상태로 승격하지 않는다.

## 검증 결과

| 대상 | 관측 결과 |
|---|---|
| 백엔드 전체 | 수집 1,259개 중 1,258개 통과, 1개 미실행, 실패 0개 |
| 새 이력 회귀 | 43개 중 42개 통과, Windows 네이티브 1개 미실행 |
| 프런트 전체 | 30개 파일의 312개 중 실패 0개 |
| 타입/빌드 | OpenAPI/생성 TypeScript 반영, 현재 앱 스키마 일치 테스트와 tsc/Vite 프로덕션 빌드 통과 |
| 실제 로컬 HTTP | 목록 2개/상세 5개, 합계 7개 응답의 no-store/기록/해시/상태 대조 중 문제 0개. 조회 전후 합성 프로젝트 파일 18개의 SHA-256 유지 |
| Chrome | 합성 프로젝트 2개에서 정상 상세, 누락/변조/손상, 저장 후 낡은 입력 표시, 복구 필요 상태, 미저장 본문 보호와 저장 후 정상 이동 확인 |
| 독립 코드 리뷰 | 별도 읽기 전용 검토자의 계획/구현 발견을 수정하고 재검토. 최종 추가 필수 수정 없음 |
| 공개 저장소 감사 | 추적/미추적 비무시 파일 234개 중 경로/내용 규칙 발견 0개. 신규 줄 공백/금지 구두점과 git diff --check 문제 0개 |

구현 전 목록 API 404와 UI 컴포넌트 부재를 확인했다. UI 최초 실패는 테스트 수집 실패이며 여러 검사가 실행 후 실패한 것으로 세지 않았다. 독립 리뷰의 경로 교체, 미저장 본문 유실, 늦은 읽기/저장 응답 경합을 실패 사례로 재현한 뒤 회귀를 추가했다. 백엔드 전체는 최종 읽기 경계 변경 후, 프런트 전체와 빌드는 마지막 화면 전환 오류 해제 후 실행했다.

주요 실행 명령은 저장소 루트 기준 다음과 같다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/backend" backend/.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
backend/.venv/bin/python backend/scripts/dump_openapi.py
npm --prefix frontend run generate-types
backend/.venv/bin/python scripts/audit_public_repo.py
git diff --check
```

OpenAPI 생성은 backend 디렉터리에서 `scripts/dump_openapi.py`를 실행해도 된다. 새 미추적 파일은 기본 공개 감사 범위 밖이므로 이번에는 동일 감사 함수에 전체 비무시 파일 목록을 전달해 함께 확인했다. 문서 갱신 후 저장소 메타데이터 검사 37개도 통과했고 독립 문서 대조에서 필수 정정은 0건이었다. 검사 결과는 품질 점수나 실제 PowerPoint 표시 통과를 뜻하지 않는다.

## 독립 리뷰 반영과 보존

계획 리뷰에서 덱 부재/손상 시 접근, 원시 기록 필수값, exporter가 이미 허용한 파일명을 보완했다. 구현 리뷰에서 일시적인 디렉터리 교체와 Windows junction 전제, 미저장 본문 이탈, 보고 정보 저장 중 편집, 늦은 자료 읽기와 이전 자료 저장 응답, 복구 화면 탭 표시를 수정했다. 별도 검토자가 마지막 자료 응답 소유권 수정까지 재현 확인했다. `engineering:code-review` 지침을 사용했으며 저장소가 요구하는 superpowers 스킬은 설치 검색에서 찾지 못해 실제 제공되는 독립 리뷰 경로로 수행했다. 이전 Q1/Q2 코드 전체나 누적 브랜치 전체의 독립 리뷰 완료로 소급하지 않는다.

시작 시 추적/미추적 비무시 파일 226개를 임시 tar로 백업했다. 종료 대조에서 207개는 바이트 동일, 이번 단위 관련 19개는 수정, 8개는 신규이며 기존 파일 삭제는 0개다. tar가 추가한 AppleDouble 메타데이터는 원본 파일과 구분해 계산했다. 기존 스테이징은 계속 비어 있다. 백업과 합성 검증 스크립트는 저장소 밖 `/tmp/slidecaptain-q1b3-KYMfrB/`에 남겨 추적 파일이나 사용자 프로젝트에 섞지 않았다.

`CLAUDE.md` 수정은 프로젝트 정본의 최신 인계 포인터 갱신이며 공통 운용 지침의 설치 사본 수정이 아니다. `AGENTS.md`가 해당 정본을 가리키는 구조와 shared-work의 보존/검증/승인 범위를 대조했다. 공통 규칙과 전역 설치 파일을 변경하지 않았다. 새 위키 세션의 환경 동기화는 변경 없음으로 확인했으며 새 앱 세션의 지침 읽기 검증과는 구별한다.

## 미완료와 재심할 전제

- Windows 실기기/새 CI에서 게시 잠금, 네이티브 핸들, 경로 대조와 junction 경계는 미검증이다. 전용 테스트 1개의 skip은 통과가 아니다. 네트워크 드라이브/동기화 프로그램과 전원 차단 내구성도 보장하지 않는다.
- 이력은 조회 시점과 현재 저장본 기준이다. 외부 프로그램 변경은 새로고침해야 보이며, 별도 프로세스의 덱/원문 편집 전체나 품질 기록/PPTX 두 파일 게시를 하나의 트랜잭션으로 묶지 않는다.
- 파일 해시와 입력이 모두 일치해도 의미/시각/목표 앱 검수는 미수행이다. `final_export_allowed`는 false이며 제출본 요청 거절을 유지한다.
- 실제 AI 호출/로그인, 목표 PowerPoint 렌더와 독자 품질 평가 대상은 이번에 0건이다. 합성 UI 검증을 실제 보고서 품질 향상의 증거로 쓰지 않는다. 이번 Chrome 확인은 데스크톱 기본 창이며 모바일 폭 검증은 하지 않았다.
- 과거 Q2 단계의 미등록 비교/산식 탐지, 원문 조건의 의미, 요약 정합성과 단위 환산은 남아 있다. Q3~Q5는 이번에 구현하지 않았다.

## 다음 행동과 관련 파일

다음 구현 후보는 [DiagramSpec 도입안](../plans/2026-09-13-diagram-spec-adoption.md)의 첫 단위다. 모델/fixture와 중복 ID, 끊긴 관계, 근거 참조의 실패 경계부터 계획 리뷰로 확정한다. 기존 Deck/저장본을 변경하지 않고 누적 작업을 보존할 격리 방법부터 정한다. 결정론 배치, UI/PPTX 렌더와 AI 연결을 같은 단위에 묶지 않는다. Windows 검증 이월은 가능한 기기나 새 CI에서 별도로 해소해야 한다.

핵심 파일:

- `backend/slidecaptain/models/export_history.py`, `export/history.py`, `export/windows_history.py`
- `backend/slidecaptain/server/app.py`, `storage/file_store.py`, `backend/tests/test_export_history.py`
- `frontend/src/screens/ExportHistoryPanel.tsx`, `ExportQualitySummary.tsx`, `ProjectView.tsx`, `SourcesScreen.tsx`와 관련 테스트
- `backend/openapi.json`, `frontend/src/api/client.ts`, `types.ts`, `frontend/src/styles.css`
- 현재 상태 정본인 로드맵, 품질 개발 계획, 제품 기획, 아키텍처와 이번 단위 계획

위키 재사용: `wiki/projects/slidecaptain.md`는 이전 맥락만 참고하고 최신 인계/브랜치로 갱신 상태를 확인했다. `wiki/concepts/Contract-Measure-Roundtrip-Test.md`를 API 응답/저장 기록/실제 파일의 왕복 대조에 적용했다. 명시적 읽기 로그 2건을 확인했다. `pages_read=2`, `frames_applied=1`, `wiki_irrelevant_justified=0`, 신규 지식 환류 0건이다. 재사용의 품질 효과를 자기 판정하지 않았으며 이번 발견은 프로젝트 계획/인계에 환류했다. 위키 지식 본문과 무관한 대기 큐는 수정하지 않았다.
