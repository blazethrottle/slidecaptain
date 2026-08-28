# 단계 2: 저장소 + API 서버 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로젝트 폴더 저장소(원자적 쓰기, 스냅샷, 복구)와 FastAPI 로컬 서버를 만들고, OpenAPI 스키마에서 TS 타입을 자동 생성하는 파이프라인을 세운다.

**Architecture:** 저장소 인터페이스(목록, 불러오기, 저장, 스냅샷) 뒤에 파일 구현을 두고(설계서 2.2), FastAPI 앱은 저장소와 단계 1 코어(레이아웃 엔진, 내보내기)를 조립만 한다. 이번 단계에서 렌더 계획(RenderPlan)에 스타일 수치를 내장해 자기완결 계약으로 격상한다: 단계 4의 미리보기는 프리셋 없이 렌더 계획 JSON만으로 그린다. 형식 정의의 진본은 백엔드 pydantic 모델 하나이고, 프런트 타입은 OpenAPI에서 기계 생성한다(설계서 2.1).

**Tech Stack:** Python 3.13, pydantic v2, FastAPI 0.141+, uvicorn, httpx(테스트), openapi-typescript 7.13 (Node)

## Global Constraints

- 서버는 127.0.0.1 전용 바인딩: 자료가 PC 밖으로 나가지 않는다 (설계서 1.3 로컬 웹앱)
- 저장은 원자적 쓰기: 같은 폴더의 임시 파일에 쓴 뒤 os.replace로 교체. 저장마다 기존 deck.json을 스냅샷 (설계서 7.2)
- deck.json은 내보내기 경로에서 절대 불변 (설계서 8)
- API와 CLI의 오류 안내는 쉬운 말로: 원인과 다음 행동을 담은 한국어 문장 (설계서 7.2)
- 프로젝트 이름과 자료 파일 이름은 검증 후 사용: 경로 탈출(`..`), Windows 금지 문자, 예약어 차단
- 코어는 Windows와 macOS 모두 동작: OS 전용 API(COM 등) 사용 금지 (설계서 9.1)
- 좌표와 글자 크기는 여전히 deck.json에 없다. 렌더 계획은 항상 서버가 프리셋에서 계산해 내려준다 (로드맵 아키텍처 결정 1)
- 단계 1 이월 항목 4건을 이 계획이 소화한다: schema_version 값 검증(Task 1), 라이터의 프리셋 인자 구조와 렌더 계획 수치 내장(Task 2), 라이터 시각 리터럴의 프리셋 승격(Task 2), CLI 오류 안내와 자동 테스트(Task 7)
- 생성 텍스트에 엠대시(U+2014)와 중점(U+00B7)을 쓰지 않는다 (사용자 전역 규칙)
- TDD: 모든 태스크는 실패하는 테스트부터. 커밋은 태스크 단위
- 작업 브랜치: 실행 시작 시 `feature/phase2-storage-api` 브랜치를 만들어 진행한다 (superpowers:using-git-worktrees)
- 테스트 실행 명령: `backend` 폴더에서 `.venv/Scripts/python.exe -m pytest tests -q` (Windows. macOS는 `.venv/bin/python`)

## 이 계획이 소비하는 단계 1 인터페이스 (실측 확인, 2026-08-28)

| 이름 | 시그니처 | 위치 |
|---|---|---|
| `Deck` | pydantic 모델. `schema_version: int = 1`, `meta: DeckMeta`, `structure`, `slides` | `slidecaptain/models/deck.py:105` |
| `DeckMeta` | `title`, `report_type`, `audience`, `preset_overrides: dict` | `slidecaptain/models/deck.py:98` |
| `Preset`, `apply_overrides(base, overrides)` | 전역 프리셋 + 덱별 덮어쓰기, 하한 재검증 | `slidecaptain/models/preset.py:93,115` |
| `build_render_plan(deck, preset, metrics) -> RenderPlan` | 결정론 레이아웃 | `slidecaptain/layout/engine.py:9` |
| `FontMetrics.load_default()` | 폰트 폭 (실측 또는 번들) | `slidecaptain/metrics/font_metrics.py:119` |
| `write_pptx(plan, out_path, preset)` | 렌더 계획 → PPTX (Task 2에서 preset 인자 제거) | `slidecaptain/export/pptx_writer.py:146` |
| `export_deck(deck_path, out_dir, global_preset=None) -> Path` | 파일 경로 기반 내보내기 (Task 5에서 코어 분리) | `slidecaptain/export/exporter.py:45` |
| CLI `python -m slidecaptain export <deck.json> [--out DIR]` | 오류 처리 없음 (Task 7에서 보강) | `slidecaptain/__main__.py` |

## 파일 구조 (이 계획이 만들고 고치는 것)

```
backend/
  pyproject.toml                      # 수정: fastapi, uvicorn 의존성, dev에 httpx
  openapi.json                        # 생성 산출물 (Task 8, 커밋함)
  scripts/
    dump_openapi.py                   # 신규: OpenAPI 스키마 덤프
  slidecaptain/
    models/
      deck.py                         # 수정: schema_version 값 검증 (Task 1)
      preset.py                       # 수정: border_width_pt, BulletMarker 승격 (Task 2)
      render.py                       # 수정: RenderStyle 추가 (Task 2)
    layout/
      engine.py                       # 수정: RenderPlan.style 채움 (Task 2)
    export/
      pptx_writer.py                  # 수정: preset 인자 제거, plan.style 소비 (Task 2)
      exporter.py                     # 수정: export_deck_data 코어 분리 (Task 5)
    storage/
      __init__.py                     # 신규
      file_store.py                   # 신규: 저장소 인터페이스 + 파일 구현 (Task 3)
    server/
      __init__.py                     # 신규
      app.py                          # 신규: FastAPI 앱 팩토리 (Task 4-6)
    __main__.py                       # 수정: serve 서브커맨드, export 오류 안내 (Task 7)
  tests/
    test_deck_schema.py               # 수정: schema_version 테스트 추가 (Task 1)
    test_pptx_writer.py               # 수정: 시그니처 변경 반영 (Task 2)
    test_preset.py                    # 수정: 승격 필드 테스트 (Task 2)
    test_file_store.py                # 신규 (Task 3)
    test_api_projects.py              # 신규 (Task 4)
    test_api_render_export.py         # 신규 (Task 5)
    test_api_snapshots_sources.py     # 신규 (Task 6)
    test_cli.py                       # 신규 (Task 7)
    test_openapi.py                   # 신규 (Task 8)
frontend/
  package.json                       # 신규: openapi-typescript 파이프라인 (Task 8)
  src/api/types.ts                   # 생성 산출물 (Task 8, 커밋함)
```

## 이 계획에서 확정하는 설계 결정

1. **렌더 계획 자기완결(RenderStyle 내장)**: 라이터가 프리셋에서 읽던 수치 전부(폰트 이름, 상자 안 여백, 행간 계수, 글머리표 들여쓰기와 간격, 표 셀 여백, 본문 색)와 코드에 리터럴로 박혀 있던 수치(테두리 두께 0.75pt, 글머리표 문자 "•", 글머리표 폰트 "Arial")를 `RenderPlan.style`로 옮긴다. 근거: 미리보기(단계 4)가 프리셋을 다시 해석하지 않고 렌더 계획 JSON만 소비하게 만들어, 수치 진본을 한 곳에 유지한다(로드맵 아키텍처 결정 1의 강화). 테두리 두께는 균일성 원칙에 따라 Frame별이 아니라 스타일 전역 1개다(이월표 문구 "Frame에 테두리 두께 추가"의 정밀화).
2. **데이터 폴더 기본값**: `~/slidecaptain-projects` (사용자 홈 아래, 탐색기에서 보이는 위치). `serve --data-dir`로 변경 가능. 근거: 사용자가 sources에 자료를 넣고 exports에서 PPTX를 꺼내는 폴더라서 눈에 보여야 한다.
3. **스냅샷 보존**: 전부 보존, 정리 없음. 근거: 1인 로컬, JSON 수십 KB 수준이라 용량 문제가 없고, 정리 규칙은 필요해질 때 넣는다(YAGNI).
4. **서버 포트 기본값**: 8765. 근거: 로컬 개발 포트(3000, 5173, 8000)와의 충돌을 피한 임의 고정값.
5. **생성 산출물 커밋**: `backend/openapi.json`과 `frontend/src/api/types.ts`는 기계 생성이지만 커밋한다. 근거: 단계 4가 Node 실행 없이 타입을 바로 소비할 수 있고, 스키마 변경이 diff로 보인다.

