# Q3b 공통 도식 렌더 인계

작성: 2026-09-13. 사용자 요청은 SlideCaptain 개발 계속 진행이다. [이전 배치 인계](2026-09-13-q3b-diagram-layout-handoff.md)의 다음 단위를 [렌더 계획](../plans/2026-09-13-q3b-diagram-render.md)으로 확정했다.

## 완료 범위와 종료 지점

원래 DiagramSpec/Evidence/Preset/폰트 수치와 공통 문구에서 한 페이지 RenderPlan을 재계산한다. 기존 Preview와 PPTX 라이터가 같은 노드/관계/조건, 좌표, 명시적 줄바꿈과 스타일을 소비한다. 제목/분류 라벨/부제/각주/페이지 번호의 영역을 예약하고 겹침/넘침을 차단한다. PPTX는 이미지 대신 편집 가능한 도형/텍스트/선/화살표를 사용한다.

이번 단위는 공통 렌더 연결이다. 앱에서 도식을 생성/편집/저장하는 경로와 새 API/CLI는 추가하지 않았다. 기존 Deck/StoryPlan과 저장 버전은 유지했다. RenderPlan 출력에 선택적인 도식 페이지를 추가하고 OpenAPI/TypeScript를 함께 갱신했다. 실제 AI, 목표 PowerPoint, Windows 새 CI와 독자 품질은 미검증이다.

브랜치는 `codex/phase-5b`, 시작 HEAD는 `a8c6d7a`다. 누적 미커밋 파일 244개와 빈 스테이징을 백업하고 detached 작업 트리에서 구현했다. 이번 변경 21개(기존 14개, 신규 7개)만 시작 해시 대조 후 원본에 반영했다. 무관한 기존 파일 230개와 빈 스테이징은 보존했다. 커밋/pull/push/merge/배포와 기존 앱 서버 재시작은 수행하지 않았다. 모든 검증 자료와 내보내기는 합성 임시 자료다.

## 구현 계약

- `layout/diagram_page.py`의 `build_diagram_render_plan`은 의미 입력을 매번 다시 검증한다. 공통 슬롯은 기존 `slide_geometry`와 프레임 헬퍼를 사용한다. 불가 입력에는 `DiagramRenderBlocked.issues`를 반환하고 부분 페이지를 내지 않는다.
- `SlidePlan.diagram`의 `DiagramPagePlan(q3b-render-v1)`은 도식 배치/공통 프레임/배경/전체 입력 fingerprint를 담는다. 문구와 페이지 번호도 식별값에 포함한다. 의미/브라우저/PowerPoint/독자 상태는 계속 not_run이며 합성 화면 관측을 저장된 품질 승인으로 올리지 않는다.
- Preview는 SVG rect의 테두리 중심선, 선/화살표 점과 고정 높이 텍스트를 사용한다. 슬롯 편집 콜백을 호출하지 않는다. 모든 관계 방향과 조건, 근거 ID를 보존한다. 점선/파선 수치는 백엔드에서 계산한다.
- PPTX는 고정 줄마다 문단을 만들고 자동 줄바꿈/자동 맞춤을 끈다. 문단 앞뒤 간격, 행간과 한글/영문 폰트를 명시한다. 의미 ID/근거/조건을 도형 이름과 대체 설명에 남긴다. 선 끝은 flat, 화살표는 외곽선 없는 채움이다. pt를 EMU로 바꾸는 마지막 정밀도 한계는 남는다.
- 기존 일반 템플릿은 기존 자동 줄바꿈을 유지한다. `pipeline/quality.py`는 비어 있는 새 도식 필드만 fingerprint에서 제외해 과거 preflight-v2 식별값을 유지하며 실제 도식 내용은 포함한다.
- 현재 라이터의 실제 표현 범위로 페이지 72~4032pt, 글자 1~4000pt, 행간 1584pt 이하를 검사한다. 글자/행간의 0.01pt 표현과 최소 1EMU로 표현 가능한 선 굵기를 요구한다. 원래 배치 계산기의 지원 범위를 제품 렌더 범위로 그대로 간주하지 않는다.

## 검증

