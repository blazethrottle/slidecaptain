# 단계 4: 편집 화면 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 2026-08-29 적대 리뷰 완료: 5개 관점(설계 정합, 백엔드 사실, 프런트 실행 가능성, 태스크 일관성, 사용자 흐름) 병렬 리뷰와 발견별 반박 검증(2인)을 거쳐 확정 발견 33건을 전부 본문에 반영했다. 주요 반영: openapi.json 재생성을 태스크 단위로 배치, 비동기 테스트를 저장소 관례(asyncio.run)로 정정, 자동 저장 플러시(언마운트와 내보내기 직전), 재생성 구조안 승인의 전면 교체 규칙, 복원 직후 재마운트 경합 차단.

**Goal:** React 편집 화면을 만든다: 프로젝트 목록 → 자료와 목적 입력 → 구조안 승인 → 3구역 편집기(장 목록, 미리보기, 속성 패널) → 내보내기까지, 설계서 6절의 즉시 반영 조작 전부를 포함한다. 앞 단계에서 이월된 백엔드 항목 9건(무저장 실측 API, 저장 단위, 전역 프리셋 API, 복구 진입 경로, 오류 한국어 일관화, TrustedHost, 자료 총량 상한, 수치 게이트 정밀화, 프로바이더 타임아웃)을 함께 소화한다.

**Architecture:** 레이아웃 계산의 진본은 백엔드 하나다(로드맵 결정 1): 화면은 렌더 계획(RenderPlan)을 받아 그대로 그리고, 좌표와 글자 크기와 줄바꿈을 직접 계산하지 않는다. 이를 위해 렌더 계획에 줄바꿈 결과를 내장하고(Para.lines), 저장 없이 실측만 하는 API(POST /api/render-plan)를 연다. 편집은 자동 저장(디바운스)이고, 스냅샷은 의미 시점에만 남긴다(사용자 결정 2026-08-29). 개발은 Vite 프록시, 사용은 FastAPI 정적 마운트라 CORS를 열지 않는다.

**Tech Stack:** 백엔드는 기존 그대로(Python 3.13, FastAPI, pydantic v2). 프런트엔드는 Vite 8 + React 19 + TypeScript, 테스트는 Vitest + Testing Library(jsdom). 상태 관리와 라우터 라이브러리는 쓰지 않는다(React 내장 훅으로 충분, YAGNI).

## Global Constraints

- TDD: 모든 태스크는 실패하는 테스트부터. 커밋은 태스크 단위, 한국어 커밋 메시지 (feat/fix/test/docs 접두)
- 작업 브랜치: 실행 시작 시 `feature/phase4-editor` 브랜치를 만들어 진행한다
- 백엔드 테스트: `backend` 폴더에서 `.venv/Scripts/python.exe -m pytest tests -q` (시작 시점 237개 전부 통과 유지)
- 프런트엔드 테스트: `frontend` 폴더 **안에서** `npm test` (CLAUDE.md 실측은 `npm --prefix frontend install`의 실패였고, 혼선을 막기 위해 프런트 npm 명령은 전부 폴더 안 실행으로 통일한다)
- 백엔드의 비동기 코드 테스트는 이 저장소의 기존 관례를 따른다: 동기 테스트 함수 안에서 `asyncio.run(...)`을 부른다. pytest-asyncio가 없어 맨 `async def` 테스트는 실행되지 않는다 (test_subscription_provider.py의 subscription 모듈 별칭은 `sub`)
- 좌표, 글자 크기, 줄바꿈은 데이터와 화면에 없다: 화면은 렌더 계획을 그대로 그린다 (핵심 원칙 "AI는 내용만, 배치는 코드가")
- UI 문구는 쉬운 말 한국어(비개발자 사용자): 원인과 다음 행동을 담는다. 이모지 금지, 엠대시(U+2014)와 중점(U+00B7) 금지
- API 오류는 detail 문자열 하나로 통일한다 (Task 6의 전역 핸들러 이후 목록형 detail 금지)
- 프런트엔드 의존성은 이 계획에 명시된 것만 추가한다 (드래그, 상태 관리, 라우터 라이브러리 추가 금지)
- API 라우트나 응답 스키마를 바꾸는 태스크(Task 1~6 전부)는 전체 통과 확인 전에 `backend` 폴더에서 `.venv/Scripts/python.exe scripts/dump_openapi.py`로 `openapi.json`을 재생성하고 그 파일을 커밋에 포함한다 (`test_openapi.py::test_committed_openapi_json_matches_live_app`이 어긋남을 잡는다). 라우트를 추가한 태스크는 `test_openapi.py::test_openapi_contains_all_routes`의 목록에도 신규 경로를 추가한다 (`/api/render-plan`, `/api/preset` 등)

## 이 계획이 소비하는 단계 1~3 인터페이스 (실측 확인, 2026-08-29)

| 이름 | 시그니처 | 위치 |
|---|---|---|
| `RenderPlan` | `page_width_pt(960), page_height_pt(540), style: RenderStyle, slides: list[SlidePlan]` | `slidecaptain/models/render.py:78` |
| `SlidePlan` | `chapter_id, template, frames: list[Frame], warnings: list[CapacityWarning]` | `slidecaptain/models/render.py:51` |
| `Frame` | `name("장ID:슬롯"), x, y, w, h, fill, border, paras: list[Para], table: TablePlan|None, valign` | `slidecaptain/models/render.py:30` |
| `Para` | `text, level, font_pt, bold, color, align, bullet` | `slidecaptain/models/render.py:11` |
| `TablePlan` | `col_widths_pt, header, rows, font_pt, header_fill, row_heights_pt` | `slidecaptain/models/render.py:21` |
| `RenderStyle` | `korean_font, latin_font, text_color, box_padding_pt, line_spacing, bullet_indent_pt, bullet_gap_pt, table_cell_pad_*, border_width_pt, bullet_char, bullet_font` | `slidecaptain/models/render.py:58` |
| `build_render_plan(deck, preset, metrics)` | 구조안 순서 렌더, 슬라이드 없는 장 건너뜀 | `slidecaptain/layout/engine.py:26` |
| `build_slide(chapter, slots, page_no, preset, metrics)` | 템플릿 6종 분기 | `slidecaptain/layout/templates.py:371` |
| `break_paragraph(text, max_width_pt, font_pt, face, safety_ratio)` | 어절 탐욕 줄바꿈 → `list[str]` | `slidecaptain/metrics/line_breaker.py:22` |
| `measure_bullets(bullets, area_width_pt, font_pt, face, spacing)` | 들여쓰기는 `bullet_indent * (level+1)` | `slidecaptain/metrics/capacity.py:33` |
| `_content_geometry(preset)` | content_top/bottom/width, footnote_top | `slidecaptain/metrics/capacity.py:56` |
| `Deck / Slots / Chapter` | Slots는 template 판별자 union 6종. 검증: 장 id 중복 금지, 장당 슬라이드 1개, 템플릿 일치, 표 셀 개행 금지 | `slidecaptain/models/deck.py` |
| `Preset / apply_overrides(base, overrides)` | 깊은 병합, 하한 재검증(body 12pt, footnote 9pt) | `slidecaptain/models/preset.py:103,126` |
| `FileProjectStore` | `save_deck`는 저장마다 `_snapshot_current` 호출. `_project_dir`는 deck.json 없으면 ProjectNotFound. `list_projects`는 deck.json 없는 폴더를 건너뜀 | `slidecaptain/storage/file_store.py:188,123,160` |
| `create_app(store, provider=None)` | 라우트 14개(프로젝트 2, 덱 2, 렌더 1, 내보내기 1, 스냅샷 2, 자료 3, 생성 3). `_validated_preset(deck)` 호출부는 put_deck, render-plan GET, export, generate_chapter, condense의 5곳이고 밑판이 `Preset()` 고정 | `slidecaptain/server/app.py:86,73` |
| API 테스트 관례 | test_api_projects, test_api_render_export = `client(tmp_path)` 픽스처. test_api_generate = `store` 픽스처 + `_client(store, responses)` 헬퍼(StubProvider가 ProviderResponse 목록 소비). client 픽스처 없음, conftest 없음 | `backend/tests/test_api_generate.py:30,35` |
| `GenerationService` | `generate_structure(meta, sources, target_chapters, instructions) -> StructureResult`, `generate_chapter(deck, chapter_id, sources, preset, instructions) -> ChapterResult`, `condense_chapter(deck, chapter_id, current_slots, sources, preset, instructions) -> ChapterResult` | `slidecaptain/pipeline/service.py:94,130,167` |
| `StructureResult` | `status("ok"|"format_error"), structure, raw_text, unverified_numbers, format_retried` | `slidecaptain/pipeline/service.py:49` |
| `ChapterResult` | `status, slots, raw_text, warnings, unverified_numbers, format_retried, condensed` | `slidecaptain/pipeline/service.py:57` |
| `SubscriptionProvider` | `complete(prompt, schema)`, 오류를 ProviderNotAvailable/ProviderCallFailed 한국어 안내로 매핑 | `slidecaptain/pipeline/subscription.py:35` |
| `export_deck_data(deck, out_dir, global_preset=None)` | 이미 전역 프리셋 인자를 받는다 | `slidecaptain/export/exporter.py:45` |
| `find_unverified_numbers(texts, sources)` | lookbehind `(?<![\d.])` (Task 7에서 정밀화) | `slidecaptain/pipeline/numbers.py:34` |
| `normalize_text(text)` | 개행→공백, 탭→공백, 금지 문자 치환, 연속 공백 축소 | `slidecaptain/pipeline/normalize.py:14` |
| CLI `serve` | `--data-dir`, `--port`, `--model`. `_build_serve_app(data_dir, model)` | `slidecaptain/__main__.py:24,48` |
| 타입 생성 | `backend/scripts/dump_openapi.py` → `frontend` 폴더에서 `npm run generate-types` | CLAUDE.md 명령 |

## 파일 구조 (이 계획이 만들고 고치는 것)

```
backend/
  slidecaptain/
    models/render.py         # 수정: Para.lines, TablePlan.header_lines/cell_lines (Task 1)
    layout/templates.py      # 수정: 줄바꿈 결과 계산과 내장 (Task 1)
    storage/file_store.py    # 수정: 전역 프리셋(Task 3), snapshot 인자와 snapshot_now(Task 4), 복구 목록(Task 5)
    server/app.py            # 수정: POST /api/render-plan(Task 2), 프리셋 API(Task 3), 스냅샷(Task 4),
                             #       복구(Task 5), 오류 핸들러/TrustedHost/자료 상한(Task 6), 정적 마운트(Task 9)
    pipeline/normalize.py    # 수정: 유니코드 공백 축약 (Task 7)
    pipeline/numbers.py      # 수정: lookbehind 정밀화 (Task 7)
    pipeline/service.py      # 수정: 대조 말뭉치에 덱 제목 추가 (Task 7)
    pipeline/subscription.py # 수정: 타임아웃 (Task 7)
    __main__.py              # 수정: 정적 마운트 배선 (Task 9)
  openapi.json               # 스키마나 라우트를 바꾸는 태스크(1~6)마다 재생성 (전역 제약)
  tests/
    test_layout_engine.py    # 수정 (Task 1)
    test_openapi.py          # 수정: 라우트 목록 단언 (Task 2, 3)
    test_api_render_export.py# 수정 (Task 2)
    test_file_store.py       # 수정 (Task 3, 4, 5)
    test_api_projects.py     # 수정 (Task 3, 4, 5, 6)
    test_api_generate.py     # 수정 (Task 6)
    test_cli.py              # 수정: 바인딩 단언 (Task 6)
    test_normalize.py        # 수정 (Task 7)
    test_numbers.py          # 수정 (Task 7)
    test_generation_service.py # 수정 (Task 7)
    test_subscription_provider.py # 수정 (Task 7)
    test_api_static.py       # 신규 (Task 9)
frontend/
  package.json               # 수정: 의존성과 스크립트 (Task 8)
  vite.config.ts             # 신규 (Task 8)
  tsconfig.json              # 신규 (Task 8)
  index.html                 # 신규 (Task 8)
  src/
    main.tsx, App.tsx        # 신규 (Task 8)
    styles.css               # 신규 (Task 8, 이후 태스크에서 클래스 추가)
    test/setup.ts            # 신규 (Task 8)
    api/types.ts             # 재생성 (Task 7)
    api/client.ts            # 신규: 타입 붙은 fetch 래퍼 (Task 8)
    screens/ProjectList.tsx  # 신규 (Task 8)
    screens/ProjectView.tsx  # 신규: 탭 골격 (Task 9)
    screens/SourcesScreen.tsx# 신규: 자료와 목적 입력 (Task 9)
    screens/StructureScreen.tsx # 신규: 구조안 생성과 승인 (Task 10)
    screens/EditorScreen.tsx # 신규 Task 12, 배선 수정 Task 13~15
    screens/RecoveryScreen.tsx # 신규: 스냅샷 복구 (Task 16)
    editor/labels.ts         # 신규: 템플릿 이름표 (Task 10)
    editor/Preview.tsx       # 신규: 렌더 계획 그리기 (Task 11)
    editor/ChapterList.tsx   # 신규 Task 12, 드래그 수정 Task 13
    editor/PropertyPanel.tsx # 신규 Task 13, 템플릿 교체 수정 Task 14
    editor/GeneratePanel.tsx # 신규: AI 재생성과 축약 (Task 15)
    editor/DesignPanel.tsx   # 신규: 디자인 값 조정 (Task 14)
    editor/slotOps.ts        # 신규 Task 12(applyTextEdit), 확장 Task 13(구조 조작)과 14(setPresetOverride)
    editor/templateSwitch.ts # 신규: 템플릿 교체 매핑 (Task 14)
    state/deckStore.ts       # 신규: 언두 리듀서 (Task 12)
    state/useDeckEditor.ts   # 신규: 실측과 자동 저장 훅 (Task 12)
```

## 이 계획이 소화하는 이월 항목

| 이월 항목 (로드맵) | 처리 태스크 |
|---|---|
| 편집 화면용 무저장 분량 실측 API와 편집 저장 단위 결정 | Task 2 (API), Task 4 (저장 단위, 사용자 결정 반영) |
| 전역 프리셋의 저장 위치와 읽기, 쓰기 API 부재 | Task 3 |
| deck.json만 소실되고 스냅샷은 남은 프로젝트의 복구 진입 경로 | Task 5, 화면은 Task 16 |
| API 오류 메시지 한국어 일관화 + target_chapters ge=1 | Task 6 |
| TrustedHostMiddleware와 바인딩 자동 테스트 | Task 6 |
| 자료 총량 상한과 초과 시 422 안내 부재 | Task 6 |
| 수치 대조 게이트의 오탐/미탐 한계 목록 재평가 | Task 7 (개선 2건 반영, 잔여 한계는 결정 12에 기록) |
| normalize의 유니코드 공백 미축약 | Task 7 |
| 프로바이더 호출 타임아웃 부재 | Task 7 |

## 이 계획에서 확정하는 설계 결정

1. **저장 단위: 자동 저장 + 의미 시점 스냅샷** (사용자 결정 2026-08-29). 편집 조작은 로컬 상태에 즉시 반영하고, 1.2초 디바운스로 `PUT /deck?snapshot=false` 자동 저장한다. 스냅샷은 네 시점에만 남긴다: ① 편집 세션의 첫 저장(`snapshot=true`) ② 구조안 승인 반영 저장(`snapshot=true`. 이때 저장소가 직전 파일을 스냅샷으로 보존하므로 승인 전 상태가 복구 지점이 된다) ③ AI 재생성/축약 결과 반영 저장(`snapshot=true`) ④ 내보내기 직전(`POST /snapshots` 명시 호출). 스냅샷 복원 직전 보존은 기존 저장소 동작 그대로다. `save_deck`의 기본값은 `snapshot=True`를 유지해 화면 밖 호출자(파일 직접 수정 대비)의 안전을 지킨다. **디바운스에는 플러시가 따른다** (2026-08-29 적대 리뷰 반영): 편집 화면이 내려가는 순간(탭 전환, 목록 복귀)과 내보내기 직전에는 보류 중인 자동 저장을 즉시 실행해, 마지막 1.2초 안의 편집이 소실되거나 내보내기에서 빠지지 않게 한다 (`useDeckEditor`의 언마운트 플러시와 `flushSave`, Task 12와 16).
2. **무저장 실측 API는 `POST /api/render-plan`** (본문 = Deck 전체, 응답 = RenderPlan). 프로젝트와 무관한 순수 계산이라 경로에 프로젝트를 넣지 않는다. 편집 중 미리보기와 분량 경고는 전부 이 API의 응답으로 갱신한다(0.3초 디바운스). 저장(1.2초)과 실측(0.3초)을 분리해 타이핑 중에도 경고가 빠르게 따라온다.
3. **렌더 계획에 줄바꿈 결과를 내장한다** (로드맵 결정 1의 미이행분 이행): `Para.lines: list[str]`(엔진의 어절 줄바꿈 결과), 표는 `TablePlan.header_lines: list[list[str]]`와 `cell_lines: list[list[list[str]]]`(행 x 열 x 줄). 미리보기는 이 줄들을 줄 단위 div로 그려, 화면의 줄바꿈이 항상 분량 실측과 일치한다(브라우저 자체 줄바꿈에 맡기면 경고와 화면이 어긋날 수 있다). PPTX 라이터는 이 필드를 소비하지 않는다(강제 개행을 심지 않는 기존 원칙 유지).
4. **전역 프리셋은 `<data-dir>/preset.json`**: `GET /api/preset`, `PUT /api/preset`(본문 = Preset 전체, 하한 검증 포함). 파일이 없으면 코드 기본값 `Preset()`. 서버의 모든 프리셋 계산(_validated_preset, export)은 전역 프리셋 위에 덱 덮어쓰기를 얹는 순서로 바뀐다. CLI `export`는 data-dir 맥락이 없으므로 기본 프리셋 기준을 유지한다(문서화된 한계). 프리셋 환류 UI("프리셋에 저장" 질문)는 단계 5이고, 이 API는 그 전제다. `preset.json`과 같은 이름의 프로젝트 생성 시도는 기존 `d.exists()` 검사가 409로 거부한다(허용된 부작용).
5. **프런트엔드 스택 최소주의**: Vite 8 + React 19 + TS, Vitest + Testing Library. 상태 관리, 라우터, 드래그 라이브러리는 넣지 않는다. 언두는 useReducer의 past/present/future 스택(상한 100), 화면 전환은 App의 상태 분기, 드래그는 HTML5 네이티브 DnD. 근거: 로컬 1인 앱이라 URL 딥링크와 전역 상태 공유 요구가 없고, 의존성마다 회귀 표면이 는다.
6. **미리보기는 HTML 절대 배치 + transform scale**: 960x540 고정 좌표계(숫자를 px로 그대로 사용)를 컨테이너 폭에 맞춰 `transform: scale()`한다. pt 수치를 px로 그대로 쓰므로 비율이 정확하고, 글자 크기와 행간(font_pt x line_spacing)도 렌더 계획 수치를 그대로 쓴다. 채움이나 테두리가 있는 프레임은 `style.box_padding_pt`만큼 안쪽 여백을 준다(엔진의 실측 폭과 동일 규칙). 폰트는 Noto Sans KR(serve가 설치)이고, 줄바꿈이 서버 계산이라 폰트가 없어도 줄 구조는 유지된다.
7. **개발은 Vite 프록시, 사용은 정적 마운트, CORS는 열지 않는다**: 개발 서버가 `/api`를 `127.0.0.1:8765`로 프록시하고, 사용 시에는 FastAPI가 `frontend/dist`를 마운트해 한 주소에서 서빙한다. 어느 쪽이든 same-origin이라 CORS 미들웨어가 필요 없고, TrustedHostMiddleware(127.0.0.1, localhost)로 DNS 리바인딩을 막는다.
8. **인라인 수정은 확정 시점 반영**: 미리보기 클릭으로 프레임을 선택하고, 선택된 프레임의 문단(또는 표 칸)을 다시 클릭하면 입력 상자가 열린다. 반영은 blur 또는 Enter의 확정 시점 1회다(타이핑마다 반영하지 않는다). 근거: 언두 단위가 사람의 편집 단위와 일치하고, 실측 API 호출량이 줄어든다. 제목(title 슬롯)의 수정은 슬롯이 아니라 구조안의 `chapter.topic`을 고친다(주제형 제목의 소유가 구조안이므로).
9. **역할 분담: 텍스트는 미리보기, 구조는 패널**: 텍스트 내용 수정은 미리보기 인라인만 제공한다(설계서 6.1 "미리보기에서 클릭해 타이핑"). 속성 패널은 구조 조작을 담당한다: 불릿 추가/삭제, 표 행 삭제와 열 병합, 템플릿 교체, AI 재생성/축약, 디자인 값(프리셋 덮어쓰기) 조정, 장 주제(topic) 수정. 같은 내용의 편집 경로를 이중으로 만들지 않는다(코드와 검증 표면 최소화).
10. **템플릿 교체는 호환 슬롯 자동 이사 + 소실 확인**: 매핑 규칙은 순수 함수 `switchTemplate(slots, to)`가 구현하고, 갈 곳이 없는 내용은 사람이 읽을 수 있는 이름 목록(dropped)으로 반환한다. dropped가 비어 있지 않으면 확인 대화("다음 내용은 새 템플릿에 자리가 없어 사라집니다") 후 진행한다. 보류 영역(버리지 않고 보관)은 로드맵대로 단계 5이고, 단계 4는 소실을 확인 대화로 막는 데까지다. 매핑: conclusion은 summary/bullet_box/compare2 사이 상호 이동, bullets(bullet_box) ↔ points(summary) 상호 이동, footnote는 bullet_box ↔ table 상호 이동, bullet_box → compare2는 왼쪽 카드 불릿으로(카드 소제목은 빈 값), compare2 → bullet_box/summary는 두 카드 불릿을 순서대로 합침(소제목은 dropped), 표의 columns/rows와 cover/divider 필드는 상대가 없어 dropped.
11. **AI 생성 결과는 반영 전 확인 패널을 거친다**: 재생성/축약 응답(ChapterResult)을 바로 덱에 넣지 않고, 경고(분량, 수치)와 condensed/format_retried 표시와 함께 [반영] [버리기]를 제공한다. format_error면 원문(raw_text)을 접힌 영역으로 보여주고 재시도 버튼을 제공한다(설계서 7.2의 수동 처리 경로). 반영은 결정 1의 ③(스냅샷 저장)이다.
12. **수치 대조는 생성 시점 한정, 소음 2건 정밀화**: `unverified_numbers`는 생성 응답에만 실려 오고 deck.json에 저장되지 않으므로, 화면 표시는 생성 결과 패널과 구조안 화면의 생성 직후 표시에 한정한다(사용자가 직접 타이핑한 수치는 검증하지 않는다: 원저자가 사용자 본인이다). 정밀화 2건을 반영한다: ① lookbehind를 `(?<!\d)(?<!\d\.)`로 바꿔 "이다.500억"처럼 문장 마침표 뒤 숫자의 오탐 제거 ② 대조 말뭉치에 덱 제목을 추가해 표지의 연도 상시 경고 제거. 잔여 한계(공백 없는 날짜 "2026.8.28"의 뒷부분 오탐, "2,3위" 콤마 융합 미탐)는 실사용 소음이 보고되면 재평가한다(로드맵 이월표 갱신).
13. **프로바이더 타임아웃 300초**: `SubscriptionProvider.complete`를 `asyncio.wait_for`로 감싼다. 초과 시 ProviderCallFailed 한국어 안내. 화면은 생성 호출 중 진행 상태(어느 장을 생성 중인지)를 표시하고 버튼을 잠근다.
14. **자료 총량 상한 100,000자**: 생성 라우트의 `_load_sources`에서 합계 초과 시 422 "자료가 너무 큽니다. 필요한 부분만 발췌해 주세요". 근거: 자료 전문이 프롬프트에 동봉되는 구조에서 컨텍스트 한계로 인한 불투명한 실패를 명확한 안내로 바꾼다. 한도는 구조안 프롬프트가 자료 전체를 담고도 여유가 남는 크기로 잡았다.
15. **구조안 재승인 시 사라진 장의 슬라이드는 확인 후 제거**: 승인 반영은 새 구조안에 없는 장(또는 템플릿이 바뀐 장)의 슬라이드를 함께 제거해야 덱 검증(장 존재, 템플릿 일치)을 통과한다. 제거될 내용이 있으면 확인 대화 후 진행한다. **AI가 다시 생성한 구조안의 승인은 전면 교체다** (2026-08-29 적대 리뷰 반영): `generate_structure`가 장 id를 항상 c1부터 재부여하므로, 재생성 초안의 id는 옛 슬라이드의 chapter_id와 우연히 겹칠 수 있고 그대로 계승하면 새 장 제목 밑에 무관한 옛 내용이 남는다. 따라서 재생성 초안(draftGenerated 플래그)을 승인하면 기존 슬라이드를 전부 제거하고(확인 대화에 개수 명시) 전 장을 새로 생성한다. id 기준 슬라이드 계승은 기존 구조안을 손으로 고쳐 승인하는 경우에만 적용한다. 장별 생성은 순차 호출이다(구독 CLI 프로세스를 병렬로 띄우지 않는다). 각 장의 생성 결과는 완료 즉시 저장해(첫 반영만 결정 1의 스냅샷) 중간 이탈에도 생성분을 잃지 않는다.
16. **편집 탭 게이트로 워크플로를 강제한다**: 프로젝트 화면은 [자료] [구조안] [편집] 탭이고, 편집 탭은 슬라이드가 1개 이상일 때만 활성화된다(설계서 목적 5: 구조 합의 후 채우기). 복구가 필요한 프로젝트(status가 needs_recovery)는 목록에서 복구 화면으로만 진입한다.

