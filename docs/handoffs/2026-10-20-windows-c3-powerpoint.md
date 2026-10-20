# C3 회사 PC PowerPoint 대조와 가로 막대 수정 (2026-10-20, Windows)

## 현재 상태

- 브랜치 `fix/c3-bar-axis-room`(main `1f1c4ef`에서 분기). main 머지는 사용자 결정 대기다.
- C3 여섯 항목: 사용자가 모두 통과로 판정했다. 에이전트 측정에서 가로 막대의 그림 영역만 수용 기준(1pt)에 불합격이었고, 이 브랜치에서 고쳤다.
- 결과의 진본: [회사 PC 기록](../qa/2026-10-20-windows-c3-powerpoint.md). 실제 AI 호출 0회.

## 커밋

| 커밋 | 내용 |
|---|---|
| `7d6493e` | 가로 막대 그림 영역 아래 여유를 글자 크기의 2.5배로(PowerPoint 값 축 글자 칸 28pt). 시험 1건 추가 |
| 이 문서의 커밋 | 확인 기록, 로드맵, C3 확인 목록 9절, 10-19 Windows 재개 기록과 인계 |

## 검증

- 백엔드 전체(`PYTHONUTF8=1`): 2,937 중 통과 2,890, 건너뜀 47, 실패 0(1,287초). 건너뜀은 Windows에서 POSIX 전용 시험 등이다.
- 프런트 전체(`--maxWorkers=4`): 86 파일, 1,325 통과.
- 새 시험은 고치기 전에 실패했다(24pt < 28.2pt).
- 고친 코드로 만든 bar, bar15 PPTX를 PowerPoint로 열면 그림 영역 위쪽이 12.000pt(계획 12.0), 막대 1 위쪽이 51.650pt(계획 51.65)다. column은 바뀌지 않았다.
- CI: `7d6493e`에서 macOS와 Windows 모두 성공(run 39352662120). 이 문서의 커밋은 문서만 바꾼다.
- 독립 코드 리뷰는 하지 않았다. 바뀐 코드가 상수 한 줄이고 PowerPoint 실측으로 확인했기 때문이다. 머지 전에 리뷰가 필요하면 사용자가 정한다.

## 사용자 결정 대기

1. `fix/c3-bar-axis-room`의 main 머지.
2. 회사 PC 확인 이월표 (16): 차트 미리보기와 PowerPoint의 차이(눈금선과 중간 눈금 글자, bar15의 값 글자와 눈금선 겹침, 가로 막대 값 축 글자 위치 약 11pt). 어느 쪽에 맞출지.
3. (17): 페이지 제목 글자 크기를 키우고 차트 영역 비율을 줄이는 요청의 범위(차트 장만 또는 모든 템플릿)와 시안.
4. (18): 차트 값 소수 2자리 기본 표기. 원문 그대로 보이는 지금 계약과 충돌한다.
5. (19): 상태 아이콘의 통과 판정이 실제 앱 상태에서 본 것인지.

## 다음 즉시 행동

1. 문서 커밋의 양 OS CI 결과를 확인한다.
2. 사용자 결정을 받는다. 머지 뒤 개발선은 main이다.
3. (16)~(18)은 결정 뒤 계획서를 새로 쓴다. 제목과 차트 비율, 소수 표기는 렌더 계획과 기존 덱의 내보내기 현재성에 영향이 있으므로 D4 릴리스 안내 목록과 함께 다룬다.

## 운용 사실

- 이 PC의 PowerPoint는 PowerShell COM(`New-Object -ComObject PowerPoint.Application`)으로 구동할 수 있다. 사용자가 이미 PowerPoint를 열어 두었으면 같은 프로세스에 붙으므로 `Quit()`을 부르지 않고, 연 사본만 닫는다. 측정 스크립트는 회차 `c3-evidence/powerpoint-20261020/`에 있다.
- COM의 `PlotArea.InsideTop`과 `InsideLeft`는 차트 틀 기준보다 4pt 작게 나온다. `Point.Top`과 `Slide.Export` PNG 픽셀이 차트 틀 기준으로 서로 맞는다.
- 사용자 피드백 원본은 저장소 루트에 있고 Git 추적 대상이 아니다(`.gitignore`에도 없음). 커밋하지 않는다. 사본은 회차 `c3-feedback-user-20261020.json`이다.
- 앱 서버(8870)는 이 세션 시작 시점에 꺼져 있었고 양식 서버(8871)는 응답했다.

## 파일

- 코드: `backend/slidecaptain/layout/expression.py`(가로 막대 `plot_h`), `backend/tests/test_comparison_charts_spans.py`
- 기록: `docs/qa/2026-10-20-windows-c3-powerpoint.md`, `docs/qa/2026-10-18-c3-check.md` 9절, `docs/qa/2026-10-19-windows-c3-check.md`, `docs/handoffs/2026-10-19-windows-c3-session.md`, 로드맵 「진행 상태」와 회사 PC 확인 이월표 (16)~(19)
- 증거(저장소 밖, `projects/`는 무시 대상): `projects/windows-review/run-20261019-112243-237724/c3-evidence/powerpoint-20261020/`, `c3-feedback-user-20261020.json`