---

### Task 1: deck.json 로드 시 schema_version 값 검증 (이월 항목)

**Files:**
- Modify: `backend/slidecaptain/models/deck.py`
- Test: `backend/tests/test_deck_schema.py`

**Interfaces:**
- Consumes: `Deck`, `SCHEMA_VERSION` (기존)
- Produces: 지원하지 않는 schema_version이면 `ValidationError`. 저장소(Task 3)와 CLI(Task 7)의 로드 경로가 이 검증에 의존한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_deck_schema.py`에 추가:

```python
def test_unsupported_schema_version_rejected():
    with pytest.raises(ValidationError) as exc_info:
        Deck.model_validate({"schema_version": 99, "meta": {"title": "t"}})
    assert "스키마 버전" in str(exc_info.value)
    assert "99" in str(exc_info.value)


def test_current_schema_version_accepted():
    deck = Deck.model_validate({"schema_version": 1, "meta": {"title": "t"}})
    assert deck.schema_version == 1
```

파일 상단 import에 `pytest`, `ValidationError`(pydantic), `Deck`이 이미 있는지 확인하고 없으면 추가한다.

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deck_schema.py -q`
Expected: `test_unsupported_schema_version_rejected` FAIL (검증이 없어 통과해 버리므로 raises가 안 잡힘)

- [ ] **Step 3: 최소 구현**

`backend/slidecaptain/models/deck.py`의 `Deck` 클래스에 validator 추가 (`_chapters_and_slides_consistent` 위에):

```python
    @model_validator(mode="after")
    def _schema_version_supported(self) -> "Deck":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"이 덱 파일의 스키마 버전({self.schema_version})은 지원하지 않습니다. "
                f"이 앱은 버전 {SCHEMA_VERSION}만 읽을 수 있습니다. "
                f"파일이 더 새 버전이라면 앱을 업데이트해 주세요."
            )
        return self
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS (기존 79개 + 신규 2개)

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/models/deck.py backend/tests/test_deck_schema.py
git commit -m "feat: deck.json 로드 시 schema_version 값 검증 (단계 1 이월)"
```

---

### Task 2: 시각 리터럴의 프리셋 승격과 RenderStyle 내장 (이월 항목 2건)

**Files:**
- Modify: `backend/slidecaptain/models/preset.py`
- Modify: `backend/slidecaptain/models/render.py`
- Modify: `backend/slidecaptain/layout/engine.py`
- Modify: `backend/slidecaptain/export/pptx_writer.py`
- Modify: `backend/slidecaptain/export/exporter.py:63` (write_pptx 호출부)
- Test: `backend/tests/test_preset.py`, `backend/tests/test_pptx_writer.py`

**Interfaces:**
- Consumes: `Preset`, `RenderPlan`, `build_render_plan` (기존)
- Produces:
  - `Preset.spacing.border_width_pt: float = 0.75`, `Preset.bullet_marker: BulletMarker` (`char: str = "•"`, `font: str = "Arial"`)
  - `RenderStyle` 모델과 `RenderPlan.style: RenderStyle`
  - `write_pptx(plan: RenderPlan, out_path: str | Path) -> None` (preset 인자 제거. Task 5의 exporter와 이후 모든 호출부가 이 시그니처를 쓴다)

- [ ] **Step 1: 실패하는 테스트 작성 (프리셋 승격)**

`backend/tests/test_preset.py`에 추가:

```python
def test_border_width_and_bullet_marker_promoted():
    p = Preset()
    assert p.spacing.border_width_pt == 0.75
    assert p.bullet_marker.char == "•"
    assert p.bullet_marker.font == "Arial"


def test_bullet_marker_override():
    p = apply_overrides(Preset(), {"bullet_marker": {"char": "-"}})
    assert p.bullet_marker.char == "-"
    assert p.bullet_marker.font == "Arial"
```

- [ ] **Step 2: 실패하는 테스트 작성 (RenderStyle 내장과 라이터)**

`backend/tests/test_pptx_writer.py`의 기존 `_simple_plan()` 헬퍼는 `RenderPlan(...)` 생성에 `style=` 인자가 필요해진다. 파일 상단에 헬퍼를 추가하고 기존 헬퍼들이 쓰게 한다:

```python
from slidecaptain.models.render import RenderStyle

def _style() -> RenderStyle:
    return RenderStyle(
        korean_font="맑은 고딕",
        latin_font="맑은 고딕",
        text_color="202020",
        box_padding_pt=10.0,
        line_spacing=1.4,
        bullet_indent_pt=18.0,
        bullet_gap_pt=6.0,
        table_cell_pad_x_pt=6.0,
        table_cell_pad_y_pt=3.0,
        border_width_pt=0.75,
        bullet_char="•",
        bullet_font="Arial",
    )
```

새 테스트 추가 (테두리 도형은 유형이 아니라 이름으로 찾는다. python-pptx 실측: 테두리를 지정하지 않은 도형도 line.width가 None이 아니라 0을 돌려주므로 유형 필터는 신뢰할 수 없다):

```python
def test_style_comes_from_plan_not_literal(tmp_path):
    style = _style()
    style.border_width_pt = 2.0
    plan = _simple_plan()
    plan.style = style
    bordered_frame = next(
        f for slide in plan.slides for f in slide.frames if f.border and f.table is None
    )
    out = tmp_path / "t.pptx"
    write_pptx(plan, out)
    prs = Presentation(str(out))
    shapes = {s.name: s for slide in prs.slides for s in slide.shapes}
    assert shapes[bordered_frame.name].line.width.pt == pytest.approx(2.0)
```

그리고 호출부와 고아 코드를 정리한다:

- `write_pptx(..., PRESET)` 호출 3곳에서 PRESET 인자를 뺀다: `tests/test_pptx_writer.py` 2곳(47줄, 138줄)과 `tests/test_table_render.py` 1곳(42줄. 이 파일의 plan은 엔진이 만들므로 style은 자동으로 채워진다)
- `_simple_plan()`과 `_border_only_plan()`의 `RenderPlan(...)` 생성에 `style=_style()`을 추가한다
- 수정 후 `test_pptx_writer.py`에서 미사용이 되는 `PRESET` 상수와 `from slidecaptain.models.preset import Preset` import를 삭제한다 (test_table_render.py도 같은 방식으로 미사용 import가 생기면 삭제)

- [ ] **Step 3: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_preset.py tests/test_pptx_writer.py -q`
Expected: FAIL (`border_width_pt`, `BulletMarker`, `RenderStyle` 미정의)

- [ ] **Step 4: 프리셋 구현**

`backend/slidecaptain/models/preset.py`:

`Spacing` 클래스 마지막 필드(`safety_ratio`) 다음에 추가:

```python
    border_width_pt: float = 0.75