---

### Task 1: 렌더 계획에 줄바꿈 결과 내장 (Para.lines, TablePlan 줄 데이터)

**Files:**
- Modify: `backend/slidecaptain/models/render.py`
- Modify: `backend/slidecaptain/layout/templates.py`
- Test: `backend/tests/test_layout_engine.py`

**Interfaces:**
- Consumes: `break_paragraph(text, max_width_pt, font_pt, face, safety_ratio)` (`metrics/line_breaker.py:22`), `metrics.face(bold)`
- Produces: `Para.lines: list[str]` (기본 `[]`), `TablePlan.header_lines: list[list[str]]`, `TablePlan.cell_lines: list[list[list[str]]]` (행 x 열 x 줄, 기본 `[]`). Task 11의 미리보기가 이 필드만 보고 줄을 그린다. PPTX 라이터는 이 필드를 읽지 않는다(변경 없음).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_layout_engine.py`에 추가 (기존 import와 `METRICS` 재사용):

```python
def _deck_with(template: str, slots: dict) -> Deck:
    return Deck(
        meta=DeckMeta(title="줄바꿈 테스트"),
        structure=Structure(chapters=[Chapter(id="c1", topic="주제", template=template)]),
        slides=[Slide(chapter_id="c1", slots={"template": template, **slots})],
    )


def _frame(plan, suffix: str):
    return next(f for f in plan.slides[0].frames if f.name.endswith(suffix))


def test_para_lines_match_engine_breaks():
    long_text = ("가나다라마 " * 30).strip()
    plan = build_render_plan(
        _deck_with("bullet_box", {"bullets": [{"text": long_text}], "conclusion": "결론"}),
        Preset(), METRICS,
    )
    para = _frame(plan, ":bullets").paras[0]
    assert len(para.lines) >= 2  # 긴 문장은 여러 줄로 갈라진다
    assert " ".join(para.lines) == para.text  # 줄 결합이 원문을 보존한다

def test_short_para_has_single_line():
    plan = build_render_plan(
        _deck_with("bullet_box", {"bullets": [{"text": "짧다"}], "conclusion": "결론"}),
        Preset(), METRICS,
    )
    assert _frame(plan, ":bullets").paras[0].lines == ["짧다"]
    assert _frame(plan, ":title").paras[0].lines == ["주제"]
    assert _frame(plan, ":conclusion").paras[0].lines == ["결론"]

def test_cover_and_divider_paras_have_lines():
    cover = build_render_plan(
        _deck_with("cover", {"title": "표지 제목", "subtitle": "부제"}), Preset(), METRICS
    )
    assert _frame(cover, ":cover_title").paras[0].lines == ["표지 제목"]
    divider = build_render_plan(
        _deck_with("divider", {"section_no": "1", "section_title": "간지 제목"}), Preset(), METRICS
    )
    assert _frame(divider, ":section_title").paras[0].lines == ["간지 제목"]

def test_table_plan_carries_cell_lines():
    long_cell = ("항목 설명 " * 30).strip()
    plan = build_render_plan(
        _deck_with("table", {"columns": ["구분", "내용"], "rows": [["A", long_cell]]}),
        Preset(), METRICS,
    )
    tp = _frame(plan, ":table").table
    assert len(tp.header_lines) == 2 and tp.header_lines[0] == ["구분"]
    assert len(tp.cell_lines) == 1 and len(tp.cell_lines[0]) == 2
    assert len(tp.cell_lines[0][1]) >= 2  # 긴 칸은 여러 줄
    # 행 높이는 줄수에서 계산된 기존 값과 정합해야 한다
    from slidecaptain.metrics.capacity import line_height_pt
    lh = line_height_pt(tp.font_pt, Preset().spacing.line_spacing)
    expected = max(len(c) for c in tp.cell_lines[0]) * lh + 2 * Preset().spacing.table_cell_pad_y
    assert abs(tp.row_heights_pt[1] - expected) < 0.01
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_layout_engine.py -q`
Expected: 신규 4개 FAIL (`lines`가 비어 있고 `header_lines`가 없음)

- [ ] **Step 3: 모델 필드 추가**

`backend/slidecaptain/models/render.py`:

`Para`에 필드 추가 (bullet 아래):

```python
    lines: list[str] = []  # 엔진의 어절 줄바꿈 결과. 미리보기 전용, 라이터는 읽지 않는다
```

`TablePlan`에 필드 추가 (row_heights_pt 아래):

```python
    header_lines: list[list[str]] = []  # 머리글 칸별 줄바꿈 결과 (미리보기 전용)
    cell_lines: list[list[list[str]]] = []  # 행 x 열 x 줄 (미리보기 전용)
```

- [ ] **Step 4: 템플릿 배치부에서 줄바꿈 결과 계산**

`backend/slidecaptain/layout/templates.py` 수정. 모듈 상단 import에 추가하고 `_build_table` 안의 지역 import는 제거:

```python
from slidecaptain.metrics.line_breaker import break_paragraph
```

공통 헬퍼 추가 (`_bullet_paras` 위):

```python
def _para_lines(
    text: str, width_pt: float, font_pt: float, bold: bool, preset: Preset, metrics
) -> list[str]:
    """미리보기가 그대로 그릴 줄바꿈 결과. 분량 실측(measure_lines)과 같은 규칙이다."""
    return break_paragraph(text, width_pt, font_pt, metrics.face(bold), preset.spacing.safety_ratio)
```

`_bullet_paras`는 영역 폭과 metrics를 받아 불릿별 들여쓰기를 뺀 폭으로 줄을 계산한다 (measure_bullets와 같은 수식):

```python
def _bullet_paras(bullets: list[Bullet], area_width_pt: float, preset: Preset, metrics) -> list[Para]:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    return [
        Para(
            text=b.text, level=b.level, font_pt=r.body_pt, color=c.text, bullet=True,
            lines=_para_lines(
                b.text, area_width_pt - s.bullet_indent * (b.level + 1), r.body_pt, False, preset, metrics
            ),
        )
        for b in bullets
    ]
```

프레임 헬퍼들은 metrics를 받아 각자의 실측 폭으로 lines를 채운다. 시그니처와 Para 생성부만 바뀐다:

- `_title_frame(chapter, preset, metrics)`: `lines=_para_lines(chapter.topic, g["content_width"], r.title_pt, True, preset, metrics)`
- `_footnote_frame(chapter, text, preset, metrics)`: `lines=_para_lines(text, g["content_width"], r.footnote_pt, False, preset, metrics)`
- `_page_number_frame`: 시그니처 불변, `lines=[str(page_no)]` 직접 지정 (실측 불필요)
- `_conclusion_box_frame(chapter, text, y, preset, metrics)`: 안쪽 폭은 `_conclusion_warning`과 동일하게 `g["content_width"] - 2 * s.box_padding`, 폰트 `r.box_pt`, bold=True
- `_build_cover(chapter, slots, preset, metrics)`: title/subtitle은 폭 `w`, date/audience는 폭 `w / 2`
- `_build_divider(chapter, slots, page_no, preset, metrics)`: section_no/section_title 모두 폭 `w`
- `_build_compare2`의 카드 소제목 Para: `lines=_para_lines(card.heading, card_w - 2 * s.box_padding, r.body_pt, True, preset, metrics)`, 카드 불릿은 `_bullet_paras(card.bullets, card_w - 2 * s.box_padding, preset, metrics)`
- `_build_bullet_box`와 `_build_summary`의 불릿: `_bullet_paras(slots.bullets, g["content_width"], preset, metrics)` (points 동일)
- `build_slide`: `_build_cover(chapter, slots, preset, metrics)`, `_build_divider(chapter, slots, page_no, preset, metrics)`로 metrics 전달

`_build_table`의 행 높이 계산을 줄 데이터 기반으로 재구성 (기존 `row_height` 함수 대체):

```python
    def row_lines(cells: list[str], bold: bool) -> list[list[str]]:
        face = metrics.face(bold)
        return [
            break_paragraph(cell, col_widths[i] - 2 * s.table_cell_pad_x, r.table_pt, face, s.safety_ratio)
            for i, cell in enumerate(cells)
        ]

    header_lines = row_lines(slots.columns, True)
    cell_lines = [row_lines(row, False) for row in slots.rows]

    def row_height(lines_by_cell: list[list[str]]) -> float:
        return max(len(lines) for lines in lines_by_cell) * lh + 2 * s.table_cell_pad_y

    row_heights = [row_height(header_lines)] + [row_height(c) for c in cell_lines]
```

`TablePlan(...)` 생성에 `header_lines=header_lines, cell_lines=cell_lines` 추가.

- [ ] **Step 5: openapi.json 재생성과 전체 통과 확인**

Run: `.venv/Scripts/python.exe scripts/dump_openapi.py` (Para와 TablePlan 스키마가 바뀌었으므로. 전역 제약)
Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS (기존 237개 + 신규 4개. 골든과 회귀 테스트는 라이터가 lines를 읽지 않으므로 영향 없음)

- [ ] **Step 6: 커밋**

```bash
git add backend/slidecaptain/models/render.py backend/slidecaptain/layout/templates.py backend/tests/test_layout_engine.py backend/openapi.json
git commit -m "feat: 렌더 계획에 줄바꿈 결과 내장 (미리보기와 실측의 일치, 로드맵 결정 1 이행)"
```

---

### Task 2: 무저장 분량 실측 API (POST /api/render-plan)

**Files:**
- Modify: `backend/slidecaptain/server/app.py`
- Test: `backend/tests/test_api_render_export.py`

**Interfaces:**
- Consumes: `build_render_plan`, `_validated_preset` (기존)
- Produces: `POST /api/render-plan` (본문 = Deck JSON) → 200 RenderPlan. 저장하지 않는다. 프리셋 덮어쓰기가 유효하지 않으면 422. Task 12의 편집 실측이 이 라우트만 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_render_export.py`에 추가 (기존 client 픽스처 재사용):

```python
def test_measure_returns_plan_without_saving(client):
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"]["chapters"] = [{"id": "c1", "topic": "주제", "template": "bullet_box"}]
    deck["slides"] = [{"chapter_id": "c1", "slots": {
        "template": "bullet_box", "bullets": [{"text": "가"}], "conclusion": "결론"}}]
    r = client.post("/api/render-plan", json=deck)
    assert r.status_code == 200
    assert [s["chapter_id"] for s in r.json()["slides"]] == ["c1"]
    # 프로젝트에는 반영되지 않았다 (무저장)
    assert client.get("/api/projects/p1/deck").json()["slides"] == []

def test_measure_reports_capacity_warnings(client):
    # 실측 근거(2026-08-29, 기본 프리셋): 이 문장의 반복 150부터 bullets 영역(318pt)을 넘긴다
    # (needed 319.2pt). 경계가 1.2pt로 얇아 여유를 두고 200을 쓴다. 프리셋 기본값이 바뀌면 재실측할 것
    long_text = "분량 초과 확인 문장 " * 200
    deck = {"meta": {"title": "t"},
            "structure": {"chapters": [{"id": "c1", "topic": "주제", "template": "bullet_box"}]},
            "slides": [{"chapter_id": "c1", "slots": {
                "template": "bullet_box", "bullets": [{"text": long_text}], "conclusion": "결론"}}]}
    r = client.post("/api/render-plan", json=deck)
    assert r.status_code == 200
    assert any(w["slot"] == "bullets" for w in r.json()["slides"][0]["warnings"])

def test_measure_invalid_overrides_422(client):
    deck = {"meta": {"title": "t", "preset_overrides": {"font_roles": {"body_pt": 5}}}}
    r = client.post("/api/render-plan", json=deck)
    assert r.status_code == 422
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_render_export.py -q`
Expected: 신규 3개 FAIL (404: 라우트 없음)

- [ ] **Step 3: 라우트 추가**

`backend/slidecaptain/server/app.py`의 `get_render_plan` 아래에 추가:

```python
    @app.post("/api/render-plan", response_model=RenderPlan)
    def measure_deck(deck: Deck):
        """저장 없이 실측만 한다: 편집 중 미리보기와 분량 경고의 공급원 (단계 4 결정 2)."""
        preset = _validated_preset(deck)
        return build_render_plan(deck, preset, metrics)
```

- [ ] **Step 4: openapi.json 재생성과 전체 통과 확인**

`backend/tests/test_openapi.py::test_openapi_contains_all_routes`의 목록에 `"/api/render-plan"`을 추가한다.

Run: `.venv/Scripts/python.exe scripts/dump_openapi.py`
Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/server/app.py backend/tests/test_api_render_export.py backend/tests/test_openapi.py backend/openapi.json
git commit -m "feat: 무저장 분량 실측 API (편집 미리보기 공급원, 단계 2 이월)"
```

---

### Task 3: 전역 프리셋 파일과 API (GET/PUT /api/preset)

**Files:**
- Modify: `backend/slidecaptain/storage/file_store.py`
- Modify: `backend/slidecaptain/server/app.py`
- Test: `backend/tests/test_file_store.py`, `backend/tests/test_api_projects.py`

**Interfaces:**
- Consumes: `Preset`, `apply_overrides` (기존), `export_deck_data(deck, out_dir, global_preset=None)` (이미 인자 보유)
- Produces: `ProjectStore.load_global_preset() -> Preset`, `save_global_preset(preset) -> None` (파일 `<data-dir>/preset.json`, 없으면 기본값). `GET /api/preset` → Preset, `PUT /api/preset` → OkResponse. 서버의 모든 프리셋 계산이 전역 프리셋을 밑판으로 쓴다. 단계 5의 프리셋 환류 UI가 이 API를 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_file_store.py`에 추가. import 두 가지: `from slidecaptain.models.preset import Preset` 한 줄을 새로 넣고, 파일 상단의 기존 `slidecaptain.storage.file_store` import 블록에 `StorageError`를 추가한다 (현재 목록에 없어서 빠뜨리면 NameError가 난다):

```python
def test_global_preset_default_when_missing(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    assert store.load_global_preset() == Preset()

def test_global_preset_roundtrip(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    preset = Preset()
    preset.font_roles.title_pt = 22.0
    store.save_global_preset(preset)
    assert store.load_global_preset().font_roles.title_pt == 22.0

def test_global_preset_corrupt_file_message(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    (tmp_path / "projects" / "preset.json").write_text("{망가짐", encoding="utf-8")
    with pytest.raises(StorageError) as exc_info:
        store.load_global_preset()
    assert "preset.json" in str(exc_info.value)
```

`backend/tests/test_api_projects.py`에 추가:

```python
def test_preset_get_put_and_render_uses_it(client):
    r = client.get("/api/preset")
    assert r.status_code == 200
    preset = r.json()
    preset["font_roles"]["title_pt"] = 30.0
    assert client.put("/api/preset", json=preset).status_code == 200
    assert client.get("/api/preset").json()["font_roles"]["title_pt"] == 30.0
    # 렌더 계획이 전역 프리셋을 밑판으로 쓴다
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"]["chapters"] = [{"id": "c1", "topic": "주제", "template": "bullet_box"}]
    deck["slides"] = [{"chapter_id": "c1", "slots": {
        "template": "bullet_box", "bullets": [], "conclusion": "결론"}}]
    plan = client.post("/api/render-plan", json=deck).json()
    title_para = next(
        p for f in plan["slides"][0]["frames"] if f["name"].endswith(":title") for p in f["paras"]
    )
    assert title_para["font_pt"] == 30.0

def test_preset_put_below_floor_422(client):
    preset = client.get("/api/preset").json()
    preset["font_roles"]["body_pt"] = 5.0
    assert client.put("/api/preset", json=preset).status_code == 422
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_store.py tests/test_api_projects.py -q`
Expected: 신규 5개 FAIL (메서드와 라우트 없음)

- [ ] **Step 3: 저장소 구현**

`backend/slidecaptain/storage/file_store.py`:

- import에 추가: `from slidecaptain.models.preset import Preset`
- `ProjectStore` Protocol에 추가:

```python
    def load_global_preset(self) -> Preset: ...
    def save_global_preset(self, preset: Preset) -> None: ...
```

- `FileProjectStore`에 구현 추가 (`exports_dir` 아래):

```python
    # -- 전역 프리셋 --------------------------------------------------------

    def load_global_preset(self) -> Preset:
        path = self.root / "preset.json"
        if not path.exists():
            return Preset()
        try:
            return Preset.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as e:
            raise StorageError(
                "전역 프리셋 파일(preset.json)을 읽지 못했습니다. "
                f"파일을 지우면 기본값으로 돌아갑니다. 원인: {e}"
            ) from e

    def save_global_preset(self, preset: Preset) -> None:
        tmp = self.root / "preset.json.tmp"
        tmp.write_text(preset.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.root / "preset.json")
```

- [ ] **Step 4: 서버 배선**

`backend/slidecaptain/server/app.py`:

- `_validated_preset`이 밑판을 인자로 받게 바꾼다:

```python
def _validated_preset(deck: Deck, base: Preset | None = None) -> Preset:
    try:
        return apply_overrides(base if base is not None else Preset(), deck.meta.preset_overrides)
    except ValidationError as e:
        first = e.errors()[0]["msg"]
        raise HTTPException(422, f"프리셋 덮어쓰기 값이 유효하지 않습니다: {first}")
```

- `create_app` 안에 헬퍼를 두고 기존 `_validated_preset(deck)` 호출 전부를 `_preset_for(deck)`로 교체한다. 호출부는 6곳이다: put_deck, render-plan GET, render-plan POST(Task 2 신설), export, generate_chapter, condense. generate_structure에는 호출이 없다 (2026-08-29 실측 정정):

```python
    def _preset_for(deck: Deck) -> Preset:
        return _validated_preset(deck, store.load_global_preset())
```

- 라우트 추가 (`list_projects` 위):

```python
    @app.get("/api/preset", response_model=Preset)
    def get_preset():
        return store.load_global_preset()

    @app.put("/api/preset", response_model=OkResponse)
    def put_preset(preset: Preset):
        store.save_global_preset(preset)
        return OkResponse()
```

- export 라우트가 전역 프리셋을 전달하게 수정:

```python
        path = export_deck_data(deck, store.exports_dir(name), global_preset=store.load_global_preset())
```

- [ ] **Step 5: openapi.json 재생성과 전체 통과 확인**

`backend/tests/test_openapi.py::test_openapi_contains_all_routes`의 목록에 `"/api/preset"`을 추가한다.

Run: `.venv/Scripts/python.exe scripts/dump_openapi.py`
Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/slidecaptain/storage/file_store.py backend/slidecaptain/server/app.py backend/tests/test_file_store.py backend/tests/test_api_projects.py backend/tests/test_openapi.py backend/openapi.json
git commit -m "feat: 전역 프리셋 저장과 API (환류의 전제, 단계 4 이월)"
```

---

### Task 4: 저장 단위와 의미 시점 스냅샷

**Files:**
- Modify: `backend/slidecaptain/storage/file_store.py`
- Modify: `backend/slidecaptain/server/app.py`
- Test: `backend/tests/test_file_store.py`, `backend/tests/test_api_projects.py`

**Interfaces:**
- Consumes: `_snapshot_current` (기존 내부)
- Produces: `save_deck(name, deck, snapshot: bool = True)` (기본값 유지로 화면 밖 호출자 안전), `snapshot_now(name) -> None`, `PUT /deck?snapshot=false` (쿼리 인자, 기본 true), `POST /api/projects/{name}/snapshots` → 201. Task 12의 자동 저장이 `snapshot=false`를, 의미 시점(결정 1)이 true와 POST를 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_file_store.py`에 추가:

```python
def test_save_deck_without_snapshot(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    deck = store.load_deck("p1")
    store.save_deck("p1", deck, snapshot=False)
    assert store.list_snapshots("p1") == []
    store.save_deck("p1", deck)  # 기본값은 여전히 스냅샷을 남긴다
    assert len(store.list_snapshots("p1")) == 1

def test_snapshot_now(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    store.snapshot_now("p1")
    assert len(store.list_snapshots("p1")) == 1
```

`backend/tests/test_api_projects.py`에 추가:

