# Q3 비교 차트와 문장 일부 강조

작성: 2026-09-30. 사용자의 잔여 계획 일괄 처리 요청으로 의미 표현의 미지원 부분을 기존 계약 위에 확장한다. 원래 텍스트/표/근거와 저장 버전은 보존하며 실제 AI 호출은 하지 않는다.

- Slide의 optional `chart`는 `comparison-chart-v1`, 기존 comparison ID, bar/column 종류만 받는다. table 슬라이드에서 명시적으로 선택하며 원래 columns/rows/footnote를 그대로 저장한다. 임의 값/근거/좌표, 다수 점, line/pie, 음수, 미지원 환산은 차단한다. 해당 장의 claim에 연결된 current StoryPlan의 등록 비교와 두 원문 근거만 소비한다.
- `build_render_plan(..., sources=None)`의 optional 실제 자료를 추가한다. 차트가 있을 때 sources 누락, 낡은 story, 원문 hash/위치/발췌 불일치, incompatible/정보 부족 비교나 해석 불가 값을 오류로 반환한다. 원래 표로 조용히 대체하지 않는다. 명시적 단위 환산은 기존 결정론 계약이 확인되는 범위만 소비한다.
- ChartPlan은 실제 근거 ID, exact 문자열 값, 단위/기간/분모 조건과 결정론 축/plot/bar 외곽을 포함한다. PPTX는 편집 가능한 native chart, preview는 같은 의미/외곽의 SVG를 소비한다. 서로 다른 렌더러의 실제 라벨/축 배치 일치는 미검증이고 Q4 실제 PowerPoint 검수가 필요하다.
- Slide.text_spans는 기존 eyebrow/subtitle/text/conclusion/bullets의 text_sha256, Unicode codepoint start/end, bold/accent 역할을 받는다. bullets만 index가 필요하고 빈/중첩/범위 밖/낡은 텍스트/미지원 슬롯은 거절한다. 프런트는 같은 텍스트를 편집하면 해당 span을 지우고 원문을 보존한다.
- Render Para.runs와 line_runs는 원문 전체를 보존한다. span bold는 번들 bold 폭을 실제로 반영해 줄바꿈/용량을 재계산하고 단어를 생략하거나 글자 크기를 줄이지 않는다. 줄별 runs를 preview가, 전체 runs를 PPTX가 소비한다. 원래 diagram/폰트 미지원 경계는 유지한다.
- 차트/강조 없는 저장/렌더 optional 기본 필드는 직렬화에서 제외해 기존 fingerprint를 유지한다. 보호 재작성은 차트가 참조하는 원래 비교/claim/evidence도 서버가 보존하도록 확장한다.

소유권: 백엔드 담당은 새 표현 모델, Deck/Render 모델, chart/span 레이아웃, writer와 관련 검증, root는 서버 sources 전달/API/CLI/프런트/SVG와 생성 타입, story 담당은 차트 근거 보호 재작성 경계를 맡는다. 다른 담당의 변경은 보존한다. 구현 전 계획 독립 리뷰, 변경 전 실패 검사, 데이터/표/문장 보존과 fingerprint 골든, stale source/비교 불가/미지원 chart/overlap span/실제 bold 용량/편집 가능한 PPTX 반례를 수행한다. 실제 PowerPoint와 독자 품질, AI 도식/차트 실호출은 미검증으로 남긴다.

구현 상태: backend source-bound bar/column 및 exact text spans, native editable PPTX chart와 run 스타일을 구현했다. Python-pptx native chart는 [공식 chart API](https://python-pptx.readthedocs.io/en/latest/user/charts.html)의 data/workbook 계약을 사용한다. embedded workbook의 XlsxWriter 문자열→수식/URL 자동변환은 끄고 원문 category/series label을 literal string으로 보존한다. chart/span 없는 Deck와 quality fingerprint 골든을 유지하며 실제 bold face 폭을 줄바꿈에 사용한다. 독립 backend 검토에서 관련 53개(독립 반례 5개 포함) 통과, 추가 formula/URL embedded workbook 반례 포함 writer 관련 57개 통과했다. source 자료의 의미/독자 품질 또는 실제 PowerPoint 배치 통과를 뜻하지 않는다.

UI는 ExpressionPanel에서 기존 comparison opt-in, 원래 table 내용 보존, 읽기 전용 원문 선택과 Unicode codepoint span 범위를 처리한다. text edit 시 중앙 helper로 대상 span을 제거하고 template 전환 손실 안내에 chart/span을 포함한다. chart 원근거 재작성 보호 3개 반례와 기존 rewrite/unit conversion/semantic 124개를 별도 검증했다. 프런트 구현 인계는 `review/q3-frontend-implementation.md`에 있으며 타입/build/합성 UI 확인은 root 인계에서 최종 집계한다.
