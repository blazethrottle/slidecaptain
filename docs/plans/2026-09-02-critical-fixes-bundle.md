# Critical 결함 소형 수정 묶음 계획서 (2026-09-02)

> 2026-09-02 01:14 회사 PC 전체 리뷰(영역별 리뷰어 5명)가 "단계 5 계획과 별개로 소형 묶음으로 먼저 수정"하라고 권고한 Critical 3건의 구현 계획이다. 그 리뷰 문서는 회사 PC 에만 있고 저장소와 로드맵에 반영되지 않아, Mac Mini 에서 독립 재발견으로 대상을 확정했다 (2026-09-02. 방법: 경계값 탐침 스크립트와 견본 덱 내보내기 대조. 전부 실행으로 재현했고 적대 검증은 세션 한도로 수행하지 못했다).
> 브랜치 `feature/critical-fixes` (main 에서 분기). 완료 후 main 에 머지한다. `codex/phase-5a` 는 그 뒤 main 을 병합해 따라온다 (재배치는 강제 푸시가 필요하므로 하지 않는다).
> 리뷰 게이트 적용 방식 (이 묶음 한정): 계획서 적대 리뷰 1회 → 태스크 3개 TDD 구현 → 커밋별 독립 리뷰와 브랜치 최종 리뷰를 한 리뷰어가 한 번에 수행 (변경 범위가 작아 나눌 실익이 없고, 세션 사용량 한도가 걸려 있다). 이 축약은 이 묶음에만 적용하고 단계 5A 부터는 원래 게이트로 돌아간다.

## 태스크 B: 라이터가 세로 정렬을 항상 명시한다 (세로 정렬, 두 모듈에 걸친 결함)

**재현 (2026-09-02 macOS, `samples/sample_deck.json` 내보내기 후 slide XML 대조)**

| 도형 | 렌더 계획 `Frame.valign` | 미리보기(Preview.tsx) | PPTX `a:bodyPr anchor` |
|---|---|---|---|
| ch02:conclusion, ch04:conclusion, ch06:conclusion (결론 박스) | top | 위 정렬 | **ctr** (세로 중앙) |
| ch06:left_card, ch06:right_card (비교 카드) | top | 위 정렬 | **ctr** |
| 제목, 불릿, 각주, 표지 등 채움 없는 프레임 | top | 위 정렬 | 속성 없음 = top |

원인: `pptx_writer._add_text_shape` 는 채움이나 테두리가 있으면 `add_shape(MSO_SHAPE.RECTANGLE)` 로 자동도형을 만드는데, python-pptx 자동도형의 기본 `bodyPr` 은 `anchor="ctr"` 이다 (`add_textbox` 는 속성이 없어 top). 라이터는 `text_frame.vertical_anchor` 를 설정하지 않으므로 렌더 계획의 `valign` 이 PPTX 에 전달되지 않는다. 결과: 비교 카드의 소제목과 불릿이 PowerPoint 에서는 카드 한가운데에 떠 있고 미리보기에서는 위에 붙어 있다. "레이아웃 진본은 백엔드 하나"(로드맵 결정 1)가 세로축에서 깨진 것이고, 설계서 5.4 "장별 세로 중앙 정렬 금지" 도 어긴 것이다.

**변경**

- `_fill_text_frame` 에서 `tf.vertical_anchor` 를 `frame.valign` 에 따라 **항상** 명시한다 (`top` → `MSO_ANCHOR.TOP`, `middle` → `MIDDLE`, `bottom` → `BOTTOM`). 자동도형과 텍스트박스 모두.
- `Frame.valign` 의 타입을 `str` 에서 `Literal["top", "middle"]` 로 좁힌다 (잘못된 값이 조용히 top 으로 그려지는 일을 막는다). `bottom` 은 넣지 않는다: 미리보기(`Preview.tsx`)가 `middle` 만 처리하므로 `bottom` 을 허용하면 라이터만 아래 정렬을 그리는 새 불일치가 생긴다 (적대 리뷰 F3). OpenAPI 와 프런트 타입을 재생성한다 (`Preview.tsx` 의 `f.valign === "middle"` 비교는 그대로 성립한다).
- 설계서 5.4 에 따라 이 묶음에서는 정합만 회복한다 (전부 top). 결론 박스를 세로 중앙에 둘지는 별도 결정이며, 원하면 `_conclusion_box_frame` 에 `valign="middle"` 을 주는 것만으로 미리보기와 PPTX 가 함께 따라간다.
- 표 셀은 `graphicFrame` 이라 별개다 (셀 세로 정렬 기본 top, 미리보기도 top. 이번 범위 밖).