```python
def test_put_deck_snapshot_query(client):
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    client.put("/api/projects/p1/deck?snapshot=false", json=deck)
    assert client.get("/api/projects/p1/snapshots").json() == []
    client.put("/api/projects/p1/deck", json=deck)  # 기본값은 스냅샷
    assert len(client.get("/api/projects/p1/snapshots").json()) == 1

def test_explicit_snapshot_endpoint(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots")
    assert r.status_code == 201
    assert len(client.get("/api/projects/p1/snapshots").json()) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_store.py tests/test_api_projects.py -q`
Expected: 신규 4개 FAIL

- [ ] **Step 3: 구현**

`backend/slidecaptain/storage/file_store.py`:

- Protocol의 `save_deck` 시그니처를 `def save_deck(self, name: str, deck: Deck, snapshot: bool = True) -> None: ...`으로 바꾸고 `def snapshot_now(self, name: str) -> None: ...`을 추가
- `FileProjectStore.save_deck` 교체와 `snapshot_now` 추가:

```python
    def save_deck(self, name: str, deck: Deck, snapshot: bool = True) -> None:
        d = self._project_dir(name)
        if snapshot:
            self._snapshot_current(d)
        self._write_deck(d, deck)

    def snapshot_now(self, name: str) -> None:
        """의미 시점 스냅샷 (단계 4 결정 1): 내보내기 직전 등 명시적 복구 지점."""
        self._snapshot_current(self._project_dir(name))
```

`backend/slidecaptain/server/app.py`:

```python
    @app.put("/api/projects/{name}/deck", response_model=OkResponse)
    def put_deck(name: str, deck: Deck, snapshot: bool = True):
        _preset_for(deck)
        store.save_deck(name, deck, snapshot=snapshot)
        return OkResponse()

    @app.post("/api/projects/{name}/snapshots", response_model=OkResponse, status_code=201)
    def create_snapshot(name: str):
        store.snapshot_now(name)
        return OkResponse()
```

- [ ] **Step 4: openapi.json 재생성과 전체 통과 확인**

Run: `.venv/Scripts/python.exe scripts/dump_openapi.py` (PUT deck의 snapshot 쿼리와 POST /snapshots가 스키마에 추가된다. 경로 자체는 기존 목록에 있어 라우트 단언 수정은 불필요)
Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/storage/file_store.py backend/slidecaptain/server/app.py backend/tests/test_file_store.py backend/tests/test_api_projects.py backend/openapi.json
git commit -m "feat: 저장의 스냅샷 선택과 명시적 스냅샷 API (자동 저장 대비, 사용자 결정 반영)"
```

---

### Task 5: 복구 진입 경로 (deck.json 소실 프로젝트)

**Files:**
- Modify: `backend/slidecaptain/storage/file_store.py`
- Test: `backend/tests/test_file_store.py`, `backend/tests/test_api_projects.py`

**Interfaces:**
- Consumes: `_validate_name`, `_snapshot_current`(deck.json 부재 시 이미 무동작), `restore_snapshot` (기존)
- Produces: `ProjectInfo.status: Literal["ok", "needs_recovery"] = "ok"`. deck.json이 없어도 스냅샷이 남은 폴더는 목록에 status="needs_recovery"로 나타나고, `list_snapshots`와 `restore_snapshot`이 그 프로젝트에서도 동작한다(복원이 deck.json을 재생성). Task 8의 목록 화면과 Task 16의 복구 화면이 status를 소비한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_file_store.py`에 추가:

```python
def test_project_without_deck_listed_for_recovery(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    store.save_deck("p1", store.load_deck("p1"))  # 스냅샷 1개를 만든다
    (tmp_path / "projects" / "p1" / "deck.json").unlink()
    infos = store.list_projects()
    assert len(infos) == 1 and infos[0].status == "needs_recovery"
    snaps = store.list_snapshots("p1")  # deck.json 없이도 동작해야 한다
    assert len(snaps) == 1
    deck = store.restore_snapshot("p1", snaps[0].id)  # 복원이 deck.json을 재생성한다
    assert deck.meta.title == "p1"
    assert store.list_projects()[0].status == "ok"

def test_corrupt_deck_marked_needs_recovery(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    (tmp_path / "projects" / "p1" / "deck.json").write_text("{깨짐", encoding="utf-8")
    assert store.list_projects()[0].status == "needs_recovery"

def test_empty_dir_without_snapshots_not_listed(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    (tmp_path / "projects" / "빈폴더").mkdir(parents=True)
    assert store.list_projects() == []
```

`backend/tests/test_api_projects.py`에 추가 (파일 경로 조작이 필요해 client 픽스처 대신 직접 조립):

```python
def test_recovery_flow_over_api(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    api = TestClient(create_app(store))
    api.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = api.get("/api/projects/p1/deck").json()
    api.put("/api/projects/p1/deck", json=deck)  # 스냅샷 생성
    (tmp_path / "projects" / "p1" / "deck.json").unlink()
    assert api.get("/api/projects").json()[0]["status"] == "needs_recovery"
    snaps = api.get("/api/projects/p1/snapshots").json()
    r = api.post(f"/api/projects/p1/snapshots/{snaps[0]['id']}/restore")
    assert r.status_code == 200
    assert api.get("/api/projects/p1/deck").status_code == 200
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_store.py tests/test_api_projects.py -q`
Expected: 신규 4개 FAIL (status 필드 없음, deck 부재 시 ProjectNotFound)

- [ ] **Step 3: 구현**

`backend/slidecaptain/storage/file_store.py`:

- import 수정: `from typing import Literal, Protocol`
- `ProjectInfo`에 필드 추가:

```python
    status: Literal["ok", "needs_recovery"] = "ok"
```

- 스냅샷 접근용 헬퍼 추가 (`_project_dir` 아래):

```python
    def _project_dir_any(self, name: str) -> Path:
        """스냅샷 경로용: deck.json이 없어도(복구 대상) 프로젝트 폴더에 접근한다."""
        _validate_name(name, "프로젝트")
        d = self.root / name
        if not d.is_dir():
            raise ProjectNotFound(f"프로젝트를 찾지 못했습니다: {name}")
        return d
```

- `list_snapshots`와 `restore_snapshot`의 첫 줄을 `d = self._project_dir_any(name)`으로 교체 (다른 메서드는 deck.json을 계속 요구한다)
- `list_projects` 교체:

```python
    def list_projects(self) -> list[ProjectInfo]:
        infos = []
        for d in sorted(self.root.iterdir()):
            if not d.is_dir():
                continue
            if (d / "deck.json").exists():
                infos.append(self._info(d))
                continue
            snapshots_dir = d / "snapshots"
            snapshots = sorted(snapshots_dir.glob("deck-*.json")) if snapshots_dir.is_dir() else []
            if snapshots:  # deck.json은 사라졌지만 복구 지점이 남은 프로젝트
                mtime = datetime.fromtimestamp(snapshots[-1].stat().st_mtime).astimezone()
                infos.append(ProjectInfo(
                    name=d.name,
                    title="(deck.json 없음: 스냅샷 복구가 필요합니다)",
                    updated_at=mtime.isoformat(timespec="seconds"),
                    status="needs_recovery",
                ))
        return infos
```

- `_info`의 읽기 실패 갈래에 status를 싣는다:

```python
    def _info(self, d: Path) -> ProjectInfo:
        deck_path = d / "deck.json"
        status: Literal["ok", "needs_recovery"] = "ok"
        try:
            title = Deck.model_validate_json(deck_path.read_text(encoding="utf-8")).meta.title
        except (ValueError, ValidationError):
            title = "(deck.json 읽기 실패: 스냅샷 복구가 필요합니다)"
            status = "needs_recovery"
        mtime = datetime.fromtimestamp(deck_path.stat().st_mtime).astimezone()
        return ProjectInfo(
            name=d.name, title=title, updated_at=mtime.isoformat(timespec="seconds"), status=status
        )
```

- [ ] **Step 4: openapi.json 재생성과 전체 통과 확인**

Run: `.venv/Scripts/python.exe scripts/dump_openapi.py` (ProjectInfo에 status 필드가 추가된다)
Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/storage/file_store.py backend/tests/test_file_store.py backend/tests/test_api_projects.py backend/openapi.json
git commit -m "feat: deck.json 소실 프로젝트의 복구 진입 경로 (단계 1 이월)"
```

---

### Task 6: API 위생 (오류 한국어 일관화, TrustedHost, 자료 총량 상한)

**Files:**
- Modify: `backend/slidecaptain/server/app.py`
- Test: `backend/tests/test_api_projects.py`, `backend/tests/test_api_generate.py`, `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: FastAPI `RequestValidationError`, starlette `TrustedHostMiddleware`, test_api_generate.py의 기존 `store` 픽스처와 `_client(store, responses)` 헬퍼 (client 픽스처는 이 파일에 없다)
- Produces: 모든 422/400 응답의 detail이 한국어 문자열 하나다(목록형 금지). `GenerateStructureRequest.target_chapters`는 1 이상. Host 헤더가 127.0.0.1/localhost가 아니면 400. 자료 합계 100,000자 초과 시 생성 라우트가 422. serve의 127.0.0.1 바인딩이 테스트로 고정된다(이월 항목의 "바인딩 자동 테스트"). Task 8 이후 화면의 오류 표시가 detail 문자열 하나를 전제한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_projects.py`에 추가:

```python
def test_validation_error_detail_is_korean_string(client):
    r = client.post("/api/projects", json={})  # name 빠짐
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert "name" in r.json()["detail"] and "빠졌습니다" in r.json()["detail"]

def test_deck_validator_korean_message_preserved(client):
    client.post("/api/projects", json={"name": "p1"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["slides"] = [{"chapter_id": "유령", "slots": {"template": "bullet_box", "conclusion": "결"}}]
    r = client.put("/api/projects/p1/deck", json=deck)
    assert r.status_code == 422
    assert "구조안에 없는 장" in r.json()["detail"]  # 모델 검증의 한국어 문구가 그대로 나온다

def test_foreign_host_header_rejected(client):
    r = client.get("/api/projects", headers={"host": "evil.example.com"})
    assert r.status_code == 400
```

`backend/tests/test_api_generate.py`에 추가. 이 파일에는 client 픽스처가 없으므로 기존 관례인 `store` 픽스처 + `_client(store, responses)` 헬퍼를 쓴다 (2026-08-29 실측 정정. 프로바이더 없는 앱은 생성 라우트가 503을 먼저 내므로, 상한 검사가 검증되려면 StubProvider가 달린 앱이어야 한다):

```python
def test_target_chapters_zero_422(store):
    client = _client(store, [])
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/generate/structure", json={"target_chapters": 0})
    assert r.status_code == 422


def test_sources_over_total_limit_422(store):
    client = _client(store, [])
    client.post("/api/projects", json={"name": "p1"})
    client.put("/api/projects/p1/sources/큰자료.md", json={"text": "가" * 100_001})
    r = client.post("/api/projects/p1/generate/structure", json={})
    assert r.status_code == 422
    assert "발췌" in r.json()["detail"]
```

`backend/tests/test_cli.py`에 추가 (이월 항목의 바인딩 자동 테스트. uvicorn 실행을 가로채 바인딩 인자를 단언한다):

```python
def test_serve_binds_localhost_only(monkeypatch, tmp_path):
    import uvicorn

    captured: dict = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    from slidecaptain.__main__ import main

    assert main(["serve", "--data-dir", str(tmp_path / "data"), "--port", "8770"]) == 0
    assert captured["host"] == "127.0.0.1"  # 로컬 전용 바인딩 (설계서 1.3)
    assert captured["port"] == 8770
```

기존 테스트 중 detail의 목록형(pydantic 기본)을 전제한 단언이 있으면 문자열 전제로 조정한다.

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_projects.py tests/test_api_generate.py tests/test_cli.py -q`
Expected: 신규 6개 FAIL

- [ ] **Step 3: 구현**

`backend/slidecaptain/server/app.py`:

- import 추가:

```python
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
```

- 모듈 상수 추가:

```python
_SOURCES_TOTAL_MAX_CHARS = 100_000  # 자료 전문이 프롬프트에 동봉되므로 상한을 명시한다 (단계 4 결정 14)

_VALIDATION_TYPE_MESSAGES = {
    "missing": "필수 값이 빠졌습니다",
    "greater_than_equal": "허용된 최솟값보다 작습니다",
    "string_type": "글자여야 합니다",
    "int_type": "정수여야 합니다",
    "bool_type": "참/거짓 값이어야 합니다",
    "list_type": "목록이어야 합니다",
    "model_type": "객체 형식이어야 합니다",
    "literal_error": "허용된 값이 아닙니다",
    "string_pattern_mismatch": "형식에 맞지 않습니다",
}
```

- `GenerateStructureRequest` 수정:

```python
class GenerateStructureRequest(BaseModel):
    target_chapters: int | None = Field(default=None, ge=1)
    instructions: str = ""
```

- `create_app` 안에서 미들웨어와 핸들러 추가 (기존 exception_handler들 옆):

```python
    # DNS 리바인딩 방지. testserver는 TestClient의 기본 Host라 허용한다 (브라우저가 보낼 수 없는 값)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request, exc: RequestValidationError):
        e = exc.errors()[0]
        if e["type"] == "value_error":
            # 모델 validator의 한국어 메시지를 그대로 살린다 (예: "구조안에 없는 장을 가리킵니다")
            message = str(e["msg"]).removeprefix("Value error, ")
        else:
            loc = ".".join(str(p) for p in e["loc"] if p != "body")
            message = f"{loc}: {_VALIDATION_TYPE_MESSAGES.get(e['type'], '입력 형식이 맞지 않습니다')}"
        return JSONResponse(status_code=422, content={"detail": message})
```

- `_load_sources`에 합계 상한 추가:

```python
    def _load_sources(name: str) -> dict[str, str]:
        files = store.list_sources(name)
        if not files:
            raise HTTPException(
                422,
                "입력 자료가 없습니다. 자료 화면에서 파일을 추가하거나, "
                "프로젝트 폴더의 sources에 텍스트 파일을 넣어 주세요.",
            )
        texts = {f: store.read_source(name, f) for f in files}
        total = sum(len(t) for t in texts.values())
        if total > _SOURCES_TOTAL_MAX_CHARS:
            raise HTTPException(
                422,
                f"자료가 너무 큽니다(합계 {total:,}자, 한도 {_SOURCES_TOTAL_MAX_CHARS:,}자). "
                "필요한 부분만 발췌해 주세요.",
            )
        return texts
```

- [ ] **Step 4: openapi.json 재생성과 전체 통과 확인**

Run: `.venv/Scripts/python.exe scripts/dump_openapi.py` (target_chapters의 ge 제약이 스키마에 반영된다)
Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/server/app.py backend/tests/test_api_projects.py backend/tests/test_api_generate.py backend/tests/test_cli.py backend/openapi.json
git commit -m "feat: 오류 한국어 일관화, TrustedHost, 자료 총량 상한, 바인딩 단언 (단계 4 이월 4건)"
```

---

### Task 7: 파이프라인 위생 (정규화 공백, 수치 정밀화, 타임아웃) + 타입 재생성

**Files:**
- Modify: `backend/slidecaptain/pipeline/normalize.py`
- Modify: `backend/slidecaptain/pipeline/numbers.py`
- Modify: `backend/slidecaptain/pipeline/service.py`
- Modify: `backend/slidecaptain/pipeline/subscription.py`
- Modify: `backend/openapi.json`, `frontend/src/api/types.ts` (재생성)
- Test: `backend/tests/test_normalize.py`, `backend/tests/test_numbers.py`, `backend/tests/test_generation_service.py`, `backend/tests/test_subscription_provider.py`

**Interfaces:**
- Consumes: 기존 `normalize_text`, `find_unverified_numbers`, `GenerationService`, `SubscriptionProvider`
- Produces: 유니코드 공백(U+3000, U+00A0)이 일반 공백으로 축약된다. 수치 대조의 lookbehind가 `(?<!\d)(?<!\d\.)`로 정밀화되고 대조 말뭉치에 덱 제목이 들어간다. `SubscriptionProvider(model, timeout_s=300.0)`이 타임아웃 시 ProviderCallFailed 한국어 안내를 낸다. 이후 프런트 태스크가 쓰는 `frontend/src/api/types.ts`가 Task 1~6의 스키마 변화(lines, status, preset API 등)를 반영한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_normalize.py`에 추가:

```python
def test_unicode_spaces_collapsed():
    assert normalize_text("가　나") == "가 나"
    assert normalize_text("가 나") == "가 나"
    assert normalize_text("가　  나") == "가 나"
```

`backend/tests/test_numbers.py`에 추가:

```python
def test_number_after_sentence_period_is_found():
    # 자료의 "이다.500억"처럼 문장 마침표 바로 뒤 숫자도 근거로 인정한다 (오탐 제거)
    assert find_unverified_numbers(["500억 규모"], ["시장이다.500억 규모다"]) == []

def test_decimal_fraction_still_guarded():
    # 3.14의 14는 여전히 소수부라 별개 숫자 14의 근거가 아니다
    assert find_unverified_numbers(["14개"], ["원주율은 3.14다"]) == ["14"]
```

`backend/tests/test_generation_service.py`에 추가. 이 저장소의 비동기 테스트 관례는 동기 함수 + `asyncio.run`이다(전역 제약. pytest-asyncio가 없어 맨 `async def` 테스트는 실행되지 않는다). 이 파일에 이미 있는 모의 프로바이더 헬퍼가 아래 `_TitleFake`와 동등하면 그것을 재사용하고, `asyncio` import가 없으면 추가한다:

```python
class _TitleFake:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, prompt, schema):
        return ProviderResponse(structured=self.payload, raw_text="")


def test_deck_title_numbers_count_as_verified():
    meta = DeckMeta(title="2026 사업 검토")
    payload = {"chapters": [
        {"topic": "2026 전략", "conclusion": "", "template": "bullet_box", "source_refs": []}
    ]}
    service = GenerationService(_TitleFake(payload), FontMetrics.load_default())
    result = asyncio.run(service.generate_structure(meta, {"a.md": "자료에는 연도가 없다"}))
    assert result.status == "ok"
    assert "2026" not in result.unverified_numbers  # 덱 제목이 대조 말뭉치에 포함된다


def test_chapter_numbers_verified_against_deck_title():
    deck = Deck(
        meta=DeckMeta(title="2026 사업 검토"),
        structure=Structure(chapters=[Chapter(id="c1", topic="표지", template="cover")]),
    )
    payload = {"template": "cover", "title": "2026 사업 검토", "subtitle": "", "date": "", "audience": ""}
    service = GenerationService(_TitleFake(payload), FontMetrics.load_default())
    result = asyncio.run(service.generate_chapter(deck, "c1", {"a.md": "연도 없음"}, Preset()))
    assert result.status == "ok"
    assert "2026" not in result.unverified_numbers
```

`backend/tests/test_subscription_provider.py`에 추가. 이 파일의 관례를 따른다: 동기 함수 + `asyncio.run`, subscription 모듈 별칭은 `sub`, monkeypatch 대상은 `sub.query`:

```python
def test_timeout_maps_to_korean_error(monkeypatch):
    async def slow_query(prompt, options):
        await asyncio.sleep(0.2)
        yield object()  # 타임아웃이 먼저 걸려 도달하지 않는다

    monkeypatch.setattr(sub, "query", slow_query)
    provider = SubscriptionProvider(timeout_s=0.05)
    with pytest.raises(ProviderCallFailed) as exc_info:
        asyncio.run(provider.complete("프롬프트", {"type": "object"}))
    assert "오래 걸려" in str(exc_info.value)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_normalize.py tests/test_numbers.py tests/test_generation_service.py tests/test_subscription_provider.py -q`
Expected: 신규 테스트 FAIL

- [ ] **Step 3: 구현**

`backend/slidecaptain/pipeline/normalize.py`의 `normalize_text`에서 탭 치환 줄 다음에 추가:

```python
    text = text.replace("\u3000", " ").replace("\u00a0", " ")  # 전각 공백과 NBSP (단계 3 이월)
```

`backend/slidecaptain/pipeline/numbers.py`의 `find_unverified_numbers`에서 패턴을 교체하고 독스트링의 경계 설명을 갱신:

```python
            pattern = re.compile(r"(?<!\d)(?<!\d\.)" + re.escape(number) + r"(?!\.?\d)")
```

(앞 경계는 "숫자" 또는 "숫자."만 막는다: 문장 마침표 뒤 숫자는 근거로 인정하고, 1234 안의 234와 3.14 안의 14는 여전히 막는다.)

`backend/slidecaptain/pipeline/service.py`:

- `generate_structure`의 대조 호출을 교체:

```python
            unverified_numbers=find_unverified_numbers(texts, list(sources.values()) + [meta.title]),
```

- `_chapter_result` 시그니처에 `deck: Deck`를 첫 인자로 추가하고 두 호출부(`generate_chapter`, `condense_chapter`)를 맞춘다. 대조 호출 교체:

```python
            unverified_numbers=find_unverified_numbers(
                texts, list(sources.values()) + [deck.meta.title]
            ),
```

`backend/slidecaptain/pipeline/subscription.py`:

- `import asyncio` 추가, 생성자와 호출 교체:

```python
class SubscriptionProvider:
    def __init__(self, model: str | None = None, timeout_s: float = 300.0) -> None:
        self.model = model or DEFAULT_MODEL
        self.timeout_s = timeout_s
```

`complete`의 메시지 소비부를 감싼다 (기존 `async for`를 내부 함수로 이동):

```python
        async def _consume() -> ResultMessage | None:
            found: ResultMessage | None = None
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    found = message
            return found

        result: ResultMessage | None = None
        try:
            result = await asyncio.wait_for(_consume(), timeout=self.timeout_s)
        except TimeoutError as e:
            _LOG.warning("AI 호출 타임아웃: %.0f초", self.timeout_s)
            raise ProviderCallFailed(
                f"AI 응답이 너무 오래 걸려 중단했습니다({self.timeout_s:.0f}초 한도). "
                "잠시 후 다시 시도해 주세요."
            ) from e
        except CLINotFoundError as e:
            ...  # 기존 처리 유지
```

- [ ] **Step 4: 전체 통과 확인과 타입 재생성**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

Run: `.venv/Scripts/python.exe scripts/dump_openapi.py` (backend 폴더)
Run: `npm run generate-types` (frontend 폴더 안에서)
Expected: `frontend/src/api/types.ts`에 `lines`, `header_lines`, `cell_lines`, `status`, `/api/preset`, `/api/render-plan` POST가 나타난다

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/pipeline backend/tests backend/openapi.json frontend/src/api/types.ts
git commit -m "feat: 파이프라인 위생 3건과 타입 재생성 (유니코드 공백, 수치 정밀화, 타임아웃)"
```

---

### Task 8: 프런트엔드 스캐폴딩 + API 클라이언트 + 프로젝트 목록 화면

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/src/test/setup.ts`
- Create: `frontend/src/api/client.ts`, `frontend/src/screens/ProjectList.tsx`
- Test: `frontend/src/api/client.test.ts`, `frontend/src/screens/ProjectList.test.tsx`

**Interfaces:**
- Consumes: `frontend/src/api/types.ts` (Task 7에서 재생성된 OpenAPI 타입)
- Produces: `api` 객체(모든 백엔드 호출의 단일 통로, 타입은 생성 타입의 alias), `ApiError(status, detail)`, `messageOf(e)` (오류를 사용자 문구로), `<App />` (목록 ↔ 프로젝트 화면 전환). 이후 모든 프런트 태스크가 `api`와 타입 alias만 쓴다(직접 fetch 금지).

- [ ] **Step 1: 의존성과 설정 파일 작성**

`frontend/package.json` 전체 교체:

```json
{
  "name": "slidecaptain-frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run",
    "generate-types": "openapi-typescript ../backend/openapi.json -o src/api/types.ts"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^5.0.0",
    "jsdom": "^26.0.0",
    "openapi-typescript": "^7.13.0",
    "typescript": "^5.7.0",
    "vite": "^8.0.0",
    "vitest": "^4.0.0"
  }
}
```

`frontend` 폴더 안에서 `npm install`. peer 의존성 충돌이 나면 vite 8과 호환되는 인접 메이저로 조정하고, 실제 설치된 메이저 버전을 커밋 메시지에 남긴다.

`frontend/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8765" },  // 개발 중 same-origin 유지 (CORS 불필요, 결정 7)
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
    clearMocks: true,  // 테스트마다 모의 호출 기록을 비운다 (파일 내 누적으로 인한 오탐 방지)
  },
});
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Slide Captain</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`frontend/src/styles.css` (최소 시작점, 이후 태스크에서 클래스 추가):

```css
:root { font-family: "Noto Sans KR", sans-serif; color: #202020; }
body { margin: 0; }
main { padding: 16px; }
button { cursor: pointer; }
[role="alert"] { color: #b00020; }
```

- [ ] **Step 2: 실패하는 테스트 작성**

`frontend/src/api/client.test.ts`:

```ts
import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

it("오류 응답의 detail을 ApiError 메시지로 만든다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "자료가 너무 큽니다" }), { status: 422 }),
  ));
  await expect(api.listProjects()).rejects.toThrowError("자료가 너무 큽니다");
});

it("성공 응답의 JSON을 그대로 돌려준다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify([{ name: "p1", title: "t", updated_at: "", status: "ok" }]), { status: 200 }),
  ));
  const projects = await api.listProjects();
  expect(projects[0].name).toBe("p1");
});