```

`Colors` 클래스 아래에 새 클래스 추가:

```python
class BulletMarker(BaseModel):
    """불릿 목록 표식. 문자와 표식 전용 폰트 (승격 전에는 라이터의 리터럴이었다)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    char: str = "•"
    font: str = "Arial"
```

`Preset` 클래스에 필드 추가 (`spacing` 다음):

```python
    bullet_marker: BulletMarker = BulletMarker()
```

- [ ] **Step 5: RenderStyle 구현**

`backend/slidecaptain/models/render.py`의 `RenderPlan` 위에 추가:

```python
class RenderStyle(BaseModel):
    """라이터와 미리보기가 소비하는 시각 스타일. 프리셋에서 계산되어 렌더 계획에 내장된다.

    렌더 계획은 이 블록 덕에 자기완결적이다: 소비자는 프리셋을 다시 해석하지 않는다.
    """

    korean_font: str
    latin_font: str
    text_color: str
    box_padding_pt: float
    line_spacing: float  # 행간 계수. 라이터가 font_pt에 곱해 고정 pt로 기록한다
    bullet_indent_pt: float
    bullet_gap_pt: float
    table_cell_pad_x_pt: float
    table_cell_pad_y_pt: float
    border_width_pt: float
    bullet_char: str
    bullet_font: str
```

`RenderPlan`에 필드 추가:

```python
class RenderPlan(BaseModel):
    page_width_pt: float
    page_height_pt: float
    style: RenderStyle
    slides: list[SlidePlan]
```

- [ ] **Step 6: 엔진이 style을 채우게 구현**

`backend/slidecaptain/layout/engine.py`의 `build_render_plan` 반환부를 교체:

```python
from slidecaptain.models.render import RenderPlan, RenderStyle


def _style_from_preset(preset: Preset) -> RenderStyle:
    return RenderStyle(
        korean_font=preset.fonts.korean,
        latin_font=preset.fonts.latin,
        text_color=preset.colors.text,
        box_padding_pt=preset.spacing.box_padding,
        line_spacing=preset.spacing.line_spacing,
        bullet_indent_pt=preset.spacing.bullet_indent,
        bullet_gap_pt=preset.spacing.bullet_gap,
        table_cell_pad_x_pt=preset.spacing.table_cell_pad_x,
        table_cell_pad_y_pt=preset.spacing.table_cell_pad_y,
        border_width_pt=preset.spacing.border_width_pt,
        bullet_char=preset.bullet_marker.char,
        bullet_font=preset.bullet_marker.font,
    )
```

반환문:

```python
    return RenderPlan(
        page_width_pt=preset.page_width_pt,
        page_height_pt=preset.page_height_pt,
        style=_style_from_preset(preset),
        slides=slides,
    )
```

- [ ] **Step 7: 라이터가 plan.style을 소비하게 구현**

`backend/slidecaptain/export/pptx_writer.py` 전체 수정 방향 (preset 인자를 제거하고 `style: RenderStyle`을 내려보낸다):

```python
from slidecaptain.models.render import Frame, Para, RenderPlan, RenderStyle, TablePlan


def _style_run(run, para: Para, style: RenderStyle) -> None:
    # 기존 코드에서 preset.fonts.latin → style.latin_font, preset.fonts.korean → style.korean_font
    ...


def _apply_bullet(paragraph, para: Para, style: RenderStyle) -> None:
    indent_emu = round(style.bullet_indent_pt * EMU_PER_PT)
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("marL", str(indent_emu * (para.level + 1)))
    pPr.set("indent", str(-indent_emu))
    bu_font = pPr.makeelement(qn("a:buFont"), {"typeface": style.bullet_font})
    bu_char = pPr.makeelement(qn("a:buChar"), {"char": style.bullet_char})
    pPr.append(bu_font)
    pPr.append(bu_char)


def write_pptx(plan: RenderPlan, out_path: str | Path) -> None:
    style = plan.style
    ...  # 이하 기존 흐름 그대로, preset 참조를 style 필드로 치환:
    # preset.spacing.box_padding      → style.box_padding_pt
    # preset.spacing.line_spacing     → style.line_spacing
    # preset.spacing.bullet_gap       → style.bullet_gap_pt
    # preset.spacing.table_cell_pad_x → style.table_cell_pad_x_pt
    # preset.spacing.table_cell_pad_y → style.table_cell_pad_y_pt
    # preset.colors.text              → style.text_color
    # Pt(0.75)                        → Pt(style.border_width_pt)
```

내부 헬퍼 `_fill_text_frame`, `_add_text_shape`, `_add_table_shape`의 `preset: Preset` 파라미터도 전부 `style: RenderStyle`로 바꾼다. `from slidecaptain.models.preset import Preset` import는 삭제한다.

- [ ] **Step 8: 호출부 갱신**

`backend/slidecaptain/export/exporter.py:63`의 `write_pptx(plan, tmp_file, preset)` → `write_pptx(plan, tmp_file)`.
`backend/tests/test_layout_engine.py`와 `backend/tests/test_table_render.py`에서 `RenderPlan` 필드를 직접 검사하는 테스트가 있으면 `plan.style` 접근이 깨지지 않는지 확인한다 (엔진이 항상 채우므로 생성 경로는 영향 없음).

- [ ] **Step 9: 전체 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS. 특히 골든 테스트(test_table_render)와 회귀(test_regression)가 그대로 통과해야 한다 (기본값이 기존 리터럴과 동일하므로 산출 PPTX는 바이트 수준까지는 아니어도 검사 항목 수준에서 불변)

- [ ] **Step 10: 커밋**

```bash
git add backend/slidecaptain backend/tests
git commit -m "feat: 시각 리터럴 프리셋 승격과 RenderStyle 내장 (렌더 계획 자기완결, 단계 1 이월 2건)"
```

---

### Task 3: 프로젝트 폴더 저장소 (원자적 쓰기, 스냅샷, 복구)

**Files:**
- Create: `backend/slidecaptain/storage/__init__.py` (빈 파일)
- Create: `backend/slidecaptain/storage/file_store.py`
- Test: `backend/tests/test_file_store.py`

**Interfaces:**
- Consumes: `Deck`, `DeckMeta` (models/deck.py)
- Produces (Task 4~6의 API가 전부 이 저장소만 통해 파일을 만진다):
  - 예외: `StorageError` (기반), `InvalidName`, `ProjectNotFound`, `ProjectExists`, `SnapshotNotFound`, `SourceNotFound`. 전부 사용자에게 보여줄 한국어 메시지를 담는다
  - `ProjectInfo(name, title, updated_at)`, `SnapshotInfo(id, saved_at)` (pydantic)
  - `ProjectStore` Protocol: 저장소 인터페이스 (설계서 2.2). `create_app`은 이 타입으로 주입받아, 판매 단계의 DB 구현 교체(설계서 2.1)가 앱 수정 없이 가능하다
  - `FileProjectStore(root)`: `list_projects() -> list[ProjectInfo]`, `create_project(name, title="") -> ProjectInfo`, `load_deck(name) -> Deck`, `save_deck(name, deck) -> None`, `list_snapshots(name) -> list[SnapshotInfo]`, `restore_snapshot(name, snapshot_id) -> Deck`, `list_sources(name) -> list[str]`, `read_source(name, filename) -> str`, `write_source(name, filename, text) -> None`, `exports_dir(name) -> Path`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_file_store.py` 신규:

```python
import pytest

from slidecaptain.models.deck import Deck, DeckMeta
from slidecaptain.storage.file_store import (
    FileProjectStore,
    InvalidName,
    ProjectExists,
    ProjectNotFound,
    SnapshotNotFound,
    SourceNotFound,
)


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def _deck(title="테스트 덱"):
    return Deck(meta=DeckMeta(title=title))


def test_create_project_builds_folder_layout(store):
    info = store.create_project("주간보고", title="주간 보고")
    assert info.name == "주간보고"
    assert info.title == "주간 보고"
    root = store.root / "주간보고"
    assert (root / "deck.json").exists()
    assert (root / "sources").is_dir()
    assert (root / "snapshots").is_dir()
    assert (root / "exports").is_dir()


def test_create_duplicate_project_rejected(store):
    store.create_project("p1")
    with pytest.raises(ProjectExists):
        store.create_project("p1")


@pytest.mark.parametrize("bad", ["", "..", "a/b", "a\\b", "CON", "긴이름" * 30, " 앞공백", "이름끝점."])
def test_invalid_project_names_rejected(store, bad):
    with pytest.raises(InvalidName):
        store.create_project(bad)


def test_load_save_round_trip(store):
    store.create_project("p1", title="원래 제목")
    deck = store.load_deck("p1")
    deck.meta.title = "고친 제목"
    store.save_deck("p1", deck)
    assert store.load_deck("p1").meta.title == "고친 제목"


def test_save_makes_snapshot_of_previous_state(store):
    store.create_project("p1", title="v1")
    deck = store.load_deck("p1")
    deck.meta.title = "v2"
    store.save_deck("p1", deck)  # 저장 직전의 v1이 스냅샷으로 남는다
    snaps = store.list_snapshots("p1")
    assert len(snaps) == 1
    restored = store.restore_snapshot("p1", snaps[0].id)
    assert restored.meta.title == "v1"
    # 복원도 저장이므로 복원 직전 상태(v2)가 다시 스냅샷으로 남는다
    assert len(store.list_snapshots("p1")) == 2


def test_create_project_leaves_no_snapshot(store):
    store.create_project("p1")
    assert store.list_snapshots("p1") == []


def test_atomic_write_leaves_no_tmp_file(store):
    store.create_project("p1")
    store.save_deck("p1", _deck())
    leftovers = [p for p in (store.root / "p1").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_uses_atomic_replace(store, monkeypatch):
    # 원자성 자체를 고정한다: 저장이 임시 파일 + os.replace 경로를 반드시 거쳐야 한다
    import slidecaptain.storage.file_store as fs

    calls = []
    real_replace = fs.os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(fs.os, "replace", spy)
    store.create_project("p1")
    store.save_deck("p1", _deck())
    deck_writes = [c for c in calls if c[1].endswith("deck.json")]
    assert deck_writes, "deck.json 저장이 os.replace를 거치지 않았습니다"
    assert deck_writes[-1][0].endswith(".tmp")


def test_missing_project_raises(store):
    with pytest.raises(ProjectNotFound):
        store.load_deck("없는프로젝트")


def test_missing_snapshot_raises(store):
    store.create_project("p1")
    with pytest.raises(SnapshotNotFound):
        store.restore_snapshot("p1", "deck-19990101-000000-000000")


def test_corrupted_deck_reports_recovery_hint(store):
    store.create_project("p1")
    (store.root / "p1" / "deck.json").write_text("{망가진 json", encoding="utf-8")
    with pytest.raises(Exception) as exc_info:
        store.load_deck("p1")
    assert "스냅샷" in str(exc_info.value)


def test_list_projects_sorted_with_updated_at(store):
    store.create_project("b프로젝트")
    store.create_project("a프로젝트")
    infos = store.list_projects()
    assert [i.name for i in infos] == ["a프로젝트", "b프로젝트"]
    assert all(i.updated_at for i in infos)


def test_sources_round_trip(store):
    store.create_project("p1")
    store.write_source("p1", "리서치.md", "# 자료\n숫자 42")
    assert store.list_sources("p1") == ["리서치.md"]
    assert "42" in store.read_source("p1", "리서치.md")


def test_source_name_traversal_rejected(store):
    store.create_project("p1")
    with pytest.raises(InvalidName):
        store.write_source("p1", "..\\밖으로.md", "x")
    with pytest.raises(SourceNotFound):
        store.read_source("p1", "없는파일.md")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_store.py -q`
Expected: FAIL (`slidecaptain.storage` 모듈 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/storage/__init__.py`: 빈 파일.

`backend/slidecaptain/storage/file_store.py`:

```python
"""프로젝트 폴더 저장소 (설계서 3.1, 7.2).