**테스트 (실패부터)**: `tests/test_pptx_writer.py` 에 (1) 채움 프레임과 채움 없는 프레임 모두 `a:bodyPr anchor="t"` 이 기록된다 (지금은 채움 프레임이 `ctr` 라 실패), (2) `valign="middle"` 프레임은 `anchor="ctr"` 이 기록된다, (3) `tests/test_regression.py` 계열의 견본 내보내기에서 모든 텍스트 도형의 anchor 가 렌더 계획 valign 과 일치한다. `tests/test_deck_schema.py` 또는 `test_layout_engine.py` 에 `Frame(valign="center")` 가 거부된다는 단언을 추가한다.

## 태스크 A: 용량 계약이 실측과 같은 규칙으로 계산된다 (계약 대 실측 불일치)

**재현 (2026-09-02 macOS, 번들 폰트 실측, 기본 프리셋)**

| 슬롯 | 프롬프트가 약속한 한도 | 실제로 넘치지 않는 최대 | 과다 약속 |
|---|---|---|---|
| bullet_box 불릿 전체 | 최대 18줄 | 한 줄 불릿 14개 | 22% |
| summary 요점 전체 | 최대 18줄 | 한 줄 요점 14개 | 22% |
| table 행 수(머리글 포함) | 최대 22행 | 16행 | 27% |
| compare2 카드 불릿 전체 | 최대 17줄 | 한 줄 불릿 11개 (한 불릿 여러 줄이면 15줄) | 35% |
| 환산 안내 "한 줄 약 75자" | 75자 | 불릿 73자, 카드 불릿 33자, 카드 소제목 35자 (안내 "절반" 37자는 넘침) | |
| 결론 박스 "2줄" x 75자 | 2줄 | 4줄로 실측되어 경고 | |

원인 세 가지가 겹친다. (1) `capacity_contract()` 는 가용 높이를 행간 높이로만 나누는데, `measure_bullets()`, 라이터(`space_before`), 미리보기(`marginTop`) 는 항목 사이마다 `bullet_gap`(6pt) 을 더한다. (2) 표의 행 높이는 `행간 + 2 x table_cell_pad_y` = 22.8pt 인데 계약은 16.8pt 로 나눈다. (3) compare2 의 계약 가용 높이(286pt)는 `_build_compare2()` 의 실측 가용 높이(266pt)에서 `2 x box_padding` 을 빼지 않은 값이다. 같은 수식이 두 모듈에 따로 적혀 있다. 부수로 프리셋 여백을 키우면 계약이 음수(`최대 -2줄`)로 프롬프트에 그대로 나간다.

**결과**: AI 가 계약을 지켜도 분량 게이트가 초과 경고를 내고 축약 호출이 한 번 더 나간다 (구독 사용량 낭비 + "AI 가 계약을 못 지킨다" 는 착시). 사용자에게는 계약 안에서 쓴 장이 매번 "넘침" 으로 표시된다.

**변경**