it("스냅샷 여부를 쿼리로 보낸다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.putDeck("p1", { schema_version: 1, meta: { title: "t" } } as never, false);
  expect(fetchMock.mock.calls[0][0]).toContain("/deck?snapshot=false");
});
```

`frontend/src/screens/ProjectList.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { ProjectList } from "./ProjectList";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listProjects: vi.fn(), createProject: vi.fn() } };
});

it("프로젝트 목록과 복구 필요 표지를 보여준다", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([
    { name: "p1", title: "주간 보고", updated_at: "", status: "ok" },
    { name: "p2", title: "(deck.json 없음: 스냅샷 복구가 필요합니다)", updated_at: "", status: "needs_recovery" },
  ]);
  render(<ProjectList onOpen={() => {}} />);
  expect(await screen.findByText("주간 보고")).toBeInTheDocument();
  expect(screen.getByText("복구 필요")).toBeInTheDocument();
});

it("새 프로젝트를 만들고 연다", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([]);
  vi.mocked(api.createProject).mockResolvedValue(
    { name: "새보고", title: "새보고", updated_at: "", status: "ok" });
  const onOpen = vi.fn();
  render(<ProjectList onOpen={onOpen} />);
  await userEvent.type(screen.getByLabelText("프로젝트 이름"), "새보고");
  await userEvent.click(screen.getByText("만들기"));
  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ name: "새보고" }));
});

it("만들기 실패의 안내 문구를 보여준다", async () => {
  vi.mocked(api.listProjects).mockResolvedValue([]);
  const { ApiError } = await import("../api/client");
  vi.mocked(api.createProject).mockRejectedValue(new ApiError(409, "같은 이름의 프로젝트가 이미 있습니다: p1"));
  render(<ProjectList onOpen={() => {}} />);
  await userEvent.type(screen.getByLabelText("프로젝트 이름"), "p1");
  await userEvent.click(screen.getByText("만들기"));
  expect(await screen.findByRole("alert")).toHaveTextContent("이미 있습니다");
});
```

- [ ] **Step 3: 실패 확인**

Run: `frontend` 폴더 안에서 `npm test`
Expected: FAIL (client.ts, ProjectList.tsx 없음)

- [ ] **Step 4: 구현**

`frontend/src/api/client.ts`:

```ts
import type { components } from "./types";

export type Deck = components["schemas"]["Deck"];
export type DeckMeta = components["schemas"]["DeckMeta"];
export type Chapter = components["schemas"]["Chapter"];
export type Structure = components["schemas"]["Structure"];
export type Slide = components["schemas"]["Slide"];
export type Slots = Slide["slots"];
export type Bullet = components["schemas"]["Bullet"];  // level이 필수 필드다 (기본값이 있어도 생성 타입에서는 필수)
export type Preset = components["schemas"]["Preset"];
export type ProjectInfo = components["schemas"]["ProjectInfo"];
export type SnapshotInfo = components["schemas"]["SnapshotInfo"];
export type RenderPlan = components["schemas"]["RenderPlan"];
export type SlidePlan = components["schemas"]["SlidePlan"];
export type Frame = components["schemas"]["Frame"];
export type Para = components["schemas"]["Para"];
export type TablePlan = components["schemas"]["TablePlan"];
export type CapacityWarning = components["schemas"]["CapacityWarning"];
export type StructureResult = components["schemas"]["StructureResult"];
export type ChapterResult = components["schemas"]["ChapterResult"];
export type TemplateName = Chapter["template"];

export class ApiError extends Error {
  constructor(public status: number, detail: string) {
    super(detail);
  }
}

export function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : "서버에 연결하지 못했습니다. 앱을 다시 시작해 주세요.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let detail = "요청이 실패했습니다. 잠시 후 다시 시도해 주세요.";
    try {
      const body = await r.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // JSON 본문이 아니면 기본 문구 유지
    }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  listProjects: () => request<ProjectInfo[]>("/api/projects"),
  createProject: (name: string, title: string) =>
    request<ProjectInfo>("/api/projects", { method: "POST", body: JSON.stringify({ name, title }) }),
  getDeck: (name: string) => request<Deck>(`/api/projects/${enc(name)}/deck`),
  putDeck: (name: string, deck: Deck, snapshot: boolean) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/deck?snapshot=${snapshot}`, {
      method: "PUT", body: JSON.stringify(deck),
    }),
  measure: (deck: Deck) =>
    request<RenderPlan>("/api/render-plan", { method: "POST", body: JSON.stringify(deck) }),
  getPreset: () => request<Preset>("/api/preset"),
  putPreset: (preset: Preset) =>
    request<{ ok: boolean }>("/api/preset", { method: "PUT", body: JSON.stringify(preset) }),
  listSources: (name: string) => request<string[]>(`/api/projects/${enc(name)}/sources`),
  readSource: (name: string, file: string) =>
    request<{ text: string }>(`/api/projects/${enc(name)}/sources/${enc(file)}`),
  writeSource: (name: string, file: string, text: string) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/sources/${enc(file)}`, {
      method: "PUT", body: JSON.stringify({ text }),
    }),
  listSnapshots: (name: string) => request<SnapshotInfo[]>(`/api/projects/${enc(name)}/snapshots`),
  createSnapshot: (name: string) =>
    request<{ ok: boolean }>(`/api/projects/${enc(name)}/snapshots`, { method: "POST" }),
  restoreSnapshot: (name: string, id: string) =>
    request<Deck>(`/api/projects/${enc(name)}/snapshots/${enc(id)}/restore`, { method: "POST" }),
  exportDeck: (name: string) =>
    request<{ path: string }>(`/api/projects/${enc(name)}/export`, { method: "POST" }),
  generateStructure: (name: string, req: { target_chapters?: number | null; instructions?: string }) =>
    request<StructureResult>(`/api/projects/${enc(name)}/generate/structure`, {
      method: "POST", body: JSON.stringify(req),
    }),
  generateChapter: (name: string, chapterId: string, instructions = "") =>
    request<ChapterResult>(`/api/projects/${enc(name)}/generate/chapter/${enc(chapterId)}`, {
      method: "POST", body: JSON.stringify({ instructions }),
    }),
  condenseChapter: (name: string, chapterId: string, slots: Slots, instructions = "") =>
    request<ChapterResult>(`/api/projects/${enc(name)}/generate/chapter/${enc(chapterId)}/condense`, {
      method: "POST", body: JSON.stringify({ slots, instructions }),
    }),
};
```

`frontend/src/screens/ProjectList.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api, messageOf, type ProjectInfo } from "../api/client";