projects/<프로젝트명>/
  deck.json      # 진본
  sources/       # 입력 자료 원문 (수치 대조의 기준)
  snapshots/     # 저장 시점 스냅샷
  exports/       # 내보낸 PPTX

- 저장은 원자적: 같은 폴더의 임시 파일에 쓴 뒤 os.replace로 교체
- 저장마다 직전 deck.json을 스냅샷으로 보존 (복구 경로)
"""

import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from slidecaptain.models.deck import Deck, DeckMeta

_NAME_RE = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣 ._\-]{0,79}$")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_SNAPSHOT_RE = re.compile(r"^deck-(\d{8}-\d{6}-\d{6})(?:-\d+)?$")


class StorageError(Exception):
    """사용자에게 쉬운 말로 보여줄 저장소 오류."""


class InvalidName(StorageError):
    pass


class ProjectNotFound(StorageError):
    pass


class ProjectExists(StorageError):
    pass


class SnapshotNotFound(StorageError):
    pass


class SourceNotFound(StorageError):
    pass


class ProjectInfo(BaseModel):
    name: str
    title: str
    updated_at: str  # ISO 8601


class SnapshotInfo(BaseModel):
    id: str  # 파일 이름에서 확장자를 뺀 것 (예: deck-20260828-153000-123456)
    saved_at: str


def _validate_name(name: str, kind: str) -> None:
    stem = name.split(".")[0].upper()
    if (
        not _NAME_RE.match(name)
        or name != name.strip()
        or ".." in name
        or name.endswith(".")  # Windows가 끝 마침표를 조용히 지워 폴더 이름이 어긋난다
        or stem in _WINDOWS_RESERVED
    ):
        raise InvalidName(
            f"{kind} 이름으로 쓸 수 없습니다: {name!r}. "
            "한글, 영문, 숫자로 시작하고 공백, 점, 밑줄, 붙임표만 섞어 80자 이내로 지어 주세요 "
            "(마침표로 끝나는 이름은 안 됩니다)."
        )


class ProjectStore(Protocol):
    """저장소 인터페이스 (설계서 2.2). 파일 구현 외의 구현(DB 등)으로 교체 가능하게 한다."""

    def list_projects(self) -> list[ProjectInfo]: ...
    def create_project(self, name: str, title: str = "") -> ProjectInfo: ...
    def load_deck(self, name: str) -> Deck: ...
    def save_deck(self, name: str, deck: Deck) -> None: ...
    def list_snapshots(self, name: str) -> list[SnapshotInfo]: ...
    def restore_snapshot(self, name: str, snapshot_id: str) -> Deck: ...
    def list_sources(self, name: str) -> list[str]: ...
    def read_source(self, name: str, filename: str) -> str: ...
    def write_source(self, name: str, filename: str, text: str) -> None: ...
    def exports_dir(self, name: str) -> Path: ...


class FileProjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- 내부 공통 ---------------------------------------------------------

    def _project_dir(self, name: str) -> Path:
        _validate_name(name, "프로젝트")
        d = self.root / name
        if not (d / "deck.json").exists():
            raise ProjectNotFound(f"프로젝트를 찾지 못했습니다: {name}")
        return d

    def _write_deck(self, project_dir: Path, deck: Deck) -> None:
        tmp = project_dir / "deck.json.tmp"
        tmp.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, project_dir / "deck.json")

    def _snapshot_current(self, project_dir: Path) -> None:
        src = project_dir / "deck.json"
        if not src.exists():
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dst = project_dir / "snapshots" / f"deck-{ts}.json"
        n = 1
        while dst.exists():  # 같은 마이크로초 충돌 백스톱
            dst = project_dir / "snapshots" / f"deck-{ts}-{n}.json"
            n += 1
        shutil.copy2(src, dst)

    # -- 프로젝트 ----------------------------------------------------------

    def create_project(self, name: str, title: str = "") -> ProjectInfo:
        _validate_name(name, "프로젝트")
        d = self.root / name
        if d.exists():
            raise ProjectExists(f"같은 이름의 프로젝트가 이미 있습니다: {name}")
        (d / "sources").mkdir(parents=True)
        (d / "snapshots").mkdir()
        (d / "exports").mkdir()
        self._write_deck(d, Deck(meta=DeckMeta(title=title or name)))
        return self._info(d)

    def list_projects(self) -> list[ProjectInfo]:
        infos = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and (d / "deck.json").exists():
                infos.append(self._info(d))
        return infos

    def _info(self, d: Path) -> ProjectInfo:
        deck_path = d / "deck.json"
        try:
            title = Deck.model_validate_json(deck_path.read_text(encoding="utf-8")).meta.title
        except (ValueError, ValidationError):
            title = "(deck.json 읽기 실패: 스냅샷 복구가 필요합니다)"
        mtime = datetime.fromtimestamp(deck_path.stat().st_mtime).astimezone()
        return ProjectInfo(name=d.name, title=title, updated_at=mtime.isoformat(timespec="seconds"))

    # -- 덱 ---------------------------------------------------------------

    def load_deck(self, name: str) -> Deck:
        d = self._project_dir(name)
        try:
            return Deck.model_validate_json((d / "deck.json").read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as e:
            raise StorageError(
                f"프로젝트 {name}의 deck.json을 읽지 못했습니다. "
                f"스냅샷 복구 기능으로 이전 저장 시점으로 되돌릴 수 있습니다. 원인: {e}"
            ) from e

    def save_deck(self, name: str, deck: Deck) -> None:
        d = self._project_dir(name)
        self._snapshot_current(d)
        self._write_deck(d, deck)

    # -- 스냅샷 ------------------------------------------------------------

    def list_snapshots(self, name: str) -> list[SnapshotInfo]:
        d = self._project_dir(name)
        infos = []
        for p in sorted((d / "snapshots").glob("deck-*.json")):
            m = _SNAPSHOT_RE.match(p.stem)
            if m is None:
                continue
            ts = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S-%f").astimezone()
            infos.append(SnapshotInfo(id=p.stem, saved_at=ts.isoformat(timespec="seconds")))
        return infos

    def restore_snapshot(self, name: str, snapshot_id: str) -> Deck:
        d = self._project_dir(name)
        _validate_name(snapshot_id, "스냅샷")
        path = d / "snapshots" / f"{snapshot_id}.json"
        if not path.exists():
            raise SnapshotNotFound(f"스냅샷을 찾지 못했습니다: {snapshot_id}")
        try:
            deck = Deck.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as e:
            raise StorageError(f"스냅샷 {snapshot_id}을 읽지 못했습니다. 다른 스냅샷을 골라 주세요. 원인: {e}") from e
        self._snapshot_current(d)  # 복원 직전 상태도 스냅샷으로 남긴다
        self._write_deck(d, deck)
        return deck

    # -- 입력 자료 ----------------------------------------------------------

    def list_sources(self, name: str) -> list[str]:
        d = self._project_dir(name)
        return sorted(p.name for p in (d / "sources").iterdir() if p.is_file())

    def read_source(self, name: str, filename: str) -> str:
        d = self._project_dir(name)
        _validate_name(filename, "자료 파일")
        path = d / "sources" / filename
        if not path.exists():
            raise SourceNotFound(f"자료 파일을 찾지 못했습니다: {filename}")
        return path.read_text(encoding="utf-8")

    def write_source(self, name: str, filename: str, text: str) -> None:
        d = self._project_dir(name)
        _validate_name(filename, "자료 파일")
        tmp = d / "sources" / (filename + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, d / "sources" / filename)

    # -- 내보내기 -----------------------------------------------------------

    def exports_dir(self, name: str) -> Path:
        return self._project_dir(name) / "exports"
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_file_store.py -q`
Expected: 전체 PASS

- [ ] **Step 5: 전체 스위트 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/slidecaptain/storage backend/tests/test_file_store.py
git commit -m "feat: 프로젝트 폴더 저장소 (원자적 쓰기, 저장마다 스냅샷, 복구)"
```

---

### Task 4: FastAPI 앱과 프로젝트, 덱 엔드포인트

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/slidecaptain/server/__init__.py` (빈 파일)
- Create: `backend/slidecaptain/server/app.py`
- Test: `backend/tests/test_api_projects.py`

**Interfaces:**
- Consumes: `FileProjectStore`와 예외들(Task 3), `Deck`, `Preset`, `apply_overrides`
- Produces:
  - `create_app(store: ProjectStore) -> FastAPI` (Task 5~7과 dump_openapi가 사용. 인자 타입은 Task 3의 Protocol)
  - HTTP: `GET /api/projects`, `POST /api/projects`, `GET /api/projects/{name}/deck`, `PUT /api/projects/{name}/deck`
  - 오류 매핑: InvalidName → 422, ProjectNotFound/SnapshotNotFound/SourceNotFound → 404, ProjectExists → 409, 기타 StorageError → 400. 응답 본문은 FastAPI 표준 `{"detail": "<쉬운 말>"}`

- [ ] **Step 1: 의존성 추가**

`backend/pyproject.toml`:

```toml
dependencies = [
    "pydantic>=2.9",
    "python-pptx==1.0.2",
    "fonttools>=4.63",
    "fastapi>=0.141",
    "uvicorn>=0.30",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]
```

Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`
Expected: fastapi, uvicorn, httpx 설치 성공

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_api_projects.py` 신규:

```python
import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def client(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    return TestClient(create_app(store))


def test_create_and_list_projects(client):
    r = client.post("/api/projects", json={"name": "주간보고", "title": "주간 보고"})
    assert r.status_code == 201
    assert r.json()["name"] == "주간보고"
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["주간보고"]


def test_create_duplicate_conflict(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects", json={"name": "p1"})
    assert r.status_code == 409
    assert "이미 있습니다" in r.json()["detail"]


def test_create_invalid_name_unprocessable(client):
    r = client.post("/api/projects", json={"name": "a/b"})
    assert r.status_code == 422


def test_get_and_put_deck(client):
    client.post("/api/projects", json={"name": "p1", "title": "제목"})
    deck = client.get("/api/projects/p1/deck").json()
    assert deck["meta"]["title"] == "제목"
    deck["meta"]["title"] = "고친 제목"
    r = client.put("/api/projects/p1/deck", json=deck)
    assert r.status_code == 200
    assert client.get("/api/projects/p1/deck").json()["meta"]["title"] == "고친 제목"


def test_get_deck_missing_project_404(client):
    r = client.get("/api/projects/없는것/deck")
    assert r.status_code == 404


def test_put_deck_invalid_schema_422(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.put("/api/projects/p1/deck", json={"meta": {}})  # title 없음
    assert r.status_code == 422


def test_put_deck_bad_preset_overrides_422(client):
    client.post("/api/projects", json={"name": "p1"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["meta"]["preset_overrides"] = {"font_roles": {"body_pt": 8}}  # 하한 위반
    r = client.put("/api/projects/p1/deck", json=deck)
    assert r.status_code == 422
    assert "하한" in r.json()["detail"]
```

- [ ] **Step 3: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_projects.py -q`
Expected: FAIL (`slidecaptain.server` 모듈 없음)

- [ ] **Step 4: 구현**

`backend/slidecaptain/server/__init__.py`: 빈 파일.

`backend/slidecaptain/server/app.py`:

```python
"""FastAPI 로컬 서버 (설계서 2.2). 저장소와 단계 1 코어를 조립만 한다.