- 계약을 실측과 같은 규칙으로 계산한다. 불릿류 슬롯의 한도는 "한 줄짜리 항목이 전부일 때" 를 기준으로 `floor((available + gap) / (line_height + gap))` 로 정의한다 (여러 줄 불릿은 간격이 줄어 여유가 생기므로 안전한 하한이다. 설계서 5.1 은 계약을 "줄수, 불릿 수, 표 행수" 로 정의하고 있어 이 해석과 맞다). 표는 `floor(available / (line_height + 2 x pad_y))`. 기본 프리셋에서 bullet_box 18 → 14, summary 18 → 14, table 22 → 16, compare2 17 → 11.
- compare2 카드 기하(카드 폭, 카드 높이, 불릿 가용 높이, 안쪽 폭)를 `capacity.py` 의 파생 함수 한 곳에 두고 `_build_compare2()` 와 `capacity_contract()` 가 같은 함수를 호출하게 한다.
- 계약값은 0 이상으로 자른다. 음수 계약은 프리셋 기하가 성립하지 않는다는 뜻이므로 프리셋 검증(단계 5A A 의 "프리셋 유한값 검증" 항목) 에서 막을 문제이고, 이 묶음은 프롬프트에 음수가 나가는 것만 막는다.
- 환산 안내를 실측대로 고친다: 본문 한 줄은 불릿 들여쓰기를 뺀 폭으로 계산(75 → 73자), 카드 안 한 줄은 "그 절반" 대신 실제 값(33자)을 계산해 넘긴다. 프롬프트 문구 "최대 N줄" 을 "최대 N줄 (한 줄짜리 항목 N개 기준)" 으로 바꿔 AI 가 줄 수와 항목 수를 같은 것으로 읽게 한다.
- 전달 경로 (적대 리뷰 F1 반영): 단일 값 `chars_per_line` 을 **칸별 힌트 맵**으로 바꾼다. `capacity.py` 에 `char_hints(template, preset, face) -> dict[str, int]` 를 두어 템플릿별로 라벨과 글자 수를 돌려준다 (bullet_box·summary: `{"본문 한 줄": 73}`, compare2: `{"카드 안 한 줄": 33, "카드 소제목": 35}`, table: `{"본문 한 줄": 73}`, cover: `{"표지 제목": 30, "부제": 60}`, divider: `{"섹션 제목": 35}`). `_contract_block(contract, char_hints)` 는 `- 환산 안내: 본문 한 줄은 한글 약 73자` 처럼 맵을 한 줄로 이어 붙인다. `build_chapter_prompt` 의 `chars_per_line` 인자는 `char_hints` 로 대체하고 `service._chapter_prompt` 가 새 함수를 호출한다. 기존 `hangul_chars_per_line` 은 본문 값 계산에 그대로 쓰되 들여쓰기를 뺀다.

**테스트 (실패부터)**

- `tests/test_capacity.py`: 템플릿별 계약값만큼 한 줄 항목을 채운 슬롯이 `build_slide` 에서 경고 0건이어야 한다 (지금은 4개 템플릿 전부 실패). 계약값 + 1 개는 경고가 나야 한다. compare2 계약과 `_build_compare2` 가 같은 가용 높이 함수를 쓴다. 여백을 크게 키운 프리셋에서도 계약이 음수가 아니다.
- `tests/test_capacity.py`: 환산 안내 글자 수만큼의 한글 한 어절이 불릿 한 줄에 들어간다 (지금은 75자가 2줄로 실패). 카드 안내 글자 수도 같다.
- `tests/test_prompts.py`: 계약 문구에 항목 수 기준이 함께 적히고 카드 환산 안내가 실제 값으로 나간다. 기존 단언(`최대 11줄`, `약 75자`)은 새 값으로 바꾼다.
- 기존 `test_capacity_contract_bullet_box` 의 기대값 18 은 14 로 바뀐다. 이 테스트가 결함을 잡지 못한 이유를 주석으로 남긴다: 계약 산식만 검증했고, 계약대로 채웠을 때 실측이 통과하는지를 잇는 테스트가 없었다.

## 태스크 C: 표지와 간지도 넘침을 경고한다 (조용히 틀린 산출물)

**재현**: 표지 제목 100자(4줄)를 넣으면 `cover_title` 프레임(높이 48pt)에 4줄 x 39.2pt = 157pt 가 들어가 부제(y=260)와 날짜(y=430) 위로 겹치지만 `SlidePlan.warnings` 는 빈 목록이다. 간지 제목 4줄(44pt 프레임)도 같다. 자동 맞춤을 꺼 두었으므로(`MSO_AUTO_SIZE.NONE`) PowerPoint 에서 글자가 상자 밖으로 흘러넘친다. 다른 템플릿의 제목, 각주, 카드 소제목은 `_fixed_height_warning` 으로 잡는데 표지와 간지만 경고 함수가 없다. 프롬프트는 "이 템플릿은 짧은 텍스트만 담는다. 각 칸은 한 줄로 쓴다" 고만 안내한다.