export function ProjectList({ onOpen }: { onOpen: (p: ProjectInfo) => void }) {
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(messageOf(e)));
  }, []);

  const create = async () => {
    setError("");
    try {
      onOpen(await api.createProject(name.trim(), title.trim()));
    } catch (e) {
      setError(messageOf(e));
    }
  };

  return (
    <main className="project-list">
      <h1>Slide Captain</h1>
      {error && <p role="alert">{error}</p>}
      <section>
        <h2>새 프로젝트</h2>
        <input aria-label="프로젝트 이름" placeholder="프로젝트 이름"
          value={name} onChange={(e) => setName(e.target.value)} />
        <input aria-label="보고서 제목" placeholder="보고서 제목 (비우면 이름과 같음)"
          value={title} onChange={(e) => setTitle(e.target.value)} />
        <button onClick={create} disabled={!name.trim()}>만들기</button>
      </section>
      <section>
        <h2>프로젝트</h2>
        {projects === null ? (
          <p>불러오는 중...</p>
        ) : projects.length === 0 ? (
          <p>아직 프로젝트가 없습니다. 위에서 새로 만들어 주세요.</p>
        ) : (
          <ul>
            {projects.map((p) => (
              <li key={p.name}>
                <button onClick={() => onOpen(p)}>
                  {p.title} <small>({p.name}, {p.updated_at})</small>
                  {p.status === "needs_recovery" && <em> 복구 필요</em>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
```

`frontend/src/App.tsx` (프로젝트 화면 분기는 Task 9가 교체한다):

```tsx
import { useState } from "react";
import type { ProjectInfo } from "./api/client";
import { ProjectList } from "./screens/ProjectList";

export function App() {
  const [current, setCurrent] = useState<ProjectInfo | null>(null);
  if (current === null) return <ProjectList onOpen={setCurrent} />;
  return (
    <main>
      <button onClick={() => setCurrent(null)}>목록으로</button>
      <h1>{current.title}</h1>
    </main>
  );
}
```

`frontend/src/main.tsx`:

```tsx
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(<App />);
```

- [ ] **Step 5: 통과와 빌드 확인**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS
Run: `frontend` 폴더 안에서 `npm run build` → 타입 검사와 빌드 성공 (`dist/` 생성)

- [ ] **Step 6: 커밋**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/index.html frontend/src
git commit -m "feat: 프런트엔드 스캐폴딩과 API 클라이언트, 프로젝트 목록 화면"
```

---

### Task 9: FastAPI 정적 마운트 + 프로젝트 화면 골격 + 자료와 목적 입력

**Files:**
- Modify: `backend/slidecaptain/server/app.py`, `backend/slidecaptain/__main__.py`
- Create: `backend/tests/test_api_static.py`
- Create: `frontend/src/screens/ProjectView.tsx`, `frontend/src/screens/SourcesScreen.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/screens/SourcesScreen.test.tsx`

**Interfaces:**
- Consumes: `api.listSources/readSource/writeSource/putDeck/getDeck`, `ProjectInfo.status`
- Produces: `create_app(store, provider=None, static_dir: Path | None = None)` (dist가 있으면 마운트, API 라우트 우선). `<ProjectView project onBack>`: 탭 [자료] [구조안] [편집]과 게이트(결정 16). `SourcesScreen`의 자료 CRUD와 보고 정보(제목, 보고 유형, 피보고자) 저장. Task 10이 구조안 탭을, Task 12가 편집 탭을 이 골격에 끼운다.

- [ ] **Step 1: 백엔드 실패 테스트 작성**

`backend/tests/test_api_static.py` 신규:

```python
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


def test_static_ui_served_and_api_precedence(tmp_path):
    ui = tmp_path / "dist"
    ui.mkdir()
    (ui / "index.html").write_text("<h1>ui</h1>", encoding="utf-8")
    client = TestClient(create_app(FileProjectStore(tmp_path / "projects"), static_dir=ui))
    assert "<h1>ui</h1>" in client.get("/").text
    assert client.get("/api/projects").json() == []  # API 라우트가 정적보다 우선


def test_missing_static_dir_means_api_only(tmp_path):
    client = TestClient(
        create_app(FileProjectStore(tmp_path / "projects"), static_dir=tmp_path / "없는폴더")
    )
    assert client.get("/api/projects").status_code == 200
    assert client.get("/").status_code == 404
```

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_static.py -q` → FAIL (인자 없음)

- [ ] **Step 2: 백엔드 구현**

`backend/slidecaptain/server/app.py`:

- import 추가: `from pathlib import Path`, `from fastapi.staticfiles import StaticFiles`
- 시그니처 교체: `def create_app(store: ProjectStore, provider: AIProvider | None = None, static_dir: Path | None = None) -> FastAPI:`
- `return app` 직전에 추가:

```python
    if static_dir is not None and static_dir.is_dir():
        # 빌드된 화면을 같은 주소에서 서빙한다 (결정 7). API 라우트가 먼저 등록되어 우선한다
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
```

`backend/slidecaptain/__main__.py`:

- `_build_serve_app` 교체:

```python
def _build_serve_app(data_dir: Path, model: str | None):
    from slidecaptain.pipeline.subscription import SubscriptionProvider
    from slidecaptain.server.app import create_app
    from slidecaptain.storage.file_store import FileProjectStore

    ui_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return create_app(
        FileProjectStore(data_dir), provider=SubscriptionProvider(model=model), static_dir=ui_dir
    )
```

- `_run_serve`의 주소 출력 앞에 안내 추가:

```python
    ui_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not ui_dir.is_dir():
        print(
            "화면 파일이 아직 없어 API만 제공합니다. "
            "frontend 폴더에서 npm run build를 실행하면 화면이 함께 제공됩니다."
        )
```

Run: `.venv/Scripts/python.exe -m pytest tests -q` → 전체 PASS. 커밋:

```bash
git add backend/slidecaptain/server/app.py backend/slidecaptain/__main__.py backend/tests/test_api_static.py
git commit -m "feat: 빌드된 화면의 정적 서빙 (serve 한 명령으로 화면 제공)"
```

- [ ] **Step 3: 프런트 실패 테스트 작성**

`frontend/src/screens/SourcesScreen.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck } from "../api/client";
import { SourcesScreen } from "./SourcesScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    listSources: vi.fn(), readSource: vi.fn(), writeSource: vi.fn(), putDeck: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [] },
  slides: [],
};

it("자료 목록을 보여주고 파일을 열어 저장한다", async () => {
  vi.mocked(api.listSources).mockResolvedValue(["자료.md"]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.click(await screen.findByText("자료.md"));
  const area = await screen.findByLabelText("자료 내용");
  expect(area).toHaveValue("원문");
  await userEvent.clear(area);
  await userEvent.type(area, "고친 원문");
  await userEvent.click(screen.getByText("자료 저장"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "자료.md", "고친 원문");
});

it("보고 정보를 저장하면 덱이 갱신된다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  render(<SourcesScreen project={project} deck={deck} onDeckChange={onDeckChange} />);
  const title = screen.getByLabelText("보고서 제목");
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  expect(api.putDeck).toHaveBeenCalledWith(
    "p1", expect.objectContaining({ meta: expect.objectContaining({ title: "새 제목" }) }), false);
  expect(onDeckChange).toHaveBeenCalled();
});

it("새 자료 이름에 확장자가 없으면 .md를 붙인다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  vi.mocked(api.readSource).mockResolvedValue({ text: "" });
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.type(screen.getByLabelText("새 자료 이름"), "리서치");
  await userEvent.click(screen.getByText("자료 추가"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "리서치.md", "");
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 4: 프런트 구현**

`frontend/src/screens/SourcesScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api, messageOf, type Deck, type ProjectInfo } from "../api/client";

const REPORT_TYPES = [
  ["research", "연구분석"],
  ["approval", "승인요청"],
  ["strategy", "전략기획"],
] as const;

export function SourcesScreen({ project, deck, onDeckChange }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
}) {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [newName, setNewName] = useState("");
  const [meta, setMeta] = useState(deck.meta);
  const [notice, setNotice] = useState("");

  const reload = () => {
    api.listSources(project.name).then(setFiles).catch((e) => setNotice(messageOf(e)));
  };
  useEffect(reload, [project.name]);

  const open = async (f: string) => {
    try {
      const s = await api.readSource(project.name, f);
      setSelected(f);
      setText(s.text);
      setNotice("");
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  const saveText = async () => {
    if (selected === null) return;
    try {
      await api.writeSource(project.name, selected, text);
      setNotice("자료를 저장했습니다.");
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  const addFile = async () => {
    const base = newName.trim();
    const f = base.includes(".") ? base : `${base}.md`;
    try {
      await api.writeSource(project.name, f, "");
      setNewName("");
      reload();
      await open(f);
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  const saveMeta = async () => {
    const updated = { ...deck, meta };
    try {
      await api.putDeck(project.name, updated, false);
      onDeckChange(updated);
      setNotice("보고 정보를 저장했습니다.");
    } catch (e) {
      setNotice(messageOf(e));
    }
  };

  return (
    <div className="sources-screen">
      {notice && <p role="alert">{notice}</p>}
      <section>
        <h2>보고 정보</h2>
        <label>보고서 제목
          <input aria-label="보고서 제목" value={meta.title}
            onChange={(e) => setMeta({ ...meta, title: e.target.value })} />
        </label>
        <label>보고 유형
          <select aria-label="보고 유형" value={meta.report_type}
            onChange={(e) => setMeta({ ...meta, report_type: e.target.value as Deck["meta"]["report_type"] })}>
            {REPORT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        <label>피보고자
          <input aria-label="피보고자" value={meta.audience ?? ""}
            onChange={(e) => setMeta({ ...meta, audience: e.target.value })} />
        </label>
        <button onClick={saveMeta}>보고 정보 저장</button>
      </section>
      <section>
        <h2>입력 자료</h2>
        <p>완성된 리서치 자료(마크다운, 텍스트)를 넣어 주세요. 탐색기로 프로젝트 폴더의 sources에 파일을 넣어도 됩니다.</p>
        <ul>
          {files.map((f) => (
            <li key={f}><button onClick={() => open(f)}>{f}</button></li>
          ))}
        </ul>
        <input aria-label="새 자료 이름" placeholder="새 자료 이름"
          value={newName} onChange={(e) => setNewName(e.target.value)} />
        <button onClick={addFile} disabled={!newName.trim()}>자료 추가</button>
        {selected !== null && (
          <div>
            <h3>{selected}</h3>
            <textarea aria-label="자료 내용" rows={16} value={text}
              onChange={(e) => setText(e.target.value)} />
            <button onClick={saveText}>자료 저장</button>
          </div>
        )}
      </section>
    </div>
  );
}
```

`frontend/src/screens/ProjectView.tsx` (구조안, 편집 탭의 내용은 Task 10과 12가 채운다. 이 시점에는 자료 탭만 동작하고 나머지 버튼은 비활성):

```tsx
import { useEffect, useState } from "react";
import { api, messageOf, type Deck, type ProjectInfo } from "../api/client";
import { SourcesScreen } from "./SourcesScreen";

export type Tab = "sources" | "structure" | "editor";

export function ProjectView({ project, onBack }: { project: ProjectInfo; onBack: () => void }) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [tab, setTab] = useState<Tab>("sources");
  const [error, setError] = useState("");

  useEffect(() => {
    if (project.status === "ok") {
      api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
    }
  }, [project.name, project.status]);

  if (project.status === "needs_recovery") {
    // 복구 화면은 Task 16이 교체한다. 그때까지는 안내만 한다
    return (
      <main>
        <p role="alert">이 프로젝트는 복구가 필요합니다. 스냅샷 복구 화면에서 이전 저장 시점으로 되돌릴 수 있습니다.</p>
        <button onClick={onBack}>목록으로</button>
      </main>
    );
  }
  if (deck === null) {
    // 최초 로드 실패만 화면 전체를 대체한다. 로드 이후의 오류(내보내기 실패 등)는
    // 아래 배너로 표시해 편집 맥락을 잃지 않는다 (2026-08-29 적대 리뷰 반영)
    return (
      <main>
        {error ? (
          <>
            <p role="alert">{error}</p>
            <button onClick={onBack}>목록으로</button>
          </>
        ) : (
          <p>불러오는 중...</p>
        )}
      </main>
    );
  }

  const hasSlides = deck.slides.length > 0;
  return (
    <main className="project-view">
      {error && (
        <p role="alert">{error} <button onClick={() => setError("")}>닫기</button></p>
      )}
      <header>
        <button onClick={onBack}>목록으로</button>
        <h1>{deck.meta.title}</h1>
        <nav>
          <button aria-pressed={tab === "sources"} onClick={() => setTab("sources")}>자료</button>
          <button aria-pressed={tab === "structure"} disabled>구조안</button>
          <button aria-pressed={tab === "editor"} disabled={!hasSlides}
            title={hasSlides ? undefined : "구조안을 승인하고 내용을 생성하면 열립니다"}>편집</button>
        </nav>
      </header>
      {tab === "sources" && <SourcesScreen project={project} deck={deck} onDeckChange={setDeck} />}
    </main>
  );
}
```

`frontend/src/App.tsx`의 프로젝트 분기 교체:

```tsx
import { useState } from "react";
import type { ProjectInfo } from "./api/client";
import { ProjectList } from "./screens/ProjectList";
import { ProjectView } from "./screens/ProjectView";

export function App() {
  const [current, setCurrent] = useState<ProjectInfo | null>(null);
  if (current === null) return <ProjectList onOpen={setCurrent} />;
  return <ProjectView project={current} onBack={() => setCurrent(null)} />;
}
```

- [ ] **Step 5: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 프로젝트 화면 골격과 자료, 보고 정보 입력"
```

---

### Task 10: 구조안 생성과 승인 화면 (장별 순차 생성 포함)

> 2026-08-29 태스크 리뷰 정정: 승인 저장 성공 직후 setDraftGenerated(false)를 추가한다. 부분 실패 후 재승인이 성공분을 지우고 전량 재생성하는 결함(리뷰 발견)의 수리이며, 결정 15의 의도(재생성 승인의 전면 교체는 최초 승인에 한정)와 정합.

**Files:**
- Create: `frontend/src/screens/StructureScreen.tsx`, `frontend/src/editor/labels.ts`
- Modify: `frontend/src/screens/ProjectView.tsx` (구조안 탭 배선)
- Test: `frontend/src/screens/StructureScreen.test.tsx`

**Interfaces:**
- Consumes: `api.generateStructure/generateChapter/putDeck`, `StructureResult`, `ChapterResult`
- Produces: `<StructureScreen project deck onDeckChange onDone>`: 구조안 생성 → 표에서 수정(주제, 결론 한 줄, 템플릿, 순서, 추가, 삭제) → 승인 시 덱 반영(`snapshot=true`) 후 슬라이드 없는 장을 순차 생성(각 장 완료 즉시 `snapshot=false` 저장, 결정 15) → 전부 완료되면 `onDone()`. `TEMPLATE_LABELS` (Task 13, 14도 사용).

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/screens/StructureScreen.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck } from "../api/client";
import { StructureScreen } from "./StructureScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    generateStructure: vi.fn(), generateChapter: vi.fn(), putDeck: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

function emptyDeck(): Deck {
  return {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", preset_overrides: {} },
    structure: { chapters: [] },
    slides: [],
  };
}

const CH1 = { id: "c1", topic: "표지", conclusion: "", template: "cover" as const, source_refs: [] };
const CH2 = { id: "c2", topic: "본문", conclusion: "결론", template: "bullet_box" as const, source_refs: [] };

it("구조안을 생성해 초안 표를 보여준다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    raw_text: "", unverified_numbers: ["9999"], format_retried: false,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  expect(await screen.findByDisplayValue("본문")).toBeInTheDocument();
  expect(screen.getByText(/9999/)).toBeInTheDocument();  // 자료에 없는 수치 경고
});

it("승인하면 덱 반영 후 장별로 순차 생성해 저장한다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter)
    .mockResolvedValueOnce({ status: "ok", raw_text: "", warnings: [], unverified_numbers: [],
      format_retried: false, condensed: false,
      slots: { template: "cover", title: "제목", subtitle: "", date: "", audience: "" } })
    .mockResolvedValueOnce({ status: "ok", raw_text: "", warnings: [], unverified_numbers: [],
      format_retried: false, condensed: false,
      slots: { template: "bullet_box", bullets: [{ text: "가", level: 0 }], conclusion: "결", footnote: "" } });
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  // 승인 저장 1회(snapshot true) + 장 반영 2회(snapshot false)
  const calls = vi.mocked(api.putDeck).mock.calls;
  expect(calls[0][2]).toBe(true);
  expect(calls.length).toBe(3);
  expect(calls[2][1].slides).toHaveLength(2);
});

it("형식 오류면 원문과 재시도 경로를 보여준다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "format_error", structure: null, raw_text: "이상한 응답",
    unverified_numbers: [], format_retried: true,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText("이상한 응답")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "다시 생성" })).toBeInTheDocument();
});

it("기존 슬라이드가 사라지는 승인은 확인을 거친다", async () => {
  // 장 2개 중 슬라이드가 있는 c2만 삭제한다: 초안에 CH1이 남아 승인 버튼이 유지되고,
  // c2 슬라이드의 소실로 확인 대화가 뜬다 (마지막 장을 삭제하면 승인 절 자체가 사라지므로 부적합)
  const deck = emptyDeck();
  deck.structure.chapters = [CH1, CH2];
  deck.slides = [{ chapter_id: "c2", slots: {
    template: "bullet_box", bullets: [], conclusion: "결", footnote: "" } }];
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByLabelText("본문 삭제"));
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  expect(confirmSpy).toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();  // 취소했으므로 반영 없음
  confirmSpy.mockRestore();
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 2: 구현**

`frontend/src/editor/labels.ts`:

```ts
import type { TemplateName } from "../api/client";

export const TEMPLATE_LABELS: Record<TemplateName, string> = {
  cover: "표지",
  summary: "핵심 요약",
  bullet_box: "불릿 + 강조박스",
  table: "표 중심",
  compare2: "2단 비교",
  divider: "간지",
};
```

`frontend/src/screens/StructureScreen.tsx`:

```tsx
import { useState } from "react";
import {
  api, messageOf,
  type Chapter, type ChapterResult, type Deck, type ProjectInfo, type TemplateName,
} from "../api/client";
import { TEMPLATE_LABELS } from "../editor/labels";

type Progress = Record<string, "대기" | "생성 중" | "완료" | "실패">;

function nextChapterId(chapters: Chapter[]): string {
  const max = chapters
    .map((c) => /^c(\d+)$/.exec(c.id))
    .reduce((n, m) => (m ? Math.max(n, Number(m[1])) : n), 0);
  return `c${max + 1}`;
}

export function StructureScreen({ project, deck, onDeckChange, onDone }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onDone: () => void;
}) {
  const [draft, setDraft] = useState<Chapter[]>(deck.structure.chapters);
  const [draftGenerated, setDraftGenerated] = useState(false);  // AI 재생성 초안 여부 (결정 15: 승인 시 전면 교체)
  const [targetChapters, setTargetChapters] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [rawText, setRawText] = useState("");
  const [numbers, setNumbers] = useState<string[]>([]);
  const [progress, setProgress] = useState<Progress>({});

  const generate = async () => {
    setBusy(true);
    setError("");
    setRawText("");
    try {
      const n = targetChapters.trim() === "" ? undefined : Number(targetChapters);
      const result = await api.generateStructure(project.name, {
        target_chapters: n, instructions,
      });
      if (result.status === "format_error") {
        setError("AI 응답을 형식에 맞게 읽지 못했습니다. 원문을 확인하고 다시 생성해 주세요.");
        setRawText(result.raw_text);
      } else if (result.structure) {
        setDraft(result.structure.chapters);
        setDraftGenerated(true);
        setNumbers(result.unverified_numbers);
      }
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };

  const update = (i: number, patch: Partial<Chapter>) => {
    setDraft(draft.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  };
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= draft.length) return;
    const next = [...draft];
    [next[i], next[j]] = [next[j], next[i]];
    setDraft(next);
  };
  const remove = (i: number) => setDraft(draft.filter((_, j) => j !== i));
  const add = () => {
    setDraft([...draft, {
      id: nextChapterId(draft), topic: "새 장", conclusion: "",
      template: "bullet_box", source_refs: [],
    }]);
  };

  const approve = async () => {
    // AI 재생성 초안은 장 id가 재부여되어 옛 슬라이드와의 대응이 보장되지 않으므로 전면 교체한다 (결정 15).
    // 기존 구조안을 손으로 고친 경우에만 id와 템플릿이 일치하는 슬라이드를 계승한다
    const draftById = new Map(draft.map((c) => [c.id, c]));
    const kept = draftGenerated ? [] : deck.slides.filter((s) => {
      const ch = draftById.get(s.chapter_id);
      return ch !== undefined && ch.template === s.slots.template;
    });
    const droppedCount = deck.slides.length - kept.length;
    if (droppedCount > 0) {
      const ok = window.confirm(
        draftGenerated
          ? `새 구조안을 승인하면 기존 장 내용 ${droppedCount}개를 지우고 전부 새로 생성합니다. 계속할까요?`
          : `구조안 변경으로 기존 장 내용 ${droppedCount}개가 사라집니다. 계속할까요?`,
      );
      if (!ok) return;
    }
    setBusy(true);
    setError("");
    try {
      let current: Deck = { ...deck, structure: { chapters: draft }, slides: kept };
      await api.putDeck(project.name, current, true);  // 승인 반영: 직전 상태가 스냅샷으로 남는다
      onDeckChange(current);
      setDraftGenerated(false);  // 승인이 반영된 순간부터는 재승인이 성공분을 계승한다 (실패한 장만 재생성)
      const targets = draft.filter((c) => !current.slides.some((s) => s.chapter_id === c.id));
      setProgress(Object.fromEntries(targets.map((c) => [c.id, "대기"])));
      let failed = false;
      for (const chapter of targets) {
        setProgress((p) => ({ ...p, [chapter.id]: "생성 중" }));
        let result: ChapterResult;
        try {
          result = await api.generateChapter(project.name, chapter.id);
        } catch (e) {
          setError(messageOf(e));
          setProgress((p) => ({ ...p, [chapter.id]: "실패" }));
          failed = true;
          continue;
        }
        if (result.status !== "ok" || !result.slots) {
          setError("일부 장의 AI 응답을 형식에 맞게 읽지 못했습니다. 실패한 장만 다시 시도해 주세요.");
          setRawText(result.raw_text);
          setProgress((p) => ({ ...p, [chapter.id]: "실패" }));
          failed = true;
          continue;
        }
        current = { ...current, slides: [...current.slides, { chapter_id: chapter.id, slots: result.slots }] };
        await api.putDeck(project.name, current, false);
        onDeckChange(current);
        setNumbers((n) => [...new Set([...n, ...result.unverified_numbers])]);
        setProgress((p) => ({ ...p, [chapter.id]: "완료" }));
      }
      if (!failed) onDone();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="structure-screen">
      {error && <p role="alert">{error}</p>}
      {rawText && <details><summary>AI 응답 원문</summary><pre>{rawText}</pre></details>}
      {numbers.length > 0 && (
        <p className="number-warning">자료에서 찾지 못한 수치가 있습니다: {numbers.join(", ")}. 반영 전에 확인해 주세요.</p>
      )}
      <section>
        <h2>구조안</h2>
        <label>목표 장수 (비우면 AI가 정함)
          <input aria-label="목표 장수" type="number" min={1} value={targetChapters}
            onChange={(e) => setTargetChapters(e.target.value)} />
        </label>
        <label>지시사항
          <textarea aria-label="지시사항" value={instructions}
            onChange={(e) => setInstructions(e.target.value)} />
        </label>
        <button onClick={generate} disabled={busy}>
          {draft.length > 0 || rawText ? "다시 생성" : "구조안 생성"}
        </button>
        {draft.length === 0 && !busy && <span> 자료를 먼저 넣고 눌러 주세요.</span>}
        {busy && <span> 진행 중입니다. 잠시 기다려 주세요...</span>}
      </section>
      {draft.length > 0 && (
        <section>
          <h2>장 구성</h2>
          <table>
            <thead>
              <tr><th>순서</th><th>주제</th><th>결론 한 줄</th><th>템플릿</th><th></th></tr>
            </thead>
            <tbody>
              {draft.map((c, i) => (
                <tr key={c.id}>
                  <td>
                    <button aria-label={`${c.topic} 위로`} onClick={() => move(i, -1)}>위</button>
                    <button aria-label={`${c.topic} 아래로`} onClick={() => move(i, 1)}>아래</button>
                  </td>
                  <td><input aria-label={`${i + 1}번 장 주제`} value={c.topic}
                    onChange={(e) => update(i, { topic: e.target.value })} /></td>
                  <td><input aria-label={`${i + 1}번 장 결론`} value={c.conclusion ?? ""}
                    onChange={(e) => update(i, { conclusion: e.target.value })} /></td>
                  <td>
                    <select aria-label={`${i + 1}번 장 템플릿`} value={c.template}
                      onChange={(e) => update(i, { template: e.target.value as TemplateName })}>
                      {Object.entries(TEMPLATE_LABELS).map(([v, label]) => (
                        <option key={v} value={v}>{label}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button aria-label={`${c.topic} 삭제`} onClick={() => remove(i)}>삭제</button>
                    {progress[c.id] && <span> {progress[c.id]}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={add}>장 추가</button>
          <button onClick={approve} disabled={busy || draft.length === 0}>승인하고 내용 생성</button>
        </section>
      )}
    </div>
  );
}
```

`frontend/src/screens/ProjectView.tsx` 배선: import에 `StructureScreen` 추가, 구조안 버튼의 `disabled`를 제거하고 `onClick={() => setTab("structure")}`, 본문에 아래 추가:

```tsx
      {tab === "structure" && (
        <StructureScreen project={project} deck={deck} onDeckChange={setDeck}
          onDone={() => setTab("editor")} />
      )}
```

주의: 이 시점에는 편집 탭 내용이 아직 없으므로, `onDone`이 편집 탭으로 전환해도 빈 본문이 나온다(Task 12가 채운다). 탭 전환 자체는 동작해야 한다.

- [ ] **Step 3: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 구조안 생성과 승인 화면, 장별 순차 생성"
```

---

### Task 11: 미리보기 렌더러 (렌더 계획을 그대로 그리는 순수 컴포넌트)

**Files:**
- Create: `frontend/src/editor/Preview.tsx`
- Test: `frontend/src/editor/Preview.test.tsx`

**Interfaces:**
- Consumes: `SlidePlan`, `Frame`, `Para.lines`, `TablePlan.header_lines/cell_lines`, `RenderStyle` (Task 1, 7의 타입)
- Produces: `<Preview slide style pageW pageH selected onSelect onCommitText />`, `FrameRef = { chapterId, slot }`, `TextRef = FrameRef & { index?, row?, col? }`. 좌표와 글자 크기는 계획 수치를 px로 그대로 쓰고 transform scale로 맞춘다(결정 6). 텍스트는 `Para.lines`를 줄 div로 그린다(브라우저 줄바꿈 사용 금지: `white-space: pre`). 선택된 프레임의 문단(또는 표 칸)을 클릭하면 입력 상자가 열리고, blur/Enter 확정 시 `onCommitText(ref, text)`를 부른다(결정 8). Task 12의 EditorScreen이 이 계약만 소비한다.

**동작 규칙 (구현 기준):**
- 프레임 div: `position: absolute; left x; top y; width w; height h` (px = pt 수치 그대로), fill이 있으면 배경색, border가 있으면 `border_width_pt`px 실선, 채움이나 테두리가 있으면 `box_padding_pt` 안쪽 여백(box-sizing: border-box), `valign`이 middle이면 세로 중앙(flex)
- 문단: 줄마다 div (`font-size: font_pt`px, `line-height: line_spacing` 배수, 색 `#{color}`, 정렬 align). 불릿 문단은 `padding-left: bullet_indent_pt * (level + 1)`px과 첫 줄 앞 표식(`bullet_char`), 두 번째 이후 불릿 문단은 `margin-top: bullet_gap_pt`px
- 표: `row_heights_pt`와 `col_widths_pt`대로 행과 칸을 그린다. 머리글은 굵게 + `header_fill` 배경, 칸 텍스트는 `header_lines`/`cell_lines`의 줄들. 칸 사이 경계선 색은 화면 전용 상수(#D0D7E2)를 쓴다(렌더 계획에 표 경계색이 없어서 화면 장식으로만 취급, PPTX와의 시각 일치 대상 아님)
- 경고 표시: `slide.warnings`의 slot과 프레임 slot이 같거나 `slot + "_"`로 시작하면 프레임에 `warned` 클래스(빨간 외곽선). 예: `left_card_heading` 경고는 `left_card` 프레임에 붙는다
- `page_number` 프레임은 클릭 대상이 아니다. 문단 클릭의 TextRef는: 카드 프레임(left_card, right_card)은 index 0 = 소제목, 1부터 = 불릿(index - 1). 표 칸은 row -1 = 머리글. 그 외 단일 텍스트 슬롯은 index 0
- 배율: 컨테이너 폭 / pageW. 컨테이너 폭을 잴 수 없으면(테스트 환경) 1

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/editor/Preview.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SlidePlan } from "../api/client";
import { Preview } from "./Preview";

const style = {
  korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020",
  box_padding_pt: 10, line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6,
  table_cell_pad_x_pt: 6, table_cell_pad_y_pt: 3, border_width_pt: 0.75,
  bullet_char: "•", bullet_font: "Arial",
};

const slide: SlidePlan = {
  chapter_id: "c1",
  template: "bullet_box",
  warnings: [{ chapter_id: "c1", slot: "bullets", message: "넘침", needed_pt: 400, available_pt: 300 }],
  frames: [
    { name: "c1:title", x: 50, y: 36, w: 860, h: 40, fill: null, border: null, valign: "top", table: null,
      paras: [{ text: "장 제목", level: 0, font_pt: 20, bold: true, color: "202020",
        align: "left", bullet: false, lines: ["장 제목"] }] },
    { name: "c1:bullets", x: 50, y: 92, w: 860, h: 300, fill: null, border: null, valign: "top", table: null,
      paras: [{ text: "첫 불릿 문장", level: 0, font_pt: 12, bold: false, color: "202020",
        align: "left", bullet: true, lines: ["첫 불릿", "문장"] }] },
    { name: "c1:page_number", x: 850, y: 512, w: 60, h: 16, fill: null, border: null, valign: "top", table: null,
      paras: [{ text: "1", level: 0, font_pt: 9, bold: false, color: "202020",
        align: "right", bullet: false, lines: ["1"] }] },
  ],
};

it("엔진의 줄바꿈 결과를 줄 단위로 그린다", () => {
  render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);
  expect(screen.getByText("첫 불릿")).toBeInTheDocument();
  expect(screen.getByText("문장")).toBeInTheDocument();  // 한 문단이 두 줄 div
});

it("경고가 있는 프레임에 warned 표시를 붙인다", () => {
  const { container } = render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={() => {}} onCommitText={() => {}} />);
  const bullets = container.querySelector('[data-frame="c1:bullets"]');
  expect(bullets).toHaveClass("warned");
  expect(container.querySelector('[data-frame="c1:title"]')).not.toHaveClass("warned");
});

it("프레임 클릭이 선택을 알린다", async () => {
  const onSelect = vi.fn();
  render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={null} onSelect={onSelect} onCommitText={() => {}} />);
  await userEvent.click(screen.getByText("장 제목"));
  expect(onSelect).toHaveBeenCalledWith({ chapterId: "c1", slot: "title" });
});

it("선택된 프레임의 문단을 클릭하면 입력이 열리고 확정 시 반영된다", async () => {
  const onCommitText = vi.fn();
  render(<Preview slide={slide} style={style} pageW={960} pageH={540}
    selected={{ chapterId: "c1", slot: "title" }} onSelect={() => {}} onCommitText={onCommitText} />);
  await userEvent.click(screen.getByText("장 제목"));
  const box = await screen.findByLabelText("내용 수정");
  expect(box).toHaveValue("장 제목");
  await userEvent.clear(box);
  await userEvent.type(box, "새 제목{Enter}");
  expect(onCommitText).toHaveBeenCalledWith({ chapterId: "c1", slot: "title", index: 0 }, "새 제목");
});

it("표 칸을 편집하면 행과 열이 담긴 참조로 반영된다", async () => {
  const tableSlide: SlidePlan = {
    chapter_id: "c1", template: "table", warnings: [],
    frames: [{ name: "c1:table", x: 50, y: 92, w: 860, h: 400, fill: null, border: null,
      valign: "top", paras: [],
      table: {
        col_widths_pt: [200, 660], header: ["구분", "내용"], rows: [["A", "값"]],
        font_pt: 12, header_fill: "F2F2F2", row_heights_pt: [22.8, 22.8],
        header_lines: [["구분"], ["내용"]], cell_lines: [[["A"], ["값"]]],
      } }],
  };
  const onCommitText = vi.fn();
  render(<Preview slide={tableSlide} style={style} pageW={960} pageH={540}
    selected={{ chapterId: "c1", slot: "table" }} onSelect={() => {}} onCommitText={onCommitText} />);
  await userEvent.click(screen.getByText("값"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "새 값{Enter}");
  expect(onCommitText).toHaveBeenCalledWith(
    { chapterId: "c1", slot: "table", row: 0, col: 1 }, "새 값");
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 2: 구현**

`frontend/src/editor/Preview.tsx`:

```tsx
import { useLayoutEffect, useRef, useState } from "react";
import type { Frame, Para, SlidePlan, RenderPlan } from "../api/client";

export type FrameRef = { chapterId: string; slot: string };
export type TextRef = FrameRef & { index?: number; row?: number; col?: number };
type Style = RenderPlan["style"];

const TABLE_LINE = "#D0D7E2";  // 화면 전용 경계선 (렌더 계획에 표 경계색 없음)

function frameRef(f: Frame): FrameRef {
  const [chapterId, slot] = f.name.split(":");
  return { chapterId, slot };
}

function isWarned(slide: SlidePlan, slot: string): boolean {
  return slide.warnings.some((w) => w.slot === slot || w.slot.startsWith(`${slot}_`));
}

export function Preview({ slide, style, pageW, pageH, selected, onSelect, onCommitText }: {
  slide: SlidePlan;
  style: Style;
  pageW: number;
  pageH: number;
  selected: FrameRef | null;
  onSelect: (ref: FrameRef | null) => void;
  onCommitText: (ref: TextRef, text: string) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [editing, setEditing] = useState<{ ref: TextRef; text: string } | null>(null);

  useLayoutEffect(() => {
    const measure = () => {
      const w = holder.current?.clientWidth ?? 0;
      setScale(w > 0 ? w / pageW : 1);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [pageW]);

  const commit = () => {
    if (editing) onCommitText(editing.ref, editing.text);
    setEditing(null);
  };

  const startEdit = (ref: TextRef, text: string) => {
    const frame = { chapterId: ref.chapterId, slot: ref.slot };
    if (selected?.chapterId === frame.chapterId && selected.slot === frame.slot) {
      setEditing({ ref, text });
    } else {
      onSelect(frame);
    }
  };

  const renderPara = (f: Frame, p: Para, i: number) => {
    const indent = p.bullet ? style.bullet_indent_pt * (p.level + 1) : 0;
    const ref: TextRef = { ...frameRef(f), index: i };
    return (
      <div key={i} className="para"
        style={{
          fontSize: p.font_pt, lineHeight: String(style.line_spacing),
          fontWeight: p.bold ? 700 : 400, color: `#${p.color}`, textAlign: p.align,
          paddingLeft: indent, position: "relative",
          marginTop: p.bullet && i > 0 ? style.bullet_gap_pt : 0,
        }}
        onClick={(e) => {
          e.stopPropagation();
          if (f.name.endsWith(":page_number")) return;
          startEdit(ref, p.text);
        }}
      >
        {p.bullet && (
          <span aria-hidden style={{ position: "absolute", left: indent - style.bullet_indent_pt }}>
            {style.bullet_char}
          </span>
        )}
        {p.lines.map((line, j) => (
          <div key={j} style={{ whiteSpace: "pre" }}>{line || " "}</div>
        ))}
      </div>
    );
  };

  const renderTable = (f: Frame) => {
    const t = f.table;
    if (!t) return null;
    const base = frameRef(f);
    const renderRow = (cells: string[][], texts: string[], rowIdx: number, bold: boolean) => (
      <div key={rowIdx} style={{
        display: "flex", height: t.row_heights_pt[rowIdx + 1] ?? t.row_heights_pt[0],
        background: rowIdx === -1 ? `#${t.header_fill}` : undefined,
        fontWeight: bold ? 700 : 400,
      }}>
        {cells.map((lines, col) => (
          <div key={col} style={{
            width: t.col_widths_pt[col], boxSizing: "border-box",
            padding: `${style.table_cell_pad_y_pt}px ${style.table_cell_pad_x_pt}px`,
            border: `0.5px solid ${TABLE_LINE}`, fontSize: t.font_pt,
            lineHeight: String(style.line_spacing), overflow: "hidden",
          }}
            onClick={(e) => {
              e.stopPropagation();
              startEdit({ ...base, row: rowIdx, col }, texts[col]);
            }}
          >
            {lines.map((line, j) => <div key={j} style={{ whiteSpace: "pre" }}>{line || " "}</div>)}
          </div>
        ))}
      </div>
    );
    return (
      <div>
        {renderRow(t.header_lines, t.header, -1, true)}
        {t.cell_lines.map((rowLines, r) => renderRow(rowLines, t.rows[r], r, false))}
      </div>
    );
  };

  return (
    <div ref={holder} className="preview-holder">
      <div className="preview-canvas"
        style={{
          width: pageW, height: pageH, position: "relative", background: "#ffffff",
          transform: `scale(${scale})`, transformOrigin: "top left",
          fontFamily: `"${style.korean_font}", sans-serif`,
        }}
        onClick={() => { setEditing(null); onSelect(null); }}
      >
        {slide.frames.map((f) => {
          const ref = frameRef(f);
          const boxed = f.fill != null || f.border != null;
          const isSelected = selected?.chapterId === ref.chapterId && selected.slot === ref.slot;
          return (
            <div key={f.name} data-frame={f.name}
              className={[
                "frame",
                isWarned(slide, ref.slot) ? "warned" : "",
                isSelected ? "selected" : "",
              ].join(" ").trim()}
              style={{
                position: "absolute", left: f.x, top: f.y, width: f.w, height: f.h,
                boxSizing: "border-box",
                background: f.fill ? `#${f.fill}` : undefined,
                border: f.border ? `${style.border_width_pt}px solid #${f.border}` : undefined,
                padding: boxed ? style.box_padding_pt : 0,
                display: f.valign === "middle" ? "flex" : undefined,
                flexDirection: f.valign === "middle" ? "column" : undefined,
                justifyContent: f.valign === "middle" ? "center" : undefined,
              }}
              onClick={(e) => {
                e.stopPropagation();
                if (!f.name.endsWith(":page_number")) onSelect(ref);
              }}
            >
              {f.table ? renderTable(f) : f.paras.map((p, i) => renderPara(f, p, i))}
            </div>
          );
        })}
        {editing && (
          <textarea autoFocus aria-label="내용 수정" className="inline-editor"
            value={editing.text}
            onChange={(e) => setEditing({ ...editing, text: e.target.value })}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); commit(); }
              if (e.key === "Escape") setEditing(null);
            }}
          />
        )}
      </div>
    </div>
  );
}
```

표 행 높이 규칙: 머리글이 `row_heights_pt[0]`, 본문 r행이 `row_heights_pt[r + 1]`이다. renderRow의 `t.row_heights_pt[rowIdx + 1]`은 머리글 호출(rowIdx = -1)에서 자연히 `[0]`이 되므로 fallback `?? t.row_heights_pt[0]`은 제거해도 된다.

`frontend/src/styles.css`에 추가:

```css
.preview-holder { width: 100%; overflow: hidden; }
.frame.selected { outline: 2px solid #1F4E79; }
.frame.warned { outline: 2px solid #B00020; }
.frame.selected.warned { outline: 2px dashed #B00020; }
.inline-editor { position: absolute; left: 10%; top: 40%; width: 80%; min-height: 60px; font: inherit; }
```

- [ ] **Step 3: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 미리보기 렌더러 (렌더 계획 절대 배치, 클릭 선택과 인라인 수정)"
```

---

### Task 12: 편집 상태 저장소 (언두, 자동 저장, 실측)와 편집기 조립

**Files:**
- Create: `frontend/src/state/deckStore.ts`, `frontend/src/state/useDeckEditor.ts`
- Create: `frontend/src/editor/slotOps.ts`, `frontend/src/editor/ChapterList.tsx`
- Create: `frontend/src/screens/EditorScreen.tsx`
- Modify: `frontend/src/screens/ProjectView.tsx` (편집 탭 배선)
- Test: `frontend/src/state/deckStore.test.ts`, `frontend/src/editor/slotOps.test.ts`, `frontend/src/screens/EditorScreen.test.tsx`

**Interfaces:**
- Consumes: `api.measure/putDeck` (Task 2, 4), `<Preview>` (Task 11)
- Produces: `editorReducer(state, action)` (past/present/future, 상한 100), `useDeckEditor(projectName, initialDeck, onDeckChange, timings?) -> { deck, plan, saveState, error, canUndo, canRedo, apply, replace, undo, redo, flushSave }` (apply = 편집 반영, replace = AI 반영처럼 다음 저장을 스냅샷으로, flushSave = 보류 중 자동 저장의 즉시 실행. 언마운트 시 자동 플러시 내장, saveState에 "저장 대기" 포함), `applyTextEdit(deck, ref, text)` (모든 인라인 텍스트 수정의 단일 경로. 표 칸은 개행을 공백으로 치환해 스키마 금지와 정합), `<ChapterList>`, `<EditorScreen onEditorReady?>` (마운트 시 flushSave를 부모에 등록: Task 16의 내보내기가 쓴다). Task 13~16이 `apply`/`replace`만 부른다(직접 putDeck 금지).

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/state/deckStore.test.ts`:

```ts
import type { Deck } from "../api/client";
import { editorReducer, type EditorState } from "./deckStore";

function deck(title: string): Deck {
  return {
    schema_version: 1,
    meta: { title, report_type: "research", audience: "", preset_overrides: {} },
    structure: { chapters: [] },
    slides: [],
  };
}

const init = (d: Deck): EditorState => ({ past: [], present: d, future: [] });

it("편집은 과거를 쌓고 미래를 비운다", () => {
  let s = init(deck("a"));
  s = editorReducer(s, { type: "edit", deck: deck("b") });
  s = editorReducer(s, { type: "undo" });
  expect(s.present.meta.title).toBe("a");
  s = editorReducer(s, { type: "edit", deck: deck("c") });
  expect(s.future).toHaveLength(0);
});

it("undo와 redo가 왕복한다", () => {
  let s = init(deck("a"));
  s = editorReducer(s, { type: "edit", deck: deck("b") });
  s = editorReducer(s, { type: "undo" });
  s = editorReducer(s, { type: "redo" });
  expect(s.present.meta.title).toBe("b");
});

it("과거는 100개로 제한된다", () => {
  let s = init(deck("0"));
  for (let i = 1; i <= 150; i += 1) s = editorReducer(s, { type: "edit", deck: deck(String(i)) });
  expect(s.past).toHaveLength(100);
});
```

`frontend/src/editor/slotOps.test.ts`:

```ts
import type { Deck } from "../api/client";
import { applyTextEdit } from "./slotOps";

function bulletDeck(): Deck {
  return {
    schema_version: 1,
    meta: { title: "t", report_type: "research", audience: "", preset_overrides: {} },
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "bullet_box",
      bullets: [{ text: "하나", level: 0 }, { text: "둘", level: 1 }],
      conclusion: "결론", footnote: "" } }],
  };
}

it("title 수정은 구조안의 topic을 고친다", () => {
  const next = applyTextEdit(bulletDeck(), { chapterId: "c1", slot: "title", index: 0 }, "새 주제");
  expect(next.structure.chapters[0].topic).toBe("새 주제");
});

it("불릿 문단은 index로 고친다", () => {
  const next = applyTextEdit(bulletDeck(), { chapterId: "c1", slot: "bullets", index: 1 }, "고침");
  const slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[1].text).toBe("고침");
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("하나");
});

it("표 칸은 row와 col로, 머리글은 row -1로 고친다", () => {
  const deck: Deck = {
    ...bulletDeck(),
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "table", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "table", columns: ["구분", "내용"], rows: [["A", "값"]], footnote: "" } }],
  };
  let next = applyTextEdit(deck, { chapterId: "c1", slot: "table", row: 0, col: 1 }, "새 값");
  let slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.rows[0][1]).toBe("새 값");
  next = applyTextEdit(deck, { chapterId: "c1", slot: "table", row: -1, col: 0 }, "새 머리글");
  slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.columns[0]).toBe("새 머리글");
  // 붙여넣기로 섞인 개행은 공백으로 흡수한다 (표 칸 개행 금지 검증과 정합)
  next = applyTextEdit(deck, { chapterId: "c1", slot: "table", row: 0, col: 1 }, "줄1\n줄2");
  slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.rows[0][1]).toBe("줄1 줄2");
});