| 대상 | 관측 결과 |
|---|---|
| 신규 렌더 검사 | 백엔드 33개, 프런트 4개 중 실패 0개 |
| 백엔드 전체 | 1,457개 중 1,456개 통과, Windows 전용 1개 미실행, 실패 0개 |
| 프런트 전체 | 31개 파일의 316개 중 실패 0개 |
| 타입/빌드 | OpenAPI/TypeScript 갱신, tsc/Vite 빌드 통과 |
| 공유 fixture | 실제 백엔드 RenderPlan을 프런트/PPTX 재열기 검사에서 함께 대조 |
| 실제 Chrome | 정상 흐름/제안, 역방향 참조/굵은 테두리, 배치 불가 3개 중 표시 문제 0개 관측 |
| Chrome 글꼴 | 합성 검증 페이지에서 번들 regular/bold 두 파일을 로드하고 loaded 상태 확인 |
| PPTX | XML/재열기에서 좌표/문구/폰트/행간/빈 줄/근거/선/화살표를 대조하고 텍스트 수정 후 저장·재열기 확인 |
| 독립 계획/구현 리뷰 | 발견 수정 후 최종 재검토의 남은 필수 수정 0개 |
| 독립 합성 경계 | 160개 중 Preset 거절 7개, typed blocked 84개, PPTX 저장/재열기 69개, 예상 밖 예외 0개로 보고 |
| 기존 품질 식별값 | 독립 검토자가 Q2a/Q2b/Q2c 3개에서 시작본과 동일함을 확인 |
| 실제 저장 왕복 | 레거시 빈 덱과 Q2a/Q2b/Q2c 4개 중 차이 0개 |
| 공개 파일 감사 | 반영 대상 전체 일반 파일 251개 중 경로/내용 규칙 발견 0개 |
| 실제 AI/목표 PowerPoint/독자 품질 | 대상 0개, 미검증 |

최초 백엔드 검사는 새 모듈 부재로 수집 실패했고 프런트 4개 검사는 레이어 부재로 실패했다. 전체 회귀에서 과거 품질 fixture 4개의 fingerprint 변화를 발견해 수정했다. 자체 검사에서 16.799999pt 행간이 16.79pt로 절단되는 문제를 정수 centipoint로 고쳤다. 독립 검토의 폰트/페이지/행간/선 범위와 공통 슬롯 overflow는 실패 재현 뒤 수정했고 마지막 코드 변경 후 전체 백엔드를 다시 검사했다. 성공한 프런트 검사와 빌드는 프런트 변경이 없어 반복하지 않았다.

Chrome의 자동 브라우저 연결은 없었고 native 앱 경로로 표시를 확인했다. 앱 시작 도구 응답이 약 53분 지연됐으며, 이후 정상 동작했다. 합성 페이지에는 번들 글꼴을 명시적으로 로드했다. 이 결과가 기존 제품 페이지의 OS 폰트 설치 검증을 뜻하지는 않는다. 임시 Vite 서버만 사용했고 실제 AI 프로바이더에 연결하지 않았다.

## 보존과 다음 행동

백업과 작업 트리, 검사 로그, 합성 PPTX는 저장소 밖 `slidecaptain-q3b-render-miw6vf1j/`에 보존한다. 주요 기록은 `baseline/`, `baseline.json`, `initial-index.patch`, `backend-red.log`, `review-overflow-red.log`, `backend-tests-final.log`, `frontend-tests.log`, `compatibility-check.json`, `final-audit.json`, `applied-preservation.json`, `artifacts/`다. 임시 폴더는 영구 보관소가 아니며 이 인계와 로드맵이 지속 기록이다.

다음 후보는 검증된 도식 의미 입력을 프로젝트 저장본과 읽기 전용 미리보기에 연결하는 첫 단위다. DiagramSpec의 저장 위치/호환성과 수정 후 재계산/검수 만료를 계획 리뷰로 확정하고, 직렬화된 RenderPlan을 신뢰하는 입력 경로는 만들지 않는다. 생성과 자유 편집, 원문 현재성/자유 문장 의미 검수, 분기/비인접 배치와 다른 폰트 지원은 범위를 나누어 진행한다. 실제 목표 PowerPoint 표시와 독자 품질은 별도 검증으로 남는다.

주요 구현은 `layout/diagram.py`, `layout/diagram_page.py`, `models/diagram_render.py`, `models/render.py`, `export/pptx_writer.py`, `pipeline/quality.py`, `frontend/src/editor/DiagramPreview.tsx`와 `Preview.tsx`다. 검사는 `backend/tests/test_diagram_render.py`, `backend/tests/fixtures/q3b-render.json`, `frontend/src/editor/DiagramPreview.test.tsx`에 있다.

## 위키 참조와 환경 관측

`wiki/projects/slidecaptain.md`는 과거 맥락으로 참고하고 최신 작업은 실제 인계/구현으로 확인했다. `Editable-HTML-Diagram-Contract`의 의미/배치/두 소비자 분리와 검사 계층을 대조했으며 기존 개발 계획과 같은 결론이었다. `pages_read=2`, `frames_applied=1`, `wiki_irrelevant_justified=0`, `reflux=0`이고 환류는 업무 기록이다. 기존 측정 원장에 no_effect 1건만 남기며 사용자 품질 판정은 작성하지 않는다.

위키 환경 동기화는 current/changed_files=[]이며 runtime_verified=false다. Mac 읽기 로그에서 두 페이지의 measured-read 기록을 확인했다. 위키의 기존 미커밋 변경 때문에 pull은 수행하지 않았고 로컬 스냅샷을 참고했다. 무관한 큐와 위키 지식 본문은 수정하지 않았다.
