# 핸드오프: GitHub 동기화와 C3 T4 검수 기록 준비 (2026-10-19)

## 현재 상태

최신 main `5b00600`에서 `feat/c3-review-checklist`를 분기했다. 기존 작업 트리는 깨끗했고 `git fetch origin --tags`로 원격 상태와 구버전 호환성 시험 태그를 동기화했다. 기준 main의 Windows와 macOS CI는 성공했다. 기존 C3 구현은 main에 병합되어 있고 실제 PowerPoint 검수 T4는 남아 있다.

이번에는 T4 준비 범위로 검수 양식에 여섯 항목의 확인 방법, 기대 결과, 판정과 관찰 메모를 추가했다. JSON/임시 저장과 복원, 이전 JSON의 미평가 초기화, 다른 회차나 표본 판정 거절을 구현했다. 판정의 진본은 [확인 기록](../qa/2026-10-19-c3-review-kit.md)이다. 실제 AI 호출은 0회다.

## 커밋과 검증

| 커밋 | 내용 |
|---|---|
| `5b00600` | 동기화한 main 기준 |
| 이 문서가 포함된 커밋 | C3 T4 검수 기록 준비, 회귀 시험, 계획/로드맵/최신 인계 갱신 |

백엔드 2,931개(플랫폼 관련 5 건너뜀), 프런트 1,325개, 빌드와 디자인 토큰 검사, 검수 준비 시험, Chromium 저장/다운로드/복원, 독립 리뷰를 통과했다. OpenAPI/타입 무변경과 공개 저장소 이력 감사도 확인했다. 새 커밋 CI 결과의 진본은 해당 GitHub PR Checks다. PR은 main 병합 전에 검토할 변경 단위로 남긴다.

## 다음 즉시 행동

1. 이 브랜치 PR과 해당 커밋의 두 OS CI 결과를 확인한다. 실제 회사 PC 검수는 이 브랜치 또는 병합 뒤 main에서 진행한다.
2. `Windows검수준비.bat`로 새 합성 회차를 만든다. 양식의 'C3 회사 PC 확인 항목' 여섯 개를 미리보기와 PowerPoint에서 확인하고 JSON을 저장한다. 실제 자료 폴더와 실제 AI 호출은 사용하지 않는다.
3. C3R-05 라벨 이동 범위/선택 테두리는 사용자가 판정한다. 상태 아이콘은 실제 앱 상태를 재현하지 못하면 미평가로 둔다. 이 양식의 문자만 확인한 것은 앱 검수가 아니다.
4. 결과를 [C3 확인 기록](../qa/2026-10-18-c3-check.md)과 로드맵 회사 PC 이월표에 반영한다. D4 릴리스 안내와 구현은 다음 단계다.

## 미완료와 결정

PowerPoint 표시, Windows 앱 아이콘, C3R-05 사용자 판정, C3R-08 실제 AI 생성은 미완료다. 새 제품 동작이나 렌더 계약은 바꾸지 않았다. 기존 이월의 담당은 유지한다. 전체 개발 단계를 완료했다고 보지 않는다.

## 파일 인덱스

- 준비: `scripts/prepare_windows_review.py`, `scripts/windows-review-form.html`
- 회귀: `backend/tests/test_windows_review_kit.py`, `frontend/src/test/windowsReviewForm.test.js`
- 계획: `docs/plans/2026-10-18-revision-d3-wrapup-c3.md` 10절
- 검증: `docs/qa/2026-10-19-c3-review-kit.md`
- 진행/이월: `docs/plans/2026-08-27-mvp-roadmap.md`