실행은 CLI의 serve 서브커맨드가 담당하며 127.0.0.1 전용으로 바인딩한다 (로컬 웹앱).
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset, apply_overrides
from slidecaptain.storage.file_store import (
    InvalidName,
    ProjectExists,
    ProjectNotFound,
    ProjectInfo,
    ProjectStore,
    SnapshotNotFound,
    SourceNotFound,
    StorageError,
)

_STATUS_BY_ERROR = [
    (InvalidName, 422),
    (ProjectNotFound, 404),
    (SnapshotNotFound, 404),
    (SourceNotFound, 404),
    (ProjectExists, 409),
    (StorageError, 400),
]


class CreateProjectRequest(BaseModel):
    name: str
    title: str = ""


class OkResponse(BaseModel):
    ok: bool = True


def create_app(store: ProjectStore) -> FastAPI:
    app = FastAPI(title="Slide Captain", version="0.2.0")

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError):
        status = next(code for cls, code in _STATUS_BY_ERROR if isinstance(exc, cls))
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.get("/api/projects", response_model=list[ProjectInfo])
    def list_projects():
        return store.list_projects()

    @app.post("/api/projects", response_model=ProjectInfo, status_code=201)
    def create_project(req: CreateProjectRequest):
        return store.create_project(req.name, req.title)

    @app.get("/api/projects/{name}/deck", response_model=Deck)
    def get_deck(name: str):
        return store.load_deck(name)

    @app.put("/api/projects/{name}/deck", response_model=OkResponse)
    def put_deck(name: str, deck: Deck):
        try:
            apply_overrides(Preset(), deck.meta.preset_overrides)
        except ValidationError as e:
            first = e.errors()[0]["msg"]
            raise HTTPException(422, f"프리셋 덮어쓰기 값이 유효하지 않습니다: {first}")
        store.save_deck(name, deck)
        return OkResponse()

    return app