it("카드의 index 0은 소제목, 이후는 불릿이다", () => {
  const deck: Deck = {
    ...bulletDeck(),
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "compare2", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "compare2", conclusion: "결",
      left: { heading: "왼쪽", bullets: [{ text: "가", level: 0 }] },
      right: { heading: "오른쪽", bullets: [] } } }],
  };
  let next = applyTextEdit(deck, { chapterId: "c1", slot: "left_card", index: 0 }, "새 소제목");
  let slots = next.slides[0].slots;
  expect(slots.template === "compare2" && slots.left.heading).toBe("새 소제목");
  next = applyTextEdit(deck, { chapterId: "c1", slot: "left_card", index: 1 }, "새 불릿");
  slots = next.slides[0].slots;
  expect(slots.template === "compare2" && slots.left.bullets?.[0].text).toBe("새 불릿");
});
```

`frontend/src/screens/EditorScreen.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck, type RenderPlan } from "../api/client";
import { EditorScreen } from "./EditorScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [{ text: "하나", level: 0 }], conclusion: "결론", footnote: "" } }],
};

const plan: RenderPlan = {
  page_width_pt: 960, page_height_pt: 540,
  style: {
    korean_font: "Noto Sans KR", latin_font: "Noto Sans KR", text_color: "202020",
    box_padding_pt: 10, line_spacing: 1.4, bullet_indent_pt: 18, bullet_gap_pt: 6,
    table_cell_pad_x_pt: 6, table_cell_pad_y_pt: 3, border_width_pt: 0.75,
    bullet_char: "•", bullet_font: "Arial",
  },
  slides: [{ chapter_id: "c1", template: "bullet_box", warnings: [], frames: [
    { name: "c1:bullets", x: 50, y: 92, w: 860, h: 300, fill: null, border: null,
      valign: "top", table: null,
      paras: [{ text: "하나", level: 0, font_pt: 12, bold: false, color: "202020",
        align: "left", bullet: true, lines: ["하나"] }] },
  ] }],
};

it("실측을 불러 미리보기를 그리고, 편집을 자동 저장한다 (첫 저장은 스냅샷)", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}}
    timings={{ measureMs: 0, saveMs: 0 }} />);
  expect(await screen.findByText("하나")).toBeInTheDocument();
  // 선택 후 같은 문단을 다시 클릭해 인라인 수정
  await userEvent.click(screen.getByText("하나"));
  await userEvent.click(screen.getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "고침{Enter}");
  await waitFor(() => expect(api.putDeck).toHaveBeenCalled());
  const [, savedDeck, snapshot] = vi.mocked(api.putDeck).mock.calls[0];
  const slots = savedDeck.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("고침");
  expect(snapshot).toBe(true);  // 편집 세션 첫 저장 (결정 1)
});

