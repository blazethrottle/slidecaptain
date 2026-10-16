# 핸드오프: 회사 PC(Windows) D3 관문 확인과 Windows 수정 (2026-10-16)

[회사 PC 재개 인계](2026-10-16-windows-resume.md)의 2절부터 5절까지를 회사 PC에서 마쳤다. 결과의 진본은 [회사 PC D3 관문 확인 기록](../qa/2026-10-16-windows-d3-gate-check.md)이다. 확인 중 찾은 Windows 결함과 사용자가 PowerPoint로 판정한 결함 일부를 브랜치 `fix/windows-company-pc-20261016`에서 고쳤다. 새 기능 개발은 하지 않았고, 실제 AI 호출은 0회다.

## 1. 지금 상태

- 확인 대상은 main `688ad3b`이다. D3 관문의 회사 PC 항목(실제 PowerPoint 표시, 한글 입력기, Windows 150% 배율, 사람의 시각 판정, 터치와 펜)은 모두 결과가 나왔다. 확인 기록 3절의 요약표를 본다. 2026-10-16 사용자 결정으로 D3 관문을 통과로 기록했다.
- 수정 브랜치는 main `688ad3b`에서 분기했다. 코드 커밋 6개, 문서 커밋, 후속 리뷰 반영 커밋으로 이뤄진다. 2026-10-16 사용자 결정으로 `--no-ff` 머지했다(`bb97baa`). 개발선은 main이다.
- 회사 PC 작업 사본: 본 클론은 main이다. 수정에 쓴 `.worktrees/win-fixes-1016`(브랜치 작업 사본)은 머지 뒤 지웠다. 브랜치 `fix/windows-company-pc-20261016`은 로컬과 원격에 남아 있다(삭제는 결정하지 않음).

## 2. 이번 커밋

| 커밋 | 내용 |
|---|---|
| `470b618` | 시험 격리가 진짜 `winreg`와 `ctypes`의 쓰기 함수를 막는다(실제 HKCU 글꼴 등록 오염) |
| `6bd44d8` | 잠금 시험의 PID 단언(Windows 가상 환경 실행기), 라우트 대조 도구의 UTF-8 읽기(SV-07) |
| `e31a654` | 차트 값과 눈금의 숫자 서식을 미리보기 글자와 맞춤(`1200.`의 끝 마침표) |
| `565beaa` | 독립 리뷰 반영(세로 막대 축 글자 여백, 소수 축 0 눈금, 시험 보강) |
| `2ee1ab0` | 분류표 나열 칸 세로 가운데 정렬(사용자 PowerPoint 판정) |
| `1b106aa` | 세로 막대 축 아래 범주 이름 자리 확대(PowerPoint가 계획대로 그리자 드러난 잘림) |
| `db83c14` | 확인 기록, 로드맵 정정과 회사 PC 확인 이월표, D3c 확인 기록 정정, 이 핸드오프, 루트 `CLAUDE.md` 최신 인계 줄 |
| `26a8c99` | 후속 리뷰 반영: 시험 보조 함수 2건(레지스트리 복원 형식, 라벨 설정 완비 검사), 확인 기록과 이월표 정정(소수 축 PowerPoint 재확인, (6) 분류표, (5) 범주 이름 위치, (13) 좁은 높이 구간) |

| `bb97baa` | main 머지(`--no-ff`, 사용자 결정) |
| 이 커밋 | 사용자 결정(머지, D3 관문 통과, 정리) 기록, 회사 PC 확인 이월표 (14) 등재 |

검증(회사 PC): 백엔드 전체 2,890 중 실패 0(통과 2,844, 건너뜀 46). 프런트 코드는 바꾸지 않았고 main 기준 1,276 중 실패 0. 화면 빌드, desktop 29건, 공개 저장소 감사 0건. 독립 리뷰어 1명이 두 번 검토했다(누적 약 29.3만 토큰). 첫 리뷰는 critical 0, major 1, minor 5, nit 6, 후속 리뷰는 critical 0, major 0, minor 2, nit 5였다. 리뷰가 지적한 변형은 모두 이제 시험이 잡는다. push 뒤 CI(run 38862091540, `db83c14`)는 Windows와 macOS 모두 성공했다. 차트 수정은 PowerPoint build 20430 렌더로 확인했다.

## 3. 다음 즉시 행동