> ⚠️ 이 항목이 회사 PC 리뷰의 세 번째 Critical 과 같은지는 확인되지 않았다. 다음 회사 PC 세션에서 `docs/reviews/2026-09-02-전체-리뷰-종합.md` 와 대조하고, 다르면 그 항목을 별도 묶음으로 올린다.

**변경**

- `_build_cover`, `_build_divider` 에 프레임별 `_fixed_height_warning` 을 적용한다 (표지 제목, 부제, 날짜, 보고자 / 간지 번호, 제목). 프레임 높이는 그대로 둔다 (표지 y 리터럴의 프리셋 승격은 단계 5B 이월 항목).
- `capacity_contract("cover")`, `("divider")` 가 빈 dict 대신 칸별 `..._max_lines: 1` 을 돌려주고 (`cover_title_max_lines`, `subtitle_max_lines`, `date_max_lines` / `section_no_max_lines`, `section_title_max_lines`), 프롬프트 계약 블록에 표지 제목과 부제의 한 줄 글자 수 안내(실측: 28pt 제목 약 30자, 14pt 부제 약 60자)를 태스크 A 의 `char_hints` 경로로 넣는다. `_CONTRACT_LABELS` 에 새 키의 한글 라벨을 추가한다 (빠뜨리면 영문 키가 그대로 프롬프트에 노출된다. 적대 리뷰 F2).
- 축약 사다리(`service._fixable`)는 `title` 만 제외하는데 표지 제목(`cover_title`)은 슬롯이라 AI 가 축약할 수 있으므로 제외하지 않는다.
- 보고자(`presenter`) 프레임의 경고는 생성 게이트(`service._measure`)에서는 관측되지 않는다: `_measure` 가 `build_slide` 를 보고자 없이 호출해 항상 빈 문자열이 들어가고 빈 텍스트는 경고 대상이 아니다. 보고자는 AI 가 생성하는 값이 아니라 사용자가 자료 탭에서 입력하는 메타이므로 이것은 결함이 아니며, 그 경고는 전체 덱 렌더(`build_render_plan`, 편집 화면과 내보내기)에서만 뜬다 (적대 리뷰 F4. 구현자가 생성 경로에 방어 코드를 덧붙이지 않도록 기록한다).

**테스트 (실패부터)**: `tests/test_layout_engine.py` 에 표지 4줄 제목과 간지 4줄 제목이 경고를 내고, 한 줄 제목은 경고가 없다는 단언. `tests/test_capacity.py` 에 cover, divider 계약이 칸별 1줄을 돌려준다는 단언. `tests/test_prompts.py` 에 표지 프롬프트가 글자 수 안내를 담는다는 단언.

## 실행 순서

태스크 B (라이터, 가장 작음) → 타입 재생성(`scripts/dump_openapi.py` → `npm run generate-types` → `tsc --noEmit`) → 태스크 A (계약과 프롬프트) → 태스크 C (표지·간지) → 문서 정정 → 독립 리뷰(커밋별 + 브랜치) → 수정 반영 → main 머지(fast-forward) → push → `codex/phase-5a` 에 main 병합.

문서 정정: 설계서 5.1 (계약의 정의를 "한 줄짜리 항목 개수 기준 하한" 으로 명시), 7.1 (라이터가 세로 정렬을 항상 명시), 로드맵 이월표에 A, B, C 등재(처리 완료)와 진행 상태 항목 추가. 회사 PC 리뷰(2026-09-02 01:14)가 이월표에 반영되지 않았던 사실과 이 묶음이 그 대체 경로임을 로드맵에 적는다.

## 이 계획이 틀렸을 가능성

- 회사 PC 리뷰의 Critical 3건과 여기서 재발견한 3건이 다를 수 있다. 특히 C 는 추정이다.
- 계약을 14줄로 줄이면 AI 가 더 짧게 쓰므로 축약 호출은 줄지만 장 수가 늘 수 있다. 밀도 3단계(단계 5B 이월)가 이 값을 조정할 자리다.
- 한 줄 항목 기준 하한은 여러 줄 불릿이 섞인 장에서 실제 가용량보다 보수적이다. 실사용에서 "더 넣을 수 있는데 계약이 막는다" 는 관찰이 나오면 계약을 "줄 수 합계 + 항목 수" 두 값으로 나누는 안을 검토한다.