it("Ctrl+Z가 직전 편집을 되돌린다", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  render(<EditorScreen project={project} deck={deck} onDeckChange={() => {}}
    timings={{ measureMs: 0, saveMs: 0 }} />);
  await screen.findByText("하나");
  await userEvent.click(screen.getByText("하나"));
  await userEvent.click(screen.getByText("하나"));
  const box = await screen.findByLabelText("내용 수정");
  await userEvent.clear(box);
  await userEvent.type(box, "고침{Enter}");
  await userEvent.keyboard("{Control>}z{/Control}");
  await waitFor(() => {
    const calls = vi.mocked(api.putDeck).mock.calls;
    const last = calls[calls.length - 1][1];
    const slots = last.slides[0].slots;
    expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("하나");
  });
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 2: 구현**

`frontend/src/state/deckStore.ts`:

```ts
import type { Deck } from "../api/client";

export type EditorState = { past: Deck[]; present: Deck; future: Deck[] };
export type EditorAction =
  | { type: "edit"; deck: Deck }
  | { type: "undo" }
  | { type: "redo" };

const LIMIT = 100;

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "edit": {
      if (action.deck === state.present) return state;
      return {
        past: [...state.past.slice(-(LIMIT - 1)), state.present],
        present: action.deck,
        future: [],
      };
    }
    case "undo": {
      if (state.past.length === 0) return state;
      return {
        past: state.past.slice(0, -1),
        present: state.past[state.past.length - 1],
        future: [state.present, ...state.future],
      };
    }
    case "redo": {
      if (state.future.length === 0) return state;
      return {
        past: [...state.past, state.present],
        present: state.future[0],
        future: state.future.slice(1),
      };
    }
  }
}
```

`frontend/src/state/useDeckEditor.ts`:

```ts
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, messageOf, type Deck, type RenderPlan } from "../api/client";
import { editorReducer } from "./deckStore";

export type SaveState = "저장됨" | "저장 대기" | "저장 중" | "저장 실패";
export type Timings = { measureMs: number; saveMs: number };

const DEFAULT_TIMINGS: Timings = { measureMs: 300, saveMs: 1200 };  // 결정 1, 2

export function useDeckEditor(
  projectName: string,
  initialDeck: Deck,
  onDeckChange: (d: Deck) => void,
  timings: Timings = DEFAULT_TIMINGS,
) {
  const [state, dispatch] = useReducer(editorReducer, {
    past: [], present: initialDeck, future: [],
  });
  const [plan, setPlan] = useState<RenderPlan | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("저장됨");
  const [error, setError] = useState("");
  const firstSave = useRef(true);      // 편집 세션 첫 저장은 스냅샷 (결정 1)
  const snapshotNext = useRef(false);  // AI 반영 등 의미 시점의 다음 저장
  const savedDeck = useRef(initialDeck);
  const deck = state.present;
  const deckRef = useRef(deck);
  deckRef.current = deck;

  const saveNow = useCallback(async (target: Deck) => {
    const snapshot = firstSave.current || snapshotNext.current;
    setSaveState("저장 중");
    try {
      await api.putDeck(projectName, target, snapshot);
      firstSave.current = false;
      snapshotNext.current = false;
      savedDeck.current = target;
      setSaveState("저장됨");
      setError("");
      onDeckChange(target);
    } catch (e) {
      setSaveState("저장 실패");
      setError(messageOf(e));
    }
  }, [projectName, onDeckChange]);

  // 실측: 디바운스 (결정 2)
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      api.measure(deck)
        .then((p) => { if (!cancelled) setPlan(p); })
        .catch((e) => { if (!cancelled) setError(messageOf(e)); });
    }, timings.measureMs);
    return () => { cancelled = true; clearTimeout(t); };
  }, [deck, timings.measureMs]);

  // 자동 저장: 디바운스 (결정 1). 대기 중임을 표시해 "저장됨" 오표시를 막는다
  useEffect(() => {
    if (deck === savedDeck.current) return;
    setSaveState("저장 대기");
    const t = setTimeout(() => { void saveNow(deck); }, timings.saveMs);
    return () => clearTimeout(t);
  }, [deck, saveNow, timings.saveMs]);

  // 플러시: 보류 중 저장을 즉시 실행한다 (결정 1. 내보내기 직전에 부모가 부른다)
  const flushSave = useCallback(async () => {
    if (deckRef.current !== savedDeck.current) await saveNow(deckRef.current);
  }, [saveNow]);

  // 언마운트 플러시: 탭 전환이나 목록 복귀로 화면이 내려가도 마지막 편집을 잃지 않는다 (결정 1)
  useEffect(() => () => {
    if (deckRef.current !== savedDeck.current) void saveNow(deckRef.current);
  }, [saveNow]);

  const apply = useCallback((edit: (d: Deck) => Deck) => {
    dispatch({ type: "edit", deck: edit(deckRef.current) });
  }, []);

  const replace = useCallback((next: Deck) => {
    snapshotNext.current = true;
    dispatch({ type: "edit", deck: next });
  }, []);

  const undo = useCallback(() => dispatch({ type: "undo" }), []);
  const redo = useCallback(() => dispatch({ type: "redo" }), []);

  return {
    deck, plan, saveState, error,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    apply, replace, undo, redo, flushSave,
  };
}
```

`frontend/src/editor/slotOps.ts` (이 태스크에서는 `applyTextEdit`만, 구조 조작은 Task 13):

```ts
import type { Deck, Slots } from "../api/client";
import type { TextRef } from "./Preview";

function updateSlide(deck: Deck, chapterId: string, f: (s: Slots) => Slots): Deck {
  return {
    ...deck,
    slides: deck.slides.map((s) => (s.chapter_id === chapterId ? { ...s, slots: f(s.slots) } : s)),
  };
}

export function applyTextEdit(deck: Deck, ref: TextRef, text: string): Deck {
  const { chapterId, slot } = ref;
  if (slot === "title") {
    return {
      ...deck,
      structure: {
        chapters: deck.structure.chapters.map((c) =>
          c.id === chapterId ? { ...c, topic: text } : c),
      },
    };
  }
  return updateSlide(deck, chapterId, (slots) => {
    switch (slots.template) {
      case "cover":
        if (slot === "cover_title") return { ...slots, title: text };
        if (slot === "subtitle") return { ...slots, subtitle: text };
        if (slot === "date") return { ...slots, date: text };
        if (slot === "audience") return { ...slots, audience: text };
        return slots;
      case "divider":
        if (slot === "section_no") return { ...slots, section_no: text };
        if (slot === "section_title") return { ...slots, section_title: text };
        return slots;
      case "summary":
        if (slot === "conclusion") return { ...slots, conclusion: text };
        if (slot === "points") {
          return { ...slots, points: (slots.points ?? []).map((b, i) =>
            i === ref.index ? { ...b, text } : b) };
        }
        return slots;
      case "bullet_box":
        if (slot === "conclusion") return { ...slots, conclusion: text };
        if (slot === "footnote") return { ...slots, footnote: text };
        if (slot === "bullets") {
          return { ...slots, bullets: (slots.bullets ?? []).map((b, i) =>
            i === ref.index ? { ...b, text } : b) };
        }
        return slots;
      case "table": {
        if (slot === "footnote") return { ...slots, footnote: text };
        if (slot === "table") {
          // 표 칸 개행은 덱 검증이 거부한다: 붙여넣기로 섞인 개행을 공백으로 흡수한다 (단계 3 결정 8과 정합)
          const cell = text.replace(/[\r\n]+/g, " ");
          if (ref.row === -1) {
            return { ...slots, columns: slots.columns.map((c, j) => (j === ref.col ? cell : c)) };
          }
          return { ...slots, rows: slots.rows.map((r, i) =>
            i === ref.row ? r.map((c, j) => (j === ref.col ? cell : c)) : r) };
        }
        return slots;
      }
      case "compare2": {
        if (slot === "conclusion") return { ...slots, conclusion: text };
        const editCard = (card: (typeof slots)["left"]) =>
          (ref.index ?? 0) === 0
            ? { ...card, heading: text }
            : { ...card, bullets: (card.bullets ?? []).map((b, i) =>
                i === (ref.index ?? 0) - 1 ? { ...b, text } : b) };
        if (slot === "left_card") return { ...slots, left: editCard(slots.left) };
        if (slot === "right_card") return { ...slots, right: editCard(slots.right) };
        return slots;
      }
    }
    return slots;
  });
}
```

`frontend/src/editor/ChapterList.tsx` (드래그 배선은 Task 13):

```tsx
import type { Deck, RenderPlan } from "../api/client";
import { TEMPLATE_LABELS } from "./labels";

export function ChapterList({ deck, plan, selected, onSelect }: {
  deck: Deck;
  plan: RenderPlan | null;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const warned = new Set(
    (plan?.slides ?? []).filter((s) => s.warnings.length > 0).map((s) => s.chapter_id));
  const generated = new Set(deck.slides.map((s) => s.chapter_id));
  return (
    <ul className="chapter-list">
      {deck.structure.chapters.map((c, i) => (
        <li key={c.id}>
          <button aria-pressed={selected === c.id} onClick={() => onSelect(c.id)}>
            {i + 1}. {c.topic} <small>{TEMPLATE_LABELS[c.template]}</small>
            {!generated.has(c.id) && <em> 내용 없음</em>}
            {warned.has(c.id) && <strong className="warn-badge"> 분량 주의</strong>}
          </button>
        </li>
      ))}
    </ul>
  );
}
```

`frontend/src/screens/EditorScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import type { Deck, ProjectInfo } from "../api/client";
import { ChapterList } from "../editor/ChapterList";
import { Preview, type FrameRef, type TextRef } from "../editor/Preview";
import { applyTextEdit } from "../editor/slotOps";
import { useDeckEditor, type Timings } from "../state/useDeckEditor";

export function EditorScreen({ project, deck: initialDeck, onDeckChange, onEditorReady, timings }: {
  project: ProjectInfo;
  deck: Deck;
  onDeckChange: (d: Deck) => void;
  onEditorReady?: (flush: () => Promise<void>) => void;  // 부모(ProjectView)가 내보내기 전에 플러시하도록
  timings?: Timings;
}) {
  const editor = useDeckEditor(project.name, initialDeck, onDeckChange, timings);
  const chapters = editor.deck.structure.chapters;
  const [chapterId, setChapterId] = useState<string | null>(chapters[0]?.id ?? null);
  const [selected, setSelected] = useState<FrameRef | null>(null);

  useEffect(() => {
    onEditorReady?.(editor.flushSave);
  }, [onEditorReady, editor.flushSave]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) { e.preventDefault(); editor.undo(); }
      if (key === "y" || (key === "z" && e.shiftKey)) { e.preventDefault(); editor.redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editor.undo, editor.redo]);

  const slide = editor.plan?.slides.find((s) => s.chapter_id === chapterId) ?? null;
  const commitText = (ref: TextRef, text: string) =>
    editor.apply((d) => applyTextEdit(d, ref, text));

  return (
    <div className="editor-screen">
      <aside className="editor-left">
        <ChapterList deck={editor.deck} plan={editor.plan} selected={chapterId}
          onSelect={(id) => { setChapterId(id); setSelected(null); }} />
      </aside>
      <section className="editor-center">
        {editor.error && <p role="alert">{editor.error}</p>}
        {slide && editor.plan ? (
          // 2026-08-29 태스크 11 리뷰 이월: 장 전환 시 편집창 잔존 방지 리마운트
          <Preview key={slide.chapter_id} slide={slide} style={editor.plan.style}
            pageW={editor.plan.page_width_pt} pageH={editor.plan.page_height_pt}
            selected={selected} onSelect={setSelected} onCommitText={commitText} />
        ) : (
          <p>이 장은 아직 내용이 없습니다. 구조안 탭에서 생성해 주세요.</p>
        )}
      </section>
      <aside className="editor-right">
        <p>저장 상태: {editor.saveState}</p>
        <button onClick={editor.undo} disabled={!editor.canUndo}>되돌리기 (Ctrl+Z)</button>
        <button onClick={editor.redo} disabled={!editor.canRedo}>다시 실행</button>
        {slide && slide.warnings.length > 0 && (
          <section>
            <h3>분량 경고</h3>
            <ul>{slide.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
          </section>
        )}
      </aside>
    </div>
  );
}
```

`frontend/src/screens/ProjectView.tsx` 배선: import에 `EditorScreen` 추가, 편집 버튼에 `onClick={() => setTab("editor")}` 추가(게이트 `disabled={!hasSlides}` 유지), 본문에 추가:

```tsx
      {tab === "editor" && hasSlides && (
        <EditorScreen project={project} deck={deck} onDeckChange={setDeck} />
      )}
```

`frontend/src/styles.css`에 추가:

```css
.editor-screen { display: grid; grid-template-columns: 220px 1fr 280px; gap: 12px; }
.warn-badge { color: #B00020; }
```

- [ ] **Step 3: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 편집 상태 저장소와 편집기 조립 (언두, 자동 저장, 인라인 수정)"
```

---

### Task 13: 속성 패널의 구조 조작과 장 순서 드래그

**Files:**
- Modify: `frontend/src/editor/slotOps.ts` (구조 조작 함수 추가)
- Create: `frontend/src/editor/PropertyPanel.tsx`
- Modify: `frontend/src/editor/ChapterList.tsx` (드래그), `frontend/src/screens/EditorScreen.tsx` (패널 배선)
- Test: `frontend/src/editor/slotOps.test.ts`, `frontend/src/editor/PropertyPanel.test.tsx`, `frontend/src/editor/ChapterList.test.tsx`

**Interfaces:**
- Consumes: `applyTextEdit`, `editor.apply`, `TEMPLATE_LABELS`
- Produces: 순수 함수 `addBullet(deck, chapterId, slot)`, `removeBullet(deck, chapterId, slot, index)` (slot은 "bullets" | "points" | "left_card" | "right_card"), `deleteTableRow(deck, chapterId, rowIndex)`, `mergeTableColumns(deck, chapterId, colIndex)` (colIndex와 오른쪽 열을 공백 결합), `reorderChapters(deck, from, to)`. `<PropertyPanel deck chapterId onApply />` (topic 수정과 위 조작 버튼). ChapterList가 HTML5 드래그로 `onReorder(from, to)`를 부른다. Task 14~15가 이 패널에 절을 추가한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/editor/slotOps.test.ts`에 추가:

```ts
import {
  addBullet, deleteTableRow, mergeTableColumns, removeBullet, reorderChapters,
} from "./slotOps";

it("불릿 추가와 삭제", () => {
  let next = addBullet(bulletDeck(), "c1", "bullets");
  let slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets).toHaveLength(3);
  next = removeBullet(next, "c1", "bullets", 0);
  slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("둘");
});

it("표 행 삭제와 열 병합", () => {
  const deck: Deck = {
    ...bulletDeck(),
    structure: { chapters: [
      { id: "c1", topic: "주제", conclusion: "", template: "table", source_refs: [] }] },
    slides: [{ chapter_id: "c1", slots: {
      template: "table", columns: ["구분", "내용", "비고"],
      rows: [["A", "값1", "메모1"], ["B", "값2", "메모2"]], footnote: "" } }],
  };
  let next = deleteTableRow(deck, "c1", 0);
  let slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.rows).toEqual([["B", "값2", "메모2"]]);
  next = mergeTableColumns(deck, "c1", 1);  // "내용"과 "비고" 병합
  slots = next.slides[0].slots;
  expect(slots.template === "table" && slots.columns).toEqual(["구분", "내용 비고"]);
  expect(slots.template === "table" && slots.rows[0]).toEqual(["A", "값1 메모1"]);
});

it("장 순서 이동", () => {
  const deck = bulletDeck();
  deck.structure.chapters = [
    { id: "c1", topic: "가", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c2", topic: "나", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c3", topic: "다", conclusion: "", template: "bullet_box", source_refs: [] },
  ];
  const next = reorderChapters(deck, 0, 2);
  expect(next.structure.chapters.map((c) => c.topic)).toEqual(["나", "다", "가"]);
});
```

`frontend/src/editor/PropertyPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Deck } from "../api/client";
import { PropertyPanel } from "./PropertyPanel";

const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [{ text: "하나", level: 0 }], conclusion: "결론", footnote: "" } }],
};

it("장 주제를 고치면 onApply로 반영된다", async () => {
  const onApply = vi.fn();
  render(<PropertyPanel deck={deck} chapterId="c1" onApply={onApply} />);
  const input = screen.getByLabelText("장 주제");
  await userEvent.clear(input);
  await userEvent.type(input, "새 주제");
  await userEvent.tab();  // blur 확정
  expect(onApply).toHaveBeenCalled();
  const edit = onApply.mock.calls[0][0] as (d: Deck) => Deck;
  expect(edit(deck).structure.chapters[0].topic).toBe("새 주제");
});

it("불릿 추가 버튼이 동작한다", async () => {
  const onApply = vi.fn();
  render(<PropertyPanel deck={deck} chapterId="c1" onApply={onApply} />);
  await userEvent.click(screen.getByText("불릿 추가"));
  const edit = onApply.mock.calls[0][0] as (d: Deck) => Deck;
  const slots = edit(deck).slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets).toHaveLength(2);
});
```

`frontend/src/editor/ChapterList.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import type { Deck } from "../api/client";
import { ChapterList } from "./ChapterList";

const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "가", conclusion: "", template: "bullet_box", source_refs: [] },
    { id: "c2", topic: "나", conclusion: "", template: "bullet_box", source_refs: [] },
  ] },
  slides: [],
};

it("드래그로 순서를 바꾼다", () => {
  const onReorder = vi.fn();
  render(<ChapterList deck={deck} plan={null} selected={null}
    onSelect={() => {}} onReorder={onReorder} />);
  const items = screen.getAllByRole("listitem");
  fireEvent.dragStart(items[0]);
  fireEvent.dragOver(items[1]);
  fireEvent.drop(items[1]);
  expect(onReorder).toHaveBeenCalledWith(0, 1);
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 2: 구현**

`frontend/src/editor/slotOps.ts`에 추가:

```ts
type BulletSlot = "bullets" | "points" | "left_card" | "right_card";

export function addBullet(deck: Deck, chapterId: string, slot: BulletSlot): Deck {
  return updateSlide(deck, chapterId, (slots) => {
    const item = { text: "새 항목", level: 0 as const };
    if (slots.template === "bullet_box" && slot === "bullets") {
      return { ...slots, bullets: [...(slots.bullets ?? []), item] };
    }
    if (slots.template === "summary" && slot === "points") {
      return { ...slots, points: [...(slots.points ?? []), item] };
    }
    if (slots.template === "compare2" && (slot === "left_card" || slot === "right_card")) {
      const key = slot === "left_card" ? "left" : "right";
      const card = slots[key];
      return { ...slots, [key]: { ...card, bullets: [...(card.bullets ?? []), item] } };
    }
    return slots;
  });
}

export function removeBullet(deck: Deck, chapterId: string, slot: BulletSlot, index: number): Deck {
  return updateSlide(deck, chapterId, (slots) => {
    if (slots.template === "bullet_box" && slot === "bullets") {
      return { ...slots, bullets: (slots.bullets ?? []).filter((_, i) => i !== index) };
    }
    if (slots.template === "summary" && slot === "points") {
      return { ...slots, points: (slots.points ?? []).filter((_, i) => i !== index) };
    }
    if (slots.template === "compare2" && (slot === "left_card" || slot === "right_card")) {
      const key = slot === "left_card" ? "left" : "right";
      const card = slots[key];
      return { ...slots, [key]: { ...card, bullets: (card.bullets ?? []).filter((_, i) => i !== index) } };
    }
    return slots;
  });
}

export function deleteTableRow(deck: Deck, chapterId: string, rowIndex: number): Deck {
  return updateSlide(deck, chapterId, (slots) =>
    slots.template === "table"
      ? { ...slots, rows: slots.rows.filter((_, i) => i !== rowIndex) }
      : slots);
}

export function mergeTableColumns(deck: Deck, chapterId: string, colIndex: number): Deck {
  return updateSlide(deck, chapterId, (slots) => {
    if (slots.template !== "table" || colIndex < 0 || colIndex >= slots.columns.length - 1) {
      return slots;
    }
    const join = (a: string, b: string) => [a, b].filter(Boolean).join(" ");
    return {
      ...slots,
      columns: slots.columns.flatMap((c, j) =>
        j === colIndex ? [join(c, slots.columns[j + 1])] : j === colIndex + 1 ? [] : [c]),
      rows: slots.rows.map((r) => r.flatMap((c, j) =>
        j === colIndex ? [join(c, r[j + 1])] : j === colIndex + 1 ? [] : [c])),
    };
  });
}

export function reorderChapters(deck: Deck, from: number, to: number): Deck {
  const chapters = [...deck.structure.chapters];
  const [moved] = chapters.splice(from, 1);
  chapters.splice(to, 0, moved);
  return { ...deck, structure: { chapters } };
}
```

`frontend/src/editor/PropertyPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import type { Deck } from "../api/client";
import { TEMPLATE_LABELS } from "./labels";
import {
  addBullet, applyTextEdit, deleteTableRow, mergeTableColumns, removeBullet,
} from "./slotOps";

export function PropertyPanel({ deck, chapterId, onApply }: {
  deck: Deck;
  chapterId: string;
  onApply: (edit: (d: Deck) => Deck) => void;
}) {
  const chapter = deck.structure.chapters.find((c) => c.id === chapterId);
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const [topic, setTopic] = useState(chapter?.topic ?? "");
  useEffect(() => setTopic(chapter?.topic ?? ""), [chapterId, chapter?.topic]);
  if (!chapter) return null;
  const slots = slide?.slots;

  const commitTopic = () => {
    if (topic !== chapter.topic) {
      onApply((d) => applyTextEdit(d, { chapterId, slot: "title", index: 0 }, topic));
    }
  };

  const bulletSection = (label: string, slot: "bullets" | "points" | "left_card" | "right_card",
    items: { text: string }[]) => (
    <section key={slot}>
      <h4>{label}</h4>
      <ul>
        {items.map((b, i) => (
          <li key={i}>
            <span>{b.text}</span>
            <button aria-label={`${label} ${i + 1} 삭제`}
              onClick={() => onApply((d) => removeBullet(d, chapterId, slot, i))}>삭제</button>
          </li>
        ))}
      </ul>
      <button onClick={() => onApply((d) => addBullet(d, chapterId, slot))}>
        {slot === "bullets" || slot === "points" ? "불릿 추가" : `${label} 불릿 추가`}
      </button>
    </section>
  );

  return (
    <div className="property-panel">
      <h3>{TEMPLATE_LABELS[chapter.template]}</h3>
      <label>장 주제
        <input aria-label="장 주제" value={topic}
          onChange={(e) => setTopic(e.target.value)} onBlur={commitTopic} />
      </label>
      {slots?.template === "bullet_box" && bulletSection("본문 불릿", "bullets", slots.bullets ?? [])}
      {slots?.template === "summary" && bulletSection("요점", "points", slots.points ?? [])}
      {slots?.template === "compare2" && (
        <>
          {bulletSection("왼쪽 카드", "left_card", slots.left.bullets ?? [])}
          {bulletSection("오른쪽 카드", "right_card", slots.right.bullets ?? [])}
        </>
      )}
      {slots?.template === "table" && (
        <section>
          <h4>표 조작</h4>
          <ul>
            {slots.rows.map((r, i) => (
              <li key={i}>
                <span>{r.join(" | ")}</span>
                <button aria-label={`${i + 1}번 행 삭제`}
                  onClick={() => onApply((d) => deleteTableRow(d, chapterId, i))}>행 삭제</button>
              </li>
            ))}
          </ul>
          {slots.columns.slice(0, -1).map((c, i) => (
            <button key={i}
              onClick={() => onApply((d) => mergeTableColumns(d, chapterId, i))}>
              {c} + {slots.columns[i + 1]} 열 병합
            </button>
          ))}
        </section>
      )}
      <p className="hint">텍스트 내용은 가운데 미리보기에서 클릭해 직접 고칠 수 있습니다.</p>
    </div>
  );
}
```

`frontend/src/editor/ChapterList.tsx`에 드래그 추가 (props에 `onReorder?: (from: number, to: number) => void`):

```tsx
import { useRef } from "react";
```

li를 다음으로 교체:

```tsx
        <li key={c.id} draggable={onReorder !== undefined}
          onDragStart={() => { dragFrom.current = i; }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => {
            if (dragFrom.current !== null && dragFrom.current !== i) {
              onReorder?.(dragFrom.current, i);
            }
            dragFrom.current = null;
          }}
        >
```

컴포넌트 상단에 `const dragFrom = useRef<number | null>(null);` 추가.

`frontend/src/screens/EditorScreen.tsx` 배선:

- import에 `PropertyPanel`, `reorderChapters` 추가
- ChapterList에 `onReorder={(from, to) => editor.apply((d) => reorderChapters(d, from, to))}` 전달
- 오른쪽 aside의 저장 상태 아래에 추가:

```tsx
        {chapterId && (
          <PropertyPanel deck={editor.deck} chapterId={chapterId} onApply={editor.apply} />
        )}
```

- [ ] **Step 3: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 속성 패널 구조 조작과 장 순서 드래그 (설계서 6.1)"
```

---

### Task 14: 템플릿 교체와 디자인 값 조정 (덱 덮어쓰기)

**Files:**
- Create: `frontend/src/editor/templateSwitch.ts`, `frontend/src/editor/DesignPanel.tsx`
- Modify: `frontend/src/editor/slotOps.ts` (setPresetOverride), `frontend/src/editor/PropertyPanel.tsx` (템플릿 선택), `frontend/src/screens/EditorScreen.tsx` (디자인 패널 배선)
- Test: `frontend/src/editor/templateSwitch.test.ts`, `frontend/src/editor/DesignPanel.test.tsx`

**Interfaces:**
- Consumes: `Slots` 6종, `api.getPreset`, `editor.apply`
- Produces: `switchTemplate(slots, to) -> { slots, dropped: string[] }` (호환 슬롯 자동 이사, 소실 목록은 사람이 읽는 이름), `applyTemplateSwitch(deck, chapterId, to) -> { deck, dropped }` (chapter.template과 슬롯을 함께 교체), `setPresetOverride(deck, group, key, value)` (deck.meta.preset_overrides에 깊은 병합용 값 기록), `<DesignPanel deck onApply />`. 매핑 규칙은 결정 10을 따른다.

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/editor/templateSwitch.test.ts`:

```ts
import type { Slots } from "../api/client";
import { switchTemplate } from "./templateSwitch";

const bulletSlots: Slots = {
  template: "bullet_box",
  bullets: [{ text: "가", level: 0 }, { text: "나", level: 0 }],
  conclusion: "결론", footnote: "주석",
};

it("bullet_box에서 summary로: 불릿과 결론은 이사, 각주는 소실 목록", () => {
  const r = switchTemplate(bulletSlots, "summary");
  expect(r.slots.template === "summary" && r.slots.points).toHaveLength(2);
  expect(r.slots.template === "summary" && r.slots.conclusion).toBe("결론");
  expect(r.dropped.join(" ")).toContain("각주");
});

it("bullet_box에서 compare2로: 불릿은 왼쪽 카드로", () => {
  const r = switchTemplate(bulletSlots, "compare2");
  expect(r.slots.template === "compare2" && r.slots.left.bullets).toHaveLength(2);
  expect(r.slots.template === "compare2" && r.slots.right.bullets).toHaveLength(0);
});

it("compare2에서 bullet_box로: 두 카드 불릿을 합치고 소제목은 소실 목록", () => {
  const compare: Slots = {
    template: "compare2", conclusion: "결",
    left: { heading: "옵션 A", bullets: [{ text: "가", level: 0 }] },
    right: { heading: "옵션 B", bullets: [{ text: "나", level: 0 }] },
  };
  const r = switchTemplate(compare, "bullet_box");
  expect(r.slots.template === "bullet_box" && r.slots.bullets?.map((b) => b.text)).toEqual(["가", "나"]);
  expect(r.dropped.join(" ")).toContain("옵션 A");
  expect(r.dropped.join(" ")).toContain("옵션 B");
});

it("table로 바꾸면 불릿과 결론이 소실 목록에 오르고 빈 표가 생긴다", () => {
  const r = switchTemplate(bulletSlots, "table");
  expect(r.slots.template === "table" && r.slots.columns.length).toBeGreaterThan(0);
  expect(r.dropped.join(" ")).toContain("불릿");
  expect(r.dropped.join(" ")).toContain("결론");
  expect(r.slots.template === "table" && r.slots.footnote).toBe("주석");  // 각주는 table로 이사
});

it("같은 템플릿이면 그대로다", () => {
  const r = switchTemplate(bulletSlots, "bullet_box");
  expect(r.slots).toBe(bulletSlots);
  expect(r.dropped).toEqual([]);
});
```

`frontend/src/editor/DesignPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck, type Preset } from "../api/client";
import { DesignPanel } from "./DesignPanel";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getPreset: vi.fn() } };
});

const preset = {
  fonts: { korean: "Noto Sans KR", latin: "Noto Sans KR" },
  font_roles: { cover_title_pt: 28, section_title_pt: 24, title_pt: 20, subtitle_pt: 14,
    body_pt: 12, box_pt: 12, table_pt: 12, footnote_pt: 9, page_number_pt: 9 },
  colors: { text: "202020", accent: "1F4E79", box_fill: "EEF3F9",
    table_header_fill: "F2F2F2", border: "D0D7E2", background: "FFFFFF" },
  spacing: {}, bullet_marker: { char: "•", font: "Arial" },
  page_width_pt: 960, page_height_pt: 540, language: "ko-KR",
} as unknown as Preset;

const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [] }, slides: [],
};

it("본문 크기를 고치면 덮어쓰기로 기록된다", async () => {
  vi.mocked(api.getPreset).mockResolvedValue(preset);
  const onApply = vi.fn();
  render(<DesignPanel deck={deck} onApply={onApply} />);
  const input = await screen.findByLabelText("본문 크기(pt)");
  expect(input).toHaveValue(12);
  await userEvent.clear(input);
  await userEvent.type(input, "13");
  await userEvent.tab();
  const edit = onApply.mock.calls[0][0] as (d: Deck) => Deck;
  const next = edit(deck);
  expect((next.meta.preset_overrides as Record<string, Record<string, number>>).font_roles.body_pt).toBe(13);
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 2: 구현**

`frontend/src/editor/templateSwitch.ts`:

```ts
import type { Bullet, Deck, Slots, TemplateName } from "../api/client";

type Currency = {
  conclusion?: string;
  bullets: Bullet[];  // 생성 타입 그대로 쓴다: level이 필수 필드라 손으로 만든 유사 타입은 tsc가 거부한다
  footnote?: string;
  dropped: string[];  // 어느 템플릿으로 가든 옮길 수 없는 원본 내용
};

function collect(slots: Slots): Currency {
  switch (slots.template) {
    case "bullet_box":
      return { conclusion: slots.conclusion, bullets: slots.bullets ?? [],
        footnote: slots.footnote || undefined, dropped: [] };
    case "summary":
      return { conclusion: slots.conclusion, bullets: slots.points ?? [], dropped: [] };
    case "compare2": {
      const dropped: string[] = [];
      if (slots.left.heading) dropped.push(`왼쪽 카드 소제목 "${slots.left.heading}"`);
      if (slots.right.heading) dropped.push(`오른쪽 카드 소제목 "${slots.right.heading}"`);
      return { conclusion: slots.conclusion,
        bullets: [...(slots.left.bullets ?? []), ...(slots.right.bullets ?? [])], dropped };
    }
    case "table":
      return { bullets: [], footnote: slots.footnote || undefined, dropped: ["표 내용 전체"] };
    case "cover":
      return { bullets: [], dropped: ["표지 내용 전체"] };
    case "divider":
      return { bullets: [], dropped: ["간지 내용 전체"] };
  }
}

export function switchTemplate(slots: Slots, to: TemplateName): { slots: Slots; dropped: string[] } {
  if (slots.template === to) return { slots, dropped: [] };
  const c = collect(slots);
  const dropped = [...c.dropped];
  const conclusion = c.conclusion ?? "";
  const footnote = c.footnote ?? "";
  const dropBullets = () => { if (c.bullets.length > 0) dropped.push(`불릿 ${c.bullets.length}개`); };
  const dropConclusion = () => { if (conclusion) dropped.push(`결론 "${conclusion}"`); };
  const dropFootnote = () => { if (footnote) dropped.push(`각주 "${footnote}"`); };
  switch (to) {
    case "bullet_box":
      return { slots: { template: "bullet_box", bullets: c.bullets, conclusion, footnote }, dropped };
    case "summary":
      dropFootnote();
      return { slots: { template: "summary", conclusion, points: c.bullets }, dropped };
    case "compare2":
      dropFootnote();
      return { slots: { template: "compare2", conclusion,
        left: { heading: "", bullets: c.bullets }, right: { heading: "", bullets: [] } }, dropped };
    case "table":
      dropBullets();
      dropConclusion();
      return { slots: { template: "table", columns: ["구분", "내용"], rows: [["", ""]], footnote }, dropped };
    case "cover":
      dropBullets(); dropConclusion(); dropFootnote();
      return { slots: { template: "cover", title: "", subtitle: "", date: "", audience: "" }, dropped };
    case "divider":
      dropBullets(); dropConclusion(); dropFootnote();
      return { slots: { template: "divider", section_no: "", section_title: "" }, dropped };
  }
}

export function applyTemplateSwitch(deck: Deck, chapterId: string, to: TemplateName):
  { deck: Deck; dropped: string[] } {
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);
  const result = slide ? switchTemplate(slide.slots, to) : null;
  const next: Deck = {
    ...deck,
    structure: { chapters: deck.structure.chapters.map((ch) =>
      ch.id === chapterId ? { ...ch, template: to } : ch) },
    slides: result
      ? deck.slides.map((s) => (s.chapter_id === chapterId ? { ...s, slots: result.slots } : s))
      : deck.slides,
  };
  return { deck: next, dropped: result?.dropped ?? [] };
}
```

`frontend/src/editor/slotOps.ts`에 추가:

```ts
export function setPresetOverride(
  deck: Deck, group: string, key: string, value: number | string,
): Deck {
  const overrides = { ...(deck.meta.preset_overrides ?? {}) } as Record<string, unknown>;
  const groupValues = { ...((overrides[group] as Record<string, unknown>) ?? {}) };
  groupValues[key] = value;
  overrides[group] = groupValues;
  return { ...deck, meta: { ...deck.meta, preset_overrides: overrides } };
}
```

`frontend/src/editor/DesignPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api, messageOf, type Deck, type Preset } from "../api/client";
import { setPresetOverride } from "./slotOps";

const FONT_FIELDS = [
  ["title_pt", "제목 크기(pt)", 12],
  ["body_pt", "본문 크기(pt)", 12],
  ["box_pt", "강조 박스 크기(pt)", 12],
  ["footnote_pt", "각주 크기(pt)", 9],
] as const;
const COLOR_FIELDS = [
  ["text", "본문 색"], ["accent", "강조 색"], ["box_fill", "강조 박스 배경"],
] as const;

function overrideOf(deck: Deck, group: string, key: string): number | string | undefined {
  const groups = deck.meta.preset_overrides as Record<string, Record<string, number | string>> | undefined;
  return groups?.[group]?.[key];
}

export function DesignPanel({ deck, onApply }: {
  deck: Deck;
  onApply: (edit: (d: Deck) => Deck) => void;
}) {
  const [preset, setPreset] = useState<Preset | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.getPreset().then(setPreset).catch((e) => setError(messageOf(e)));
  }, []);
  if (error) return <p role="alert">{error}</p>;
  if (preset === null) return <p>디자인 값을 불러오는 중...</p>;

  const fontValue = (key: string) =>
    Number(overrideOf(deck, "font_roles", key)
      ?? (preset.font_roles as unknown as Record<string, number>)[key]);
  const colorValue = (key: string) =>
    String(overrideOf(deck, "colors", key)
      ?? (preset.colors as unknown as Record<string, string>)[key]);

  return (
    <details className="design-panel">
      <summary>디자인 값 (이 덱에만 적용)</summary>
      {FONT_FIELDS.map(([key, label, min]) => (
        <label key={key}>{label}
          <input aria-label={label} type="number" min={min} step={0.5}
            defaultValue={fontValue(key)}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v) && v >= min && v !== fontValue(key)) {
                onApply((d) => setPresetOverride(d, "font_roles", key, v));
              }
            }} />
        </label>
      ))}
      {COLOR_FIELDS.map(([key, label]) => (
        <label key={key}>{label}
          <input aria-label={label} type="color" defaultValue={`#${colorValue(key)}`}
            onBlur={(e) => {
              // 색 선택기는 드래그 중 change를 연사한다: 확정(blur) 시점에만 반영해 언두와 저장을 지킨다
              const hex = e.target.value.replace("#", "").toUpperCase();
              if (hex !== colorValue(key).toUpperCase()) {
                onApply((d) => setPresetOverride(d, "colors", key, hex));
              }
            }} />
        </label>
      ))}
      <p className="hint">글자 크기 하한(본문 12pt, 각주 9pt)보다 작게는 저장되지 않습니다. 프리셋 자체에 저장하는 기능은 다음 단계에서 제공합니다.</p>
    </details>
  );
}
```

`frontend/src/editor/PropertyPanel.tsx`에 템플릿 교체 추가: import에 `applyTemplateSwitch`와 `type TemplateName` 추가, "장 주제" label 아래에 삽입:

```tsx
      <label>템플릿
        <select aria-label="템플릿" value={chapter.template}
          onChange={(e) => {
            const to = e.target.value as TemplateName;
            const result = applyTemplateSwitch(deck, chapterId, to);
            if (result.dropped.length > 0) {
              const ok = window.confirm(
                `다음 내용은 새 템플릿에 자리가 없어 사라집니다:\n- ${result.dropped.join("\n- ")}\n계속할까요?`,
              );
              if (!ok) return;
            }
            onApply((d) => applyTemplateSwitch(d, chapterId, to).deck);
          }}>
          {Object.entries(TEMPLATE_LABELS).map(([v, label]) => (
            <option key={v} value={v}>{label}</option>
          ))}
        </select>
      </label>