```

- [ ] **Step 5: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/pyproject.toml backend/slidecaptain/server backend/tests/test_api_projects.py
git commit -m "feat: FastAPI 앱과 프로젝트, 덱 엔드포인트 (저장소 오류의 상태 코드 매핑)"
```

---

### Task 5: 렌더 계획과 내보내기 엔드포인트 (exporter 코어 분리)

**Files:**
- Modify: `backend/slidecaptain/export/exporter.py`
- Modify: `backend/slidecaptain/server/app.py`
- Test: `backend/tests/test_api_render_export.py`

**Interfaces:**
- Consumes: `build_render_plan`, `FontMetrics.load_default()`, `apply_overrides`, `FileProjectStore.exports_dir`
- Produces:
  - `export_deck_data(deck: Deck, out_dir: str | Path, global_preset: Preset | None = None) -> Path` (메모리의 덱을 내보내는 코어. 기존 `export_deck`은 파일 래퍼로 유지되어 CLI가 계속 쓴다)
  - HTTP: `GET /api/projects/{name}/render-plan` (RenderPlan JSON), `POST /api/projects/{name}/export` (`{"path": "<내보낸 파일 절대경로>"}`)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_render_export.py` 신규:

```python
import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def _project_with_slide(client):
    client.post("/api/projects", json={"name": "p1", "title": "덱"})
    deck = client.get("/api/projects/p1/deck").json()
    deck["structure"] = {"chapters": [
        {"id": "c1", "topic": "요약", "template": "summary"}
    ]}
    deck["slides"] = [{"chapter_id": "c1", "slots": {
        "template": "summary", "conclusion": "결론 한 줄",
        "points": [{"text": "요점"}],
    }}]
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def test_render_plan_returns_frames_and_style(client):
    _project_with_slide(client)
    r = client.get("/api/projects/p1/render-plan")
    assert r.status_code == 200
    plan = r.json()
    assert plan["page_width_pt"] == 960.0
    assert plan["style"]["korean_font"] == "맑은 고딕"
    assert plan["style"]["border_width_pt"] == 0.75
    assert len(plan["slides"]) == 1
    assert plan["slides"][0]["frames"], "프레임이 비어 있습니다"


def test_render_plan_applies_deck_overrides(client):
    _project_with_slide(client)
    deck = client.get("/api/projects/p1/deck").json()
    deck["meta"]["preset_overrides"] = {"colors": {"text": "111111"}}
    client.put("/api/projects/p1/deck", json=deck)
    plan = client.get("/api/projects/p1/render-plan").json()
    assert plan["style"]["text_color"] == "111111"


def test_export_writes_versioned_pptx(client, store):
    _project_with_slide(client)
    r = client.post("/api/projects/p1/export")
    assert r.status_code == 200
    path = r.json()["path"]
    assert path.endswith("_v001.pptx")
    assert (store.exports_dir("p1") / path.split("\\")[-1].split("/")[-1]).exists()
    # 내보내기가 deck.json을 바꾸지 않는다 (설계서 8)
    before = client.get("/api/projects/p1/deck").json()
    client.post("/api/projects/p1/export")
    assert client.get("/api/projects/p1/deck").json() == before