1. 다음 작업 후보는 D3 마무리 둘째 계획이다. 범위는 최종 리뷰 이월표의 (2), (3), (7)~(13), (19)~(25)와 회사 PC 확인 이월표의 (1), (4), (5), (7), (13)이다.

## 4. 사용자 결정 (2026-10-16, 처리 완료)

1. 브랜치 `fix/windows-company-pc-20261016`의 main 머지: 머지했다(`bb97baa`). 머지 결과의 파일 내용은 CI가 두 OS에서 성공한 `26a8c99`와 같다.
2. D3 관문: 통과로 기록했다(로드맵 D3 행, D3c 확인 기록 5절, 회사 PC 확인 기록 3절).
3. 회사 PC의 로컬 브랜치 `feat/windows-feedback-revision`(로컬 전용 커밋 `bfee429`): 사용자 결정 "전체 프로덕트에 문제가 없다면 삭제". 그 커밋의 2026-10-06 남은 작업 인계를 main과 대조했다. 내용은 이후 D2와 D3 계획, 로드맵, 개정 계획(`2026-10-02-windows-feedback-revision.md`)에 반영됐거나 낡았고, 담당 없이 남은 한 항목(bar/column 합성 표본의 `unlinked_expression`)은 회사 PC 확인 이월표 (14)로 옮겼다. 그 뒤 로컬 브랜치를 지웠다. 파일 사본은 저장소 밖 `slidecaptain-backups/2026-10-16-before-main-switch/`에 남아 있다.
4. 저장소 밖 시험 산출물: 데스크톱 빌드와 합성 자료 사본(`%USERPROFILE%\sc-b5`, 약 526MB)을 지웠다. 검수 회차(`projects/windows-review/run-20261016-123040-652004`, 무시 경로)는 남겼다.

## 5. 회사 PC에서 바꾼 환경 (사용자 결정)

- 사용자 계정 HKCU 글꼴 등록 2건(`Noto Sans KR`, `Noto Sans KR Bold`)을 지웠다. 두 값 모두 시험이 남긴 pytest 임시 경로였다. 백업: `slidecaptain-backups/2026-10-16-before-main-switch/hkcu-fonts-before-cleanup.reg`.
- 사용자 환경 변수 `TZ=Asia/Seoul`을 지웠다. 이 값 때문에 Windows의 파이썬이 현지 시각을 UTC+1로 계산했다. Windows 시간대는 Korea Standard Time이다. 이전 값과 되돌리는 명령: 같은 백업 폴더의 `user-env-TZ-before-removal.txt`.
- 본 클론의 `.git/info/exclude`에 `feedback/`를 더했다(회사 피드백 파일이 공개 저장소에 들어가지 않게).

## 6. 미완료와 재심 대상 전제

- 확인하지 못한 것: `Windows검수준비.bat` 더블클릭 실행, 피드백 HTML 양식, 독립 앱의 "저장하지 않은 변경" 경고와 "계속 작업 / 취소 후 닫기" 대화 상자의 실제 표시(회사 PC 확인 이월표 (12)).
- 전제: 확인은 PowerPoint 16.0 build 20430 한 버전이다. 축 서식에 따라 PowerPoint가 차트 그림 영역을 계획과 다르게 그린 사례가 있었으므로, 다른 PowerPoint 버전에서 같은 결과를 가정하지 않는다.
- 회사 PC 확인 이월표 (8) `TZ` 방어는 사용자 결정으로 기록만 했다. 다른 사용자 PC에도 같은 설정이 있을 수 있다.

## 7. 파일 인덱스

- 확인 기록: `docs/qa/2026-10-16-windows-d3-gate-check.md`
- 로드맵: `docs/plans/2026-08-27-mvp-roadmap.md`의 D3 행 정정, 「2026-10-16 회사 PC 확인 이월표」, D2a 이월표 정정
- D3c 확인 기록 5절 정정: `docs/qa/2026-10-13-d3c-check.md`
- 코드: `backend/tests/conftest.py`, `backend/tests/test_fonts.py`, `backend/tests/test_service_lock.py`, `backend/tests/test_desktop_routes_script.py`, `scripts/check_desktop_routes.py`, `backend/slidecaptain/layout/expression.py`, `backend/slidecaptain/export/pptx_writer.py`, `backend/slidecaptain/layout/templates.py`, `backend/tests/test_comparison_charts_spans.py`, `backend/tests/test_layout_engine.py`