```

`frontend/src/screens/EditorScreen.tsx`의 오른쪽 aside에서 PropertyPanel 아래에 추가:

```tsx
        <DesignPanel deck={editor.deck} onApply={editor.apply} />
```

주의: EditorScreen이 이제 DesignPanel을 그리므로, `EditorScreen.test.tsx`의 모의 목록에 `getPreset: vi.fn()`을 추가하고 각 테스트에서 `vi.mocked(api.getPreset).mockResolvedValue(...)`를 준다 (Task 14의 DesignPanel.test.tsx가 쓰는 preset 픽스처를 재사용).

- [ ] **Step 3: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 템플릿 교체(호환 이사와 소실 확인)와 디자인 값 조정"
```

---

### Task 15: AI 재생성과 축약 (결과 확인 패널)

**Files:**
- Create: `frontend/src/editor/GeneratePanel.tsx`
- Modify: `frontend/src/screens/EditorScreen.tsx` (배선)
- Test: `frontend/src/editor/GeneratePanel.test.tsx`

**Interfaces:**
- Consumes: `api.generateChapter/condenseChapter`, `ChapterResult`, `editor.replace` (다음 저장을 스냅샷으로 만드는 반영 경로, Task 12)
- Produces: `<GeneratePanel project deck chapterId onReplace />`. 재생성(지시문 입력 가능)과 축약(현재 슬롯 동봉) 버튼, 결과 확인 패널([반영]/[버리기], 분량 경고와 수치 경고와 condensed/format_retried 표시, format_error의 원문과 재시도), 호출 중 잠금과 진행 안내 (결정 11, 13).

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/editor/GeneratePanel.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type ChapterResult, type Deck } from "../api/client";
import { GeneratePanel } from "./GeneratePanel";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, generateChapter: vi.fn(), condenseChapter: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [{ text: "옛 내용", level: 0 }], conclusion: "결", footnote: "" } }],
};

const okResult: ChapterResult = {
  status: "ok", raw_text: "", warnings: [], unverified_numbers: ["8888"],
  format_retried: false, condensed: true,
  slots: { template: "bullet_box", bullets: [{ text: "새 내용", level: 0 }], conclusion: "결", footnote: "" },
};

it("재생성 결과를 보여주고 반영하면 onReplace에 새 슬롯이 담긴다", async () => {
  vi.mocked(api.generateChapter).mockResolvedValue(okResult);
  const onReplace = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={onReplace} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/8888/)).toBeInTheDocument();  // 수치 경고
  expect(screen.getByText(/축약했습니다/)).toBeInTheDocument();  // condensed 표시
  await userEvent.click(screen.getByText("반영"));
  const next = onReplace.mock.calls[0][0] as Deck;
  const slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("새 내용");
});

it("축약은 현재 슬롯을 동봉해 호출한다", async () => {
  vi.mocked(api.condenseChapter).mockResolvedValue(okResult);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  await waitFor(() => expect(api.condenseChapter).toHaveBeenCalled());
  const [, , sentSlots] = vi.mocked(api.condenseChapter).mock.calls[0];
  expect(sentSlots.template === "bullet_box" && sentSlots.bullets?.[0].text).toBe("옛 내용");
});

it("형식 오류는 원문과 재시도 경로를 보여주고 버리기 전까지 반영 버튼이 없다", async () => {
  vi.mocked(api.generateChapter).mockResolvedValue({
    status: "format_error", slots: null, raw_text: "이상한 원문",
    warnings: [], unverified_numbers: [], format_retried: true, condensed: false,
  });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText("이상한 원문")).toBeInTheDocument();
  expect(screen.queryByText("반영")).not.toBeInTheDocument();
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 2: 구현**

`frontend/src/editor/GeneratePanel.tsx`:

```tsx
import { useState } from "react";
import {
  api, messageOf, type ChapterResult, type Deck, type ProjectInfo,
} from "../api/client";

export function GeneratePanel({ project, deck, chapterId, onReplace }: {
  project: ProjectInfo;
  deck: Deck;
  chapterId: string;
  onReplace: (next: Deck) => void;
}) {
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ChapterResult | null>(null);
  const [error, setError] = useState("");
  const slide = deck.slides.find((s) => s.chapter_id === chapterId);

  const run = async (call: () => Promise<ChapterResult>) => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await call());
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };

  const regenerate = () => run(() => api.generateChapter(project.name, chapterId, instructions));
  const condense = () => {
    if (!slide) return;
    void run(() => api.condenseChapter(project.name, chapterId, slide.slots, instructions));
  };

  const applyResult = () => {
    if (!result || result.status !== "ok" || !result.slots) return;
    const slots = result.slots;
    const next: Deck = {
      ...deck,
      slides: deck.slides.some((s) => s.chapter_id === chapterId)
        ? deck.slides.map((s) => (s.chapter_id === chapterId ? { ...s, slots } : s))
        : [...deck.slides, { chapter_id: chapterId, slots }],
    };
    onReplace(next);  // 반영 저장은 스냅샷을 남긴다 (결정 1)
    setResult(null);
  };

  return (
    <section className="generate-panel">
      <h4>AI 다시 쓰기</h4>
      <label>지시사항 (선택)
        <textarea aria-label="재생성 지시사항" value={instructions}
          onChange={(e) => setInstructions(e.target.value)} />
      </label>
      <button onClick={regenerate} disabled={busy}>이 장 다시 생성</button>
      <button onClick={condense} disabled={busy || !slide}>이 장 축약</button>
      {busy && <p>생성 중입니다. 잠시 기다려 주세요 (최대 5분)...</p>}
      {error && <p role="alert">{error}</p>}
      {result && result.status === "format_error" && (
        <div role="alert">
          <p>AI 응답을 형식에 맞게 읽지 못했습니다. 원문을 확인하고 다시 시도해 주세요.</p>
          <details><summary>AI 응답 원문</summary><pre>{result.raw_text}</pre></details>
        </div>
      )}
      {result && result.status === "ok" && (
        <div className="generate-result">
          <p>새 초안이 준비되었습니다.
            {result.condensed && " 분량에 맞춰 축약했습니다."}
            {result.format_retried && " 형식 재시도 1회를 거쳤습니다."}
          </p>
          {result.warnings.length > 0 && (
            <ul>{result.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
          )}
          {result.unverified_numbers.length > 0 && (
            <p className="number-warning">
              자료에서 찾지 못한 수치: {result.unverified_numbers.join(", ")}. 반영 전에 확인해 주세요.
            </p>
          )}
          <button onClick={applyResult}>반영</button>
          <button onClick={() => setResult(null)}>버리기</button>
        </div>
      )}
    </section>
  );
}
```

`frontend/src/screens/EditorScreen.tsx` 배선: import에 `GeneratePanel` 추가, DesignPanel 아래에 추가:

```tsx
        {chapterId && (
          <GeneratePanel project={project} deck={editor.deck} chapterId={chapterId}
            onReplace={editor.replace} />
        )}
```

- [ ] **Step 3: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 장 단위 AI 재생성과 축약 (결과 확인 후 반영, 설계서 6.2)"
```

---

### Task 16: 내보내기와 스냅샷 복구 화면

**Files:**
- Create: `frontend/src/screens/RecoveryScreen.tsx`
- Modify: `frontend/src/screens/ProjectView.tsx` (내보내기 버튼, 복구 진입)
- Test: `frontend/src/screens/RecoveryScreen.test.tsx`, `frontend/src/screens/ProjectView.test.tsx`

**Interfaces:**
- Consumes: `api.createSnapshot/exportDeck/listSnapshots/restoreSnapshot`, `ProjectInfo.status` (Task 4, 5)
- Produces: 내보내기 버튼(슬라이드가 있을 때만): 스냅샷을 먼저 남기고(결정 1의 ④) 내보낸 뒤 파일 경로를 보여준다. `<RecoveryScreen project onBack />`: 스냅샷 목록에서 복원(확인 대화 포함). needs_recovery 프로젝트는 이 화면으로만 진입하고, 정상 프로젝트도 머리글의 "스냅샷 복구"로 들어올 수 있다(설계서 7.2 복구 메뉴).

- [ ] **Step 1: 실패하는 테스트 작성**

`frontend/src/screens/RecoveryScreen.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { RecoveryScreen } from "./RecoveryScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, listSnapshots: vi.fn(), restoreSnapshot: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "needs_recovery" as const };

it("스냅샷 목록을 보여주고 확인 후 복원한다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00" }]);
  vi.mocked(api.restoreSnapshot).mockResolvedValue({} as never);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const onBack = vi.fn();
  render(<RecoveryScreen project={project} onBack={onBack} />);
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  expect(api.restoreSnapshot).toHaveBeenCalledWith("p1", "deck-20260829-100000-000001");
  expect(onBack).toHaveBeenCalled();
});

it("확인을 취소하면 복원하지 않는다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([
    { id: "deck-20260829-100000-000001", saved_at: "2026-08-29T10:00:00+09:00" }]);
  vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<RecoveryScreen project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("이 시점으로 복원"));
  expect(api.restoreSnapshot).not.toHaveBeenCalled();
});
```

`frontend/src/screens/ProjectView.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck } from "../api/client";
import { ProjectView } from "./ProjectView";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    getDeck: vi.fn(), listSources: vi.fn(), createSnapshot: vi.fn(), exportDeck: vi.fn(),
    measure: vi.fn(), putDeck: vi.fn(), listSnapshots: vi.fn(), restoreSnapshot: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

const deckWithSlide: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [], conclusion: "결", footnote: "" } }],
};

it("내보내기는 스냅샷을 먼저 남기고 경로를 보여준다", async () => {
  vi.mocked(api.getDeck).mockResolvedValue(deckWithSlide);
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.createSnapshot).mockResolvedValue({ ok: true });
  vi.mocked(api.exportDeck).mockResolvedValue({ path: "C:\\exports\\제목_v001.pptx" });
  render(<ProjectView project={project} onBack={() => {}} />);
  await userEvent.click(await screen.findByText("PPTX 내보내기"));
  await waitFor(() => expect(api.exportDeck).toHaveBeenCalledWith("p1"));
  expect(api.createSnapshot).toHaveBeenCalledWith("p1");  // 내보내기 직전 스냅샷 (결정 1)
  expect(await screen.findByText(/제목_v001\.pptx/)).toBeInTheDocument();
});

it("복구가 필요한 프로젝트는 복구 화면으로 진입한다", async () => {
  vi.mocked(api.listSnapshots).mockResolvedValue([]);
  render(<ProjectView project={{ ...project, status: "needs_recovery" }} onBack={() => {}} />);
  expect(await screen.findByText(/스냅샷 복구/)).toBeInTheDocument();
});
```

Run: `frontend` 폴더 안에서 `npm test` → FAIL

- [ ] **Step 2: 구현**

`frontend/src/screens/RecoveryScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api, messageOf, type ProjectInfo, type SnapshotInfo } from "../api/client";

export function RecoveryScreen({ project, onBack }: {
  project: ProjectInfo;
  onBack: () => void;
}) {
  const [snapshots, setSnapshots] = useState<SnapshotInfo[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listSnapshots(project.name)
      .then((list) => setSnapshots([...list].reverse()))  // 최신이 위로
      .catch((e) => setError(messageOf(e)));
  }, [project.name]);

  const restore = async (id: string) => {
    const ok = window.confirm(
      "이 시점으로 되돌립니다. 복원 직전 상태도 스냅샷으로 보존되므로 다시 되돌릴 수 있습니다. 계속할까요?",
    );
    if (!ok) return;
    try {
      await api.restoreSnapshot(project.name, id);
      onBack();  // 목록으로 돌아가면 상태가 새로 읽힌다
    } catch (e) {
      setError(messageOf(e));
    }
  };

  return (
    <div className="recovery-screen">
      <h2>스냅샷 복구</h2>
      <p>저장 시점 목록입니다. 복원하면 그 시점의 내용으로 돌아갑니다.</p>
      {error && <p role="alert">{error}</p>}
      {snapshots === null ? (
        <p>불러오는 중...</p>
      ) : snapshots.length === 0 ? (
        <p>되돌릴 수 있는 저장 시점이 없습니다.</p>
      ) : (
        <ul>
          {snapshots.map((s) => (
            <li key={s.id}>
              {s.saved_at} <button onClick={() => restore(s.id)}>이 시점으로 복원</button>
            </li>
          ))}
        </ul>
      )}
      <button onClick={onBack}>목록으로</button>
    </div>
  );
}
```

`frontend/src/screens/ProjectView.tsx` 수정:

- import에 `RecoveryScreen` 추가, needs_recovery 분기(Task 9의 안내문)를 교체:

```tsx
  if (project.status === "needs_recovery") {
    return (
      <main>
        <h1>{project.title}</h1>
        <RecoveryScreen project={project} onBack={onBack} />
      </main>
    );
  }
```

- 상태 추가: `const [exportPath, setExportPath] = useState("");`, `const [exporting, setExporting] = useState(false);`, `const [showRecovery, setShowRecovery] = useState(false);`, `const flushEditor = useRef<null | (() => Promise<void>)>(null);` (import에 `useRef` 추가)
- 편집 탭 렌더에 플러시 등록을 배선한다 (Task 12의 배선을 이렇게 바꾼다):

```tsx
      {!showRecovery && tab === "editor" && hasSlides && (
        <EditorScreen project={project} deck={deck} onDeckChange={setDeck}
          onEditorReady={(f) => { flushEditor.current = f; }} />
      )}
```

- 내보내기 핸들러 (보류 중 자동 저장을 먼저 밀어 넣어 마지막 편집이 내보내기에 빠지지 않게 한다, 결정 1):

```tsx
  const doExport = async () => {
    setExporting(true);
    setExportPath("");
    try {
      await flushEditor.current?.();           // 보류 중 자동 저장 플러시 (결정 1)
      await api.createSnapshot(project.name);  // 내보내기 직전 복구 지점 (결정 1)
      const r = await api.exportDeck(project.name);
      setExportPath(r.path);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setExporting(false);
    }
  };
```

- header의 nav 오른쪽에 추가:

```tsx
          <button onClick={doExport} disabled={!hasSlides || exporting}>PPTX 내보내기</button>
          <button onClick={() => setShowRecovery(true)}>스냅샷 복구</button>
```

- 본문 최상단에 내보내기 결과와 복구 화면 분기 추가:

```tsx
      {exportPath && <p className="export-path">내보내기 완료: {exportPath} (PowerPoint에서 여세요)</p>}
      {showRecovery && (
        <RecoveryScreen project={project} onBack={() => {
          setShowRecovery(false);
          // 복원본을 다시 읽을 때까지 덱을 내린다: 옛 덱으로 편집기가 재마운트되어
          // 다음 자동 저장이 복원 결과를 덮어쓰는 사고를 막는다 (2026-08-29 적대 리뷰 반영)
          setDeck(null);
          api.getDeck(project.name).then(setDeck).catch((e) => setError(messageOf(e)));
        }} />
      )}
```

showRecovery가 참이면 탭 본문 대신 복구 화면만 보이게 기존 탭 렌더 조건 전부에 `!showRecovery &&`를 붙인다 (편집 탭은 위의 배선 코드가 이미 반영).

- [ ] **Step 3: 통과 확인과 커밋**

Run: `frontend` 폴더 안에서 `npm test` → 전부 PASS, `npm run build` → 성공

```bash
git add frontend/src
git commit -m "feat: 내보내기(사전 스냅샷)와 스냅샷 복구 화면 (설계서 7.2)"
```

---

### Task 17: 전 구간 관통 확인과 문서 갱신

**Files:**
- Modify: `.gitignore` (frontend/dist), `CLAUDE.md` (프런트 명령), `docs/plans/2026-08-27-mvp-roadmap.md` (이월표와 진행 상태)

**Interfaces:**
- Consumes: 이 계획의 모든 산출물
- Produces: 관통 확인 기록, 진본 문서 정합. 로드맵의 이월표에서 이 계획이 소화한 9건을 "단계 4에서 처리 완료(날짜)"로 표기하고, 진행 상태에 단계 4를 체크한다.

- [ ] **Step 1: 자동 검증 전체 실행**

- `backend` 폴더에서 `.venv/Scripts/python.exe -m pytest tests -q` → 전체 PASS (개수 기록)
- `frontend` 폴더 안에서 `npm test` → 전체 PASS (개수 기록)
- `frontend` 폴더 안에서 `npm run build` → 성공

- [ ] **Step 2: 실서버 관통 확인 (수동 스모크, AI 실호출 포함)**

1. `backend` 폴더에서 `.venv/Scripts/python.exe -m slidecaptain serve --data-dir <임시 폴더>` 기동
2. 브라우저로 `http://127.0.0.1:8765` 접속 (빌드된 화면이 나와야 한다)
3. 흐름 관통: 프로젝트 생성 → 자료 1개 입력(실제 수치가 든 짧은 리서치 샘플) → 보고 정보 저장 → 구조안 생성(실호출) → 표에서 장 1개 수정 → 승인하고 내용 생성 → 편집 탭 자동 진입 → 인라인 텍스트 수정, 장 순서 드래그, 불릿 추가, 템플릿 교체(소실 확인 대화 포함), 디자인 값 1개 조정, 이 장 다시 생성(실호출)과 반영 → Ctrl+Z 확인 → PPTX 내보내기 → 파일 경로의 PPTX가 존재하고 PowerPoint(또는 재열기 검사)로 열리는지 확인
4. 스냅샷 목록에 의미 시점만 쌓였는지 확인(타이핑마다 쌓이지 않아야 한다)
5. 확인 결과(성공 여부, 발견 문제)를 로드맵 갱신 커밋 메시지와 아래 Step 3의 문서에 기록

- [ ] **Step 3: 문서 갱신**

- `.gitignore`에 `frontend/dist/` 추가 (node_modules 항목이 없다면 함께)
- `CLAUDE.md` 명령 절에 추가: 프런트 테스트(`frontend` 폴더 안에서 `npm test`), 개발 서버(`npm run dev`, 백엔드 serve와 병행), 화면 빌드(`npm run build`, serve가 dist를 함께 서빙)
- `docs/plans/2026-08-27-mvp-roadmap.md`:
  - 이월표의 9건(이 계획 "이월 항목" 표)을 "단계 4에서 처리 완료 (날짜)"로 갱신. 수치 게이트 항목에는 반영한 정밀화 2건과 잔여 한계(공백 없는 날짜 오탐, 콤마 나열 융합 미탐)를 명기
  - 단계 4 방치 확정 문단 신설: CLI export는 전역 프리셋 미적용(서버 경로만 적용, data-dir 맥락 부재), 미리보기 표 경계선 색은 화면 전용 상수(#D0D7E2, 렌더 계획 밖 장식), 수치 경고는 생성 응답에만 실려 편집 화면에서 지속 표시되지 않음(결정 12)
  - 진행 상태: `- [x] 단계 4: 편집 화면 (날짜 완료. 태스크 17개, 백엔드 테스트 N개, 프런트 테스트 M개. 실서버 관통 확인)` 형태로 갱신
- 리뷰에서 나온 신규 이월 항목이 있으면 이월표에 등재한다 (사이드 문서 금지 관례)

- [ ] **Step 4: 커밋**

```bash
git add .gitignore CLAUDE.md docs/plans/2026-08-27-mvp-roadmap.md
git commit -m "docs: 단계 4 완료 처리 (관통 확인, 이월표 갱신, 프런트 명령 기록)"
```

이후 브랜치 마무리(머지 여부)는 superpowers:finishing-a-development-branch 흐름으로 사용자에게 선택지를 제시한다.