def test_render_plan_missing_project_404(client):
    assert client.get("/api/projects/없는것/render-plan").status_code == 404
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_render_export.py -q`
Expected: FAIL (404: render-plan 라우트 없음)

- [ ] **Step 3: exporter 코어 분리**

`backend/slidecaptain/export/exporter.py`의 `export_deck`을 둘로 나눈다:

```python
def export_deck_data(
    deck: Deck,
    out_dir: str | Path,
    global_preset: Preset | None = None,
) -> Path:
    """메모리의 덱을 새 버전 파일로 내보낸다. 덱 데이터는 절대 고치지 않는다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    preset = apply_overrides(global_preset or Preset(), deck.meta.preset_overrides)
    metrics = FontMetrics.load_default()
    plan = build_render_plan(deck, preset, metrics)

    final_path = _next_version_path(out_dir, _safe_title(deck.meta.title))
    with tempfile.TemporaryDirectory(prefix="slidecaptain_") as tmp:
        tmp_file = Path(tmp) / "deck.pptx"
        write_pptx(plan, tmp_file)
        shutil.move(str(tmp_file), str(final_path))
    return final_path


def export_deck(
    deck_path: str | Path,
    out_dir: str | Path,
    global_preset: Preset | None = None,
) -> Path:
    deck = Deck.model_validate_json(Path(deck_path).read_text(encoding="utf-8"))
    return export_deck_data(deck, out_dir, global_preset)
```

기존 함수 본문의 임시 폴더 주석("tempfile 표준 임시 폴더는 ASCII 경로다")은 이관하지 않는다. 이 단정은 미검증이며(로드맵 방치 확정 절의 주의 참조), python-pptx에는 ASCII가 필요 없음이 확인되어 임시 폴더 경유는 "부분 저장 파일 노출 방지" 목적만 남는다. 새 주석: `# 임시 폴더에서 쓴 뒤 이동: 저장 도중 실패해도 exports/에 깨진 파일이 남지 않는다`.

- [ ] **Step 4: 서버 라우트 추가**

`backend/slidecaptain/server/app.py`에 추가한다. import에 `export_deck_data`, `build_render_plan`, `FontMetrics`, `RenderPlan`을 더하고, `create_app` 안에서 `metrics = FontMetrics.load_default()`를 앱 생성 시 1회 로드해 닫아 쓴다:

```python
from slidecaptain.export.exporter import export_deck_data
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.render import RenderPlan


class ExportResult(BaseModel):
    path: str


def create_app(store: ProjectStore) -> FastAPI:
    app = FastAPI(title="Slide Captain", version="0.2.0")
    metrics = FontMetrics.load_default()  # 앱 수명 동안 1회 로드
    ...

    @app.get("/api/projects/{name}/render-plan", response_model=RenderPlan)
    def get_render_plan(name: str):
        deck = store.load_deck(name)
        preset = apply_overrides(Preset(), deck.meta.preset_overrides)
        return build_render_plan(deck, preset, metrics)

    @app.post("/api/projects/{name}/export", response_model=ExportResult)
    def export_project(name: str):
        deck = store.load_deck(name)
        path = export_deck_data(deck, store.exports_dir(name))
        return ExportResult(path=str(path))
```

- [ ] **Step 5: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS (기존 test_exporter도 래퍼 유지로 그대로 통과)

```bash
git add backend/slidecaptain/export/exporter.py backend/slidecaptain/server/app.py backend/tests/test_api_render_export.py
git commit -m "feat: 렌더 계획과 내보내기 엔드포인트 (exporter 코어를 메모리 덱 기반으로 분리)"
```

---

### Task 6: 스냅샷과 입력 자료 엔드포인트

**Files:**
- Modify: `backend/slidecaptain/server/app.py`
- Test: `backend/tests/test_api_snapshots_sources.py`

**Interfaces:**
- Consumes: `FileProjectStore.list_snapshots / restore_snapshot / list_sources / read_source / write_source`, `SnapshotInfo`
- Produces: HTTP `GET /api/projects/{name}/snapshots`, `POST /api/projects/{name}/snapshots/{snapshot_id}/restore` (복원된 Deck 반환), `GET /api/projects/{name}/sources`, `GET /api/projects/{name}/sources/{filename}` (`{"text": ...}`), `PUT /api/projects/{name}/sources/{filename}` (본문 `{"text": ...}`)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_snapshots_sources.py` 신규:

```python
import pytest
from fastapi.testclient import TestClient

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(FileProjectStore(tmp_path / "projects")))


def _save_title(client, title):
    deck = client.get("/api/projects/p1/deck").json()
    deck["meta"]["title"] = title
    assert client.put("/api/projects/p1/deck", json=deck).status_code == 200


def test_snapshot_list_and_restore(client):
    client.post("/api/projects", json={"name": "p1", "title": "v1"})
    _save_title(client, "v2")
    snaps = client.get("/api/projects/p1/snapshots").json()
    assert len(snaps) == 1 and snaps[0]["saved_at"]
    r = client.post(f"/api/projects/p1/snapshots/{snaps[0]['id']}/restore")
    assert r.status_code == 200
    assert r.json()["meta"]["title"] == "v1"
    assert client.get("/api/projects/p1/deck").json()["meta"]["title"] == "v1"


def test_restore_missing_snapshot_404(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.post("/api/projects/p1/snapshots/deck-19990101-000000-000000/restore")
    assert r.status_code == 404


def test_sources_round_trip(client):
    client.post("/api/projects", json={"name": "p1"})
    r = client.put("/api/projects/p1/sources/리서치.md", json={"text": "숫자 42"})
    assert r.status_code == 200
    assert client.get("/api/projects/p1/sources").json() == ["리서치.md"]
    assert client.get("/api/projects/p1/sources/리서치.md").json()["text"] == "숫자 42"


def test_source_missing_404(client):
    client.post("/api/projects", json={"name": "p1"})
    assert client.get("/api/projects/p1/sources/없음.md").status_code == 404
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api_snapshots_sources.py -q`
Expected: FAIL (404/405: 라우트 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/server/app.py`에 두 블록으로 나눠 추가한다.

모듈 수준(기존 `CreateProjectRequest` 옆)에:

```python
class SourceText(BaseModel):
    text: str
```

`create_app` 본문 안(기존 라우트들 다음)에:

```python
    @app.get("/api/projects/{name}/snapshots", response_model=list[SnapshotInfo])
    def list_snapshots(name: str):
        return store.list_snapshots(name)

    @app.post("/api/projects/{name}/snapshots/{snapshot_id}/restore", response_model=Deck)
    def restore_snapshot(name: str, snapshot_id: str):
        return store.restore_snapshot(name, snapshot_id)

    @app.get("/api/projects/{name}/sources", response_model=list[str])
    def list_sources(name: str):
        return store.list_sources(name)

    @app.get("/api/projects/{name}/sources/{filename}", response_model=SourceText)
    def read_source(name: str, filename: str):
        return SourceText(text=store.read_source(name, filename))

    @app.put("/api/projects/{name}/sources/{filename}", response_model=OkResponse)
    def write_source(name: str, filename: str, body: SourceText):
        store.write_source(name, filename, body.text)
        return OkResponse()
```

(`SnapshotInfo`를 storage import 줄에 추가한다.)

- [ ] **Step 4: 통과 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/slidecaptain/server/app.py backend/tests/test_api_snapshots_sources.py
git commit -m "feat: 스냅샷 복원과 입력 자료 엔드포인트"
```

---

### Task 7: CLI 정비: serve 서브커맨드, export 오류 안내, 자동 테스트 (이월 항목)

**Files:**
- Modify: `backend/slidecaptain/__main__.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `export_deck`(파일 래퍼), `create_app`, `FileProjectStore`
- Produces: CLI `python -m slidecaptain export <deck.json> [--out DIR]` (오류 시 종료 코드 1과 쉬운 말 안내), `python -m slidecaptain serve [--data-dir PATH] [--port N]` (127.0.0.1 바인딩)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_cli.py` 신규:

```python
import json

from slidecaptain.__main__ import main
from slidecaptain.models.deck import Deck, DeckMeta


def _write_deck(tmp_path):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(Deck(meta=DeckMeta(title="덱")).model_dump_json(), encoding="utf-8")
    return deck_path


def test_export_success(tmp_path, capsys):
    deck_path = _write_deck(tmp_path)
    rc = main(["export", str(deck_path), "--out", str(tmp_path / "exports")])
    assert rc == 0
    assert "내보내기 완료" in capsys.readouterr().out


def test_export_missing_file(tmp_path, capsys):
    rc = main(["export", str(tmp_path / "없는파일.json")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "찾을 수 없습니다" in err and "없는파일.json" in err


def test_export_broken_json(tmp_path, capsys):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text("{망가짐", encoding="utf-8")
    rc = main(["export", str(deck_path)])
    assert rc == 1
    assert "덱 파일을 읽지 못했습니다" in capsys.readouterr().err


def test_export_invalid_schema(tmp_path, capsys):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps({"meta": {}}), encoding="utf-8")
    rc = main(["export", str(deck_path)])
    assert rc == 1
    assert "덱 파일을 읽지 못했습니다" in capsys.readouterr().err


def test_export_out_dir_is_file(tmp_path, capsys):
    deck_path = _write_deck(tmp_path)
    blocker = tmp_path / "exports"
    blocker.write_text("파일임", encoding="utf-8")
    rc = main(["export", str(deck_path), "--out", str(blocker)])
    assert rc == 1
    assert "폴더" in capsys.readouterr().err


def test_serve_parser_defaults():
    # 서버를 띄우지 않고 인자 해석만 검증한다
    from slidecaptain.__main__ import build_parser

    args = build_parser().parse_args(["serve"])
    assert args.port == 8765
    assert args.data_dir.name == "slidecaptain-projects"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli.py -q`
Expected: FAIL (오류가 그대로 traceback으로 터지고, build_parser와 serve가 없음)

- [ ] **Step 3: 구현**

`backend/slidecaptain/__main__.py` 전체 교체:

```python
"""CLI.

- python -m slidecaptain export <deck.json> [--out DIR]
- python -m slidecaptain serve [--data-dir PATH] [--port N]
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from slidecaptain.export.exporter import export_deck


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slidecaptain")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export", help="deck.json을 PPTX로 내보낸다")
    p_export.add_argument("deck", type=Path)
    p_export.add_argument("--out", type=Path, default=None, help="내보내기 폴더 (기본: 덱 옆 exports/)")

    p_serve = sub.add_parser("serve", help="로컬 API 서버를 연다 (127.0.0.1 전용)")
    p_serve.add_argument("--data-dir", type=Path, default=Path.home() / "slidecaptain-projects")
    p_serve.add_argument("--port", type=int, default=8765)
    return parser


def _run_export(args) -> int:
    if not args.deck.exists():
        print(f"덱 파일을 찾을 수 없습니다: {args.deck}", file=sys.stderr)
        return 1
    out_dir = args.out if args.out is not None else args.deck.parent / "exports"
    if out_dir.exists() and not out_dir.is_dir():
        print(f"내보내기 위치가 폴더가 아닙니다: {out_dir}. 폴더 경로를 지정해 주세요.", file=sys.stderr)
        return 1
    try:
        result = export_deck(args.deck, out_dir)
    except (ValueError, ValidationError) as e:
        print(f"덱 파일을 읽지 못했습니다: {args.deck}\n원인: {e}", file=sys.stderr)
        return 1
    print(f"내보내기 완료: {result}")
    return 0


def _run_serve(args) -> int:
    import uvicorn

    from slidecaptain.server.app import create_app
    from slidecaptain.storage.file_store import FileProjectStore

    app = create_app(FileProjectStore(args.data_dir))
    print(f"프로젝트 폴더: {args.data_dir}")
    print(f"서버 주소: http://127.0.0.1:{args.port} (이 PC에서만 접근 가능)")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        return _run_export(args)
    return _run_serve(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

- [ ] **Step 5: 서버 기동 눈 확인 (수동 1회)**

Run: `.venv/Scripts/python.exe -m slidecaptain serve` 실행 후 브라우저에서 `http://127.0.0.1:8765/docs` 열기
Expected: FastAPI 문서 화면에 엔드포인트 목록이 보인다. Ctrl+C로 종료.

- [ ] **Step 6: 커밋**

```bash
git add backend/slidecaptain/__main__.py backend/tests/test_cli.py
git commit -m "feat: CLI serve 서브커맨드와 export 오류 안내, CLI 자동 테스트 (단계 1 이월)"
```

---

### Task 8: 타입 공유 파이프라인 (OpenAPI → TS 타입 자동 생성)

**Files:**
- Create: `backend/scripts/dump_openapi.py`
- Create: `frontend/package.json`
- Test: `backend/tests/test_openapi.py`
- 생성 산출물(커밋함): `backend/openapi.json`, `frontend/src/api/types.ts`, `frontend/package-lock.json`

**Interfaces:**
- Consumes: `create_app`, `FileProjectStore`
- Produces: `backend/openapi.json` (형식 진본의 기계 산출), `frontend/src/api/types.ts` (단계 4의 React 앱이 이 타입을 import한다). 갱신 절차는 이 태스크의 Step 5 명령 2개다

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_openapi.py` 신규:

```python
import pytest

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore


@pytest.fixture
def schema(tmp_path):
    return create_app(FileProjectStore(tmp_path / "projects")).openapi()


def test_openapi_contains_core_schemas(schema):
    names = schema["components"]["schemas"].keys()
    for required in ["Deck", "RenderPlan", "RenderStyle", "ProjectInfo", "SnapshotInfo"]:
        assert required in names, f"{required} 스키마가 OpenAPI에 없습니다"


def test_openapi_contains_all_routes(schema):
    paths = schema["paths"].keys()
    for route in [
        "/api/projects",
        "/api/projects/{name}/deck",
        "/api/projects/{name}/render-plan",
        "/api/projects/{name}/export",
        "/api/projects/{name}/snapshots",
        "/api/projects/{name}/snapshots/{snapshot_id}/restore",
        "/api/projects/{name}/sources",
        "/api/projects/{name}/sources/{filename}",
    ]:
        assert route in paths, f"{route} 경로가 OpenAPI에 없습니다"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/Scripts/python.exe -m pytest tests/test_openapi.py -q`
Expected: 앱이 이미 완성돼 있으므로 PASS가 정상이다. FAIL이면 Task 4~6의 누락을 먼저 고친다. (이 태스크의 실질 실패 대상은 아래 스크립트와 파이프라인이다)

- [ ] **Step 3: 덤프 스크립트 작성**

`backend/scripts/dump_openapi.py` 신규:

```python
"""OpenAPI 스키마를 backend/openapi.json으로 덤프한다.

실행: backend 폴더에서 .venv/Scripts/python.exe scripts/dump_openapi.py
프런트 타입 생성까지 한 번에 하려면 이어서:
  npm --prefix ../frontend run generate-types
"""

import json
import tempfile
from pathlib import Path

from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore

with tempfile.TemporaryDirectory() as tmp:
    schema = create_app(FileProjectStore(tmp)).openapi()

out = Path(__file__).resolve().parent.parent / "openapi.json"
out.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"기록 완료: {out}")
```

- [ ] **Step 4: frontend 패키지 작성**

`frontend/package.json` 신규:

```json
{
  "name": "slidecaptain-frontend",
  "private": true,
  "version": "0.0.0",
  "scripts": {
    "generate-types": "openapi-typescript ../backend/openapi.json -o src/api/types.ts"
  },
  "devDependencies": {
    "openapi-typescript": "^7.13.0"
  }
}
```

- [ ] **Step 5: 파이프라인 실행과 산출물 확인**

Run (backend 폴더): `.venv/Scripts/python.exe scripts/dump_openapi.py`
Expected: `기록 완료: ...backend/openapi.json`

Run (저장소 루트): `npm --prefix frontend install` 후 `npm --prefix frontend run generate-types`
Expected: `frontend/src/api/types.ts` 생성. 파일을 열어 `Deck`, `RenderPlan` 타입이 보이는지 확인 (openapi-typescript 7.13은 로드맵 기술 검증에서 동작 확인됨)

- [ ] **Step 6: 전체 확인 후 커밋**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

```bash
git add backend/scripts/dump_openapi.py backend/openapi.json backend/tests/test_openapi.py frontend/package.json frontend/package-lock.json frontend/src/api/types.ts
git commit -m "feat: 타입 공유 파이프라인 (OpenAPI 덤프와 TS 타입 자동 생성)"
```

---

### Task 9: 로드맵 정리와 마무리 확인

**Files:**
- Modify: `docs/plans/2026-08-27-mvp-roadmap.md`

**Interfaces:**
- Consumes: 없음 (문서 정리)
- Produces: 단계 2 완료 표시, 이월 항목의 소화 기록

- [ ] **Step 1: 전체 스위트와 수동 관통 확인**

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: 전체 PASS

Run: `.venv/Scripts/python.exe -m slidecaptain serve` 실행 후 브라우저 `http://127.0.0.1:8765/docs`에서 순서대로 실행해 본다: POST /api/projects (name: 관통확인) → PUT deck (장 1개 추가) → GET render-plan → POST export
Expected: 각 단계 200 응답, `~/slidecaptain-projects/관통확인/exports/`에 PPTX가 생기고 PowerPoint에서 열린다

- [ ] **Step 2: 로드맵 갱신**

`docs/plans/2026-08-27-mvp-roadmap.md`:
- 진행 상태의 단계 2 항목을 완료로 표시하고 날짜, 테스트 수를 기록한다
- 이월 표에서 이번에 소화한 4건(schema_version 검증, CLI 오류 안내와 테스트, 라이터 프리셋 인자 구조, 시각 리터럴 승격)의 처리 결과를 표시한다 (행 삭제 대신 "단계 2에서 처리" 표기)
- 단계 2 구현 중 새로 발견된 이월 사항이 있으면 표에 추가한다

- [ ] **Step 3: 커밋**

```bash
git add docs/plans/2026-08-27-mvp-roadmap.md
git commit -m "docs: 단계 2 완료 표시와 이월 사항 갱신"
```

- [ ] **Step 4: 브랜치 마무리**

superpowers:finishing-a-development-branch 스킬을 따라 사용자에게 머지, PR, 유지, 폐기 옵션을 제시한다.

---

## 자체 점검 기록 (계획 확정 전 수행)

- 적대 리뷰 반영 (2026-08-28, 3관점 병렬: 코드 정합성, 기술 사실 실증, 완결성. 발견 16건 = 고유 10건 전부 반영): write_pptx 호출부 3곳 전수 갱신, 이름 검증의 길이 한도와 테스트 데이터 일치, 끝 마침표 거부, MSO_SHAPE_TYPE 의존 제거(이름 기반 조회. python-pptx 실측: 테두리 없는 도형도 line.width가 0을 반환), 원자성 고정 테스트 추가, ProjectStore Protocol 신설(설계서 2.2 인터페이스 명시 조항 준수), 스니펫 배치 지시 명확화, 고아 import 정리 지시.

- 설계서 커버리지: 3.1 프로젝트 폴더(Task 3), 2.2 저장소 인터페이스(Task 3), 7.2 원자적 쓰기와 스냅샷과 복구 경로(Task 3, 6), 2.1 타입 공유(Task 8), 로드맵 단계 2 범위 전부. 복구 "메뉴"(화면)는 단계 4의 편집 화면 몫이고, 이 단계는 복구 API까지 제공한다.
- 이월 항목 4건: Task 1(schema_version), Task 2(프리셋 인자 구조 + 시각 리터럴), Task 7(CLI). Global Constraints에 대응 표기.
- 타입 일관성: `write_pptx(plan, out_path)` 시그니처 변경은 Task 2에서 정의하고 Task 5의 exporter 분리가 같은 시그니처를 쓴다. `FileProjectStore`의 메서드 이름은 Task 3 정의와 Task 4~6 사용이 일치한다.

