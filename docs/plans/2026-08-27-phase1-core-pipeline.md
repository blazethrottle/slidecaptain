# 단계 1: 결정론 코어 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `deck.json`을 입력하면 방법론 규칙(어절 줄바꿈, 크기 하한, 균일 배치, 역할 태깅)을 지킨 PPTX가 나오는 파이썬 패키지와 CLI를 만든다.

**Architecture:** 프리셋(모든 시각 수치의 진본) → 폰트 실측(fontTools) → 레이아웃 엔진(덱 + 프리셋 → 렌더 계획) → PPTX 라이터(렌더 계획 → 파일)의 단방향 파이프라인. 좌표와 글자 크기는 데이터에 존재하지 않고 항상 프리셋에서 계산된다. 라이터는 렌더 계획만 소비하므로, 이후 단계의 화면 미리보기가 같은 렌더 계획 JSON을 공유한다.

**Tech Stack:** Python 3.13, pydantic v2, python-pptx, fontTools, pytest

## Global Constraints

- 진본 형식: 구조화 데이터(deck.json). 좌표와 글자 크기는 데이터에 없다 (설계서 3.2)
- 글자 하한: 본문(불릿, 박스, 표) 12pt, 각주 9pt. 하한 미달 프리셋은 검증 오류 (설계서 3.3)
- 오버플로 시 글자 크기 축소 금지: 자동 맞춤(autofit) 항상 꺼짐, 해소는 내용 조정으로 (설계서 5.3)
- 균일 배치: 같은 역할 요소는 모든 장에서 같은 위치. 상단 기준선 정렬, 세로 중앙 정렬 금지 (설계서 5.4)
- 본문 영역(제목, 쪽번호 제외)의 글자 크기 단계는 페이지당 2개 이하. 표지와 간지는 예외 (설계서 5.4)
- 모든 텍스트 run에 `lang="ko-KR"` 주입 (설계서 7.1)
- 모든 도형에 역할 태깅: 도형 이름 = `장ID:슬롯` (설계서 7.1)
- 파일 처리는 ASCII 임시 경로 경유, 내보내기는 덮어쓰지 않고 새 버전 파일 (설계서 7.1)
- 코어는 Windows와 macOS 모두 동작: OS 전용 API(COM 등) 사용 금지, 폰트 부재 시 번들 수치로 동작 (설계서 9.1)
- 내보내기 전후 deck.json 불변 (설계서 8)
- 페이지 규격 16:9 = 960 x 540pt = 12,192,000 x 6,858,000 EMU. 내부 계산은 pt, 라이터에서 EMU 변환 (1pt = 12,700 EMU)
- 생성 텍스트에 엠대시(U+2014)와 중점(U+00B7)을 쓰지 않는다 (사용자 전역 규칙. 불릿 마커 글리프 U+2022는 문장 부호가 아니라 목록 표식이므로 예외)
- TDD: 모든 태스크는 실패하는 테스트부터. 커밋은 태스크 단위
- 작업 브랜치: 실행 시작 시 `feature/phase1-core-pipeline` 브랜치를 만들어 진행한다 (superpowers:using-git-worktrees)

## 파일 구조 (이 계획이 만드는 것)

```
backend/
  pyproject.toml
  slidecaptain/
    __init__.py
    models/
      __init__.py
      preset.py        # 프리셋: 모든 시각 수치의 진본 + 하한 검증 + 덮어쓰기 병합
      deck.py          # deck.json 스키마 (메타, 구조안, 슬라이드 슬롯 union)
      render.py        # 렌더 계획: 엔진의 출력이자 라이터와 미리보기의 입력
    metrics/
      __init__.py
      font_metrics.py  # 글자 폭 데이터 로더 (TTF 실측 또는 번들 JSON)
      line_breaker.py  # 어절 단위 줄바꿈 계산 (결정론)
      capacity.py      # 용량 계약 역산과 분량 실측
      assets/
        malgun_metrics.json  # 맑은 고딕 폭 수치 (재배포 가능한 수치 데이터만)
    layout/
      __init__.py
      templates.py     # 템플릿 6종: 슬롯 → 프레임 수식
      engine.py        # 덱 + 프리셋 + 실측 → RenderPlan + 용량 경고
    export/
      __init__.py
      pptx_writer.py   # RenderPlan → python-pptx (ko-KR, 역할 태깅, autofit off)
      exporter.py      # 파일 오케스트레이션 (ASCII 임시 경로, 버전 파일명)
    __main__.py        # CLI: python -m slidecaptain export <deck.json>
  scripts/
    extract_font_metrics.py  # 폰트 파일 → assets JSON 생성 (Windows에서 1회 실행)
  samples/
    sample_deck.json   # 템플릿 6종을 전부 쓰는 견본 덱
  tests/
    test_preset.py
    test_deck_schema.py
    test_font_metrics.py
    test_line_breaker.py
    test_capacity.py
    test_layout_engine.py
    test_pptx_writer.py
    test_table_render.py
    test_exporter.py
    test_regression.py
.gitignore
```

---

### Task 1: 패키지 뼈대 + 프리셋 모델

**Files:**
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/slidecaptain/__init__.py`, `backend/slidecaptain/models/__init__.py`, `backend/slidecaptain/models/preset.py`
- Test: `backend/tests/test_preset.py`

**Interfaces:**
- Produces: `Preset` (pydantic 모델. 필드: `fonts: Fonts`, `font_roles: FontRoles`, `colors: Colors`, `spacing: Spacing`, `page_width_pt: float = 960.0`, `page_height_pt: float = 540.0`, `language: str = "ko-KR"`), `apply_overrides(base: Preset, overrides: dict) -> Preset`, 상수 `BODY_MIN_PT = 12.0`, `FOOTNOTE_MIN_PT = 9.0`

- [ ] **Step 1: 개발 환경 구성**

```powershell
python -m venv backend/.venv
```

- [ ] **Step 2: 설정 파일 작성**

`.gitignore`:

```gitignore
backend/.venv/
__pycache__/
*.pyc
.pytest_cache/
projects/
backend/tests/_out/
node_modules/
frontend/dist/
```

`backend/pyproject.toml`:

```toml
[project]
name = "slidecaptain"
version = "0.1.0"
description = "보고 슬라이드(PPTX) 제작 로컬 웹앱: 결정론 코어"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2.9",
    "python-pptx==1.0.2",
    "fonttools>=4.63",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["slidecaptain*"]

[tool.setuptools.package-data]
"slidecaptain.metrics" = ["assets/*.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`backend/slidecaptain/__init__.py` 와 `backend/slidecaptain/models/__init__.py` 는 빈 파일로 만든다.

```powershell
backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"
```

Expected: `Successfully installed ... slidecaptain-0.1.0`

- [ ] **Step 3: 실패하는 테스트 작성**

`backend/tests/test_preset.py`:

```python
import pytest
from pydantic import ValidationError

from slidecaptain.models.preset import (
    BODY_MIN_PT,
    FOOTNOTE_MIN_PT,
    Preset,
    apply_overrides,
)


def test_default_preset_values():
    p = Preset()
    assert p.page_width_pt == 960.0
    assert p.page_height_pt == 540.0
    assert p.language == "ko-KR"
    assert p.fonts.korean == "맑은 고딕"
    assert p.font_roles.body_pt == 12.0
    assert p.font_roles.title_pt == 20.0
    assert p.font_roles.footnote_pt == 9.0
    assert p.spacing.margin_left == 50.0
    assert p.spacing.line_spacing == 1.4


def test_body_floor_enforced():
    # 본문 하한 12pt: 미달 프리셋은 만들 수 없다
    with pytest.raises(ValidationError):
        Preset.model_validate({"font_roles": {"body_pt": 11.0}})
    with pytest.raises(ValidationError):
        Preset.model_validate({"font_roles": {"table_pt": 10.0}})
    with pytest.raises(ValidationError):
        Preset.model_validate({"font_roles": {"box_pt": 11.5}})


def test_footnote_floor_enforced():
    with pytest.raises(ValidationError):
        Preset.model_validate({"font_roles": {"footnote_pt": 8.0}})


def test_apply_overrides_partial():
    base = Preset()
    merged = apply_overrides(base, {"font_roles": {"body_pt": 13.0}})
    assert merged.font_roles.body_pt == 13.0
    # 건드리지 않은 값은 유지된다
    assert merged.font_roles.title_pt == base.font_roles.title_pt
    assert merged.spacing.margin_left == base.spacing.margin_left
    # 원본은 불변이다
    assert base.font_roles.body_pt == 12.0


def test_apply_overrides_rejects_floor_violation():
    with pytest.raises(ValidationError):
        apply_overrides(Preset(), {"font_roles": {"body_pt": 10.0}})


def test_preset_roundtrip_json():
    p = Preset()
    p2 = Preset.model_validate_json(p.model_dump_json())
    assert p2 == p
```

- [ ] **Step 4: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_preset.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'slidecaptain.models.preset'`)

- [ ] **Step 5: 구현**

`backend/slidecaptain/models/preset.py`:

```python
"""프리셋: 모든 시각 수치의 단일 진본.

좌표와 글자 크기는 덱 데이터에 존재하지 않고, 항상 이 프리셋의 수치에서
레이아웃 엔진이 수식으로 계산한다 (설계서 5.4).
"""

from typing import Any

from pydantic import BaseModel, model_validator

BODY_MIN_PT = 12.0
FOOTNOTE_MIN_PT = 9.0


class Fonts(BaseModel):
    korean: str = "맑은 고딕"
    latin: str = "맑은 고딕"


class FontRoles(BaseModel):
    cover_title_pt: float = 28.0
    section_title_pt: float = 24.0
    title_pt: float = 20.0
    subtitle_pt: float = 14.0
    body_pt: float = 12.0
    box_pt: float = 12.0
    table_pt: float = 12.0
    footnote_pt: float = 9.0
    page_number_pt: float = 9.0

    @model_validator(mode="after")
    def enforce_floors(self) -> "FontRoles":
        # 하한 규칙: 분량이 넘치면 글자가 아니라 내용을 줄인다 (설계서 1.2)
        for name in ("body_pt", "box_pt", "table_pt"):
            if getattr(self, name) < BODY_MIN_PT:
                raise ValueError(f"{name}은 본문 하한 {BODY_MIN_PT}pt 아래로 내릴 수 없습니다")
        for name in ("footnote_pt", "page_number_pt"):
            if getattr(self, name) < FOOTNOTE_MIN_PT:
                raise ValueError(f"{name}은 각주 하한 {FOOTNOTE_MIN_PT}pt 아래로 내릴 수 없습니다")
        return self


class Colors(BaseModel):
    """색상은 알파 없는 6자리 16진수 문자열."""

    text: str = "202020"
    accent: str = "1F4E79"
    box_fill: str = "EEF3F9"
    table_header_fill: str = "F2F2F2"
    border: str = "D0D7E2"
    background: str = "FFFFFF"


class Spacing(BaseModel):
    margin_left: float = 50.0
    margin_right: float = 50.0
    margin_top: float = 36.0
    margin_bottom: float = 34.0
    title_height: float = 40.0
    title_gap: float = 16.0
    footnote_height: float = 24.0
    footnote_gap: float = 8.0
    box_height: float = 56.0
    box_gap: float = 8.0
    box_padding: float = 10.0
    summary_box_gap: float = 12.0
    line_spacing: float = 1.4
    bullet_gap: float = 6.0
    bullet_indent: float = 18.0
    card_gap: float = 20.0
    card_heading_height: float = 24.0
    card_heading_gap: float = 8.0
    cover_indent: float = 30.0
    table_min_col_width: float = 60.0
    table_cell_pad_x: float = 6.0
    table_cell_pad_y: float = 3.0
    page_number_width: float = 60.0
    page_number_height: float = 16.0
    page_number_bottom: float = 28.0
    safety_ratio: float = 0.97


class Preset(BaseModel):
    fonts: Fonts = Fonts()
    font_roles: FontRoles = FontRoles()
    colors: Colors = Colors()
    spacing: Spacing = Spacing()
    page_width_pt: float = 960.0
    page_height_pt: float = 540.0
    language: str = "ko-KR"


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def apply_overrides(base: Preset, overrides: dict[str, Any]) -> Preset:
    """전역 프리셋 위에 덱별 덮어쓰기를 얹는다 (설계서 3.3). 하한 검증이 다시 걸린다."""
    return Preset.model_validate(_deep_merge(base.model_dump(), overrides))
```

- [ ] **Step 6: 통과 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_preset.py -q`
Expected: `6 passed`

- [ ] **Step 7: 커밋**

```bash
git add .gitignore backend/pyproject.toml backend/slidecaptain backend/tests/test_preset.py
git commit -m "feat: 패키지 뼈대와 프리셋 모델 (크기 하한 검증, 덮어쓰기 병합)"
```

---

### Task 2: deck.json 스키마

**Files:**
- Create: `backend/slidecaptain/models/deck.py`
- Test: `backend/tests/test_deck_schema.py`

**Interfaces:**
- Consumes: 없음 (독립 모델)
- Produces: `Deck`(필드 `schema_version: int`, `meta: DeckMeta`, `structure: Structure`, `slides: list[Slide]`), `DeckMeta(title, report_type, audience, preset_overrides)`, `Structure(chapters: list[Chapter])`, `Chapter(id, topic, conclusion, template, source_refs)`, `Slide(chapter_id, slots)`, 슬롯 union `Slots` = `CoverSlots | SummarySlots | BulletBoxSlots | TableSlots | CompareSlots | DividerSlots` (discriminator `template`), `Bullet(text, level)`, `Card(heading, bullets)`, 상수 `SCHEMA_VERSION = 1`, 타입 `TemplateName`, `ReportType`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_deck_schema.py`:

```python
import pytest
from pydantic import ValidationError

from slidecaptain.models.deck import (
    SCHEMA_VERSION,
    Bullet,
    BulletBoxSlots,
    Chapter,
    Deck,
    DeckMeta,
    Slide,
    Structure,
    TableSlots,
)


def _minimal_deck() -> Deck:
    return Deck(
        meta=DeckMeta(title="시장 조사 보고"),
        structure=Structure(
            chapters=[
                Chapter(id="ch01", topic="조사 개요", conclusion="조사 범위는 3개국", template="bullet_box"),
            ]
        ),
        slides=[
            Slide(
                chapter_id="ch01",
                slots=BulletBoxSlots(
                    bullets=[Bullet(text="대상: 3개국 주요 사업자"), Bullet(text="기간: 4주", level=1)],
                    conclusion="조사 범위는 3개국 주요 사업자",
                ),
            )
        ],
    )


def test_deck_roundtrip():
    deck = _minimal_deck()
    restored = Deck.model_validate_json(deck.model_dump_json())
    assert restored == deck
    assert restored.schema_version == SCHEMA_VERSION


def test_slots_discriminated_by_template():
    deck = _minimal_deck()
    data = deck.model_dump()
    parsed = Deck.model_validate(data)
    assert isinstance(parsed.slides[0].slots, BulletBoxSlots)


def test_unknown_template_rejected():
    deck = _minimal_deck().model_dump()
    deck["slides"][0]["slots"]["template"] = "fancy_chart"
    with pytest.raises(ValidationError):
        Deck.model_validate(deck)


def test_table_row_width_must_match_columns():
    with pytest.raises(ValidationError):
        TableSlots(columns=["항목", "내용"], rows=[["하나"]])


def test_bullet_level_limited():
    with pytest.raises(ValidationError):
        Bullet(text="깊은 불릿", level=2)


def test_report_type_restricted():
    with pytest.raises(ValidationError):
        DeckMeta(title="x", report_type="poem")
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_deck_schema.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'slidecaptain.models.deck'`)

- [ ] **Step 3: 구현**

`backend/slidecaptain/models/deck.py`:

```python
"""deck.json 스키마 (설계서 3.2).

슬라이드에는 템플릿 유형과 슬롯 내용만 있다. 좌표와 글자 크기는 데이터에 없다.
본문 장의 제목 텍스트는 슬롯이 아니라 구조안의 chapter.topic에서 온다 (주제형 제목).
"""

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1

TemplateName = Literal["cover", "summary", "bullet_box", "table", "compare2", "divider"]
ReportType = Literal["research", "approval", "strategy"]


class Bullet(BaseModel):
    text: str
    level: Literal[0, 1] = 0


class Card(BaseModel):
    heading: str
    bullets: list[Bullet] = []


class CoverSlots(BaseModel):
    template: Literal["cover"] = "cover"
    title: str
    subtitle: str = ""
    date: str = ""
    audience: str = ""


class SummarySlots(BaseModel):
    template: Literal["summary"] = "summary"
    conclusion: str
    points: list[Bullet] = []


class BulletBoxSlots(BaseModel):
    template: Literal["bullet_box"] = "bullet_box"
    bullets: list[Bullet] = []
    conclusion: str
    footnote: str = ""


class TableSlots(BaseModel):
    template: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]
    footnote: str = ""

    @model_validator(mode="after")
    def rows_match_columns(self) -> "TableSlots":
        for i, row in enumerate(self.rows):
            if len(row) != len(self.columns):
                raise ValueError(f"{i}번째 행의 칸 수({len(row)})가 열 수({len(self.columns)})와 다릅니다")
        return self


class CompareSlots(BaseModel):
    template: Literal["compare2"] = "compare2"
    left: Card
    right: Card
    conclusion: str


class DividerSlots(BaseModel):
    template: Literal["divider"] = "divider"
    section_no: str = ""
    section_title: str


Slots = Annotated[
    Union[CoverSlots, SummarySlots, BulletBoxSlots, TableSlots, CompareSlots, DividerSlots],
    Field(discriminator="template"),
]


class Chapter(BaseModel):
    id: str
    topic: str
    conclusion: str = ""
    template: TemplateName
    source_refs: list[str] = []


class Structure(BaseModel):
    chapters: list[Chapter] = []


class Slide(BaseModel):
    chapter_id: str
    slots: Slots


class DeckMeta(BaseModel):
    title: str
    report_type: ReportType = "research"
    audience: str = ""
    preset_overrides: dict[str, Any] = {}


class Deck(BaseModel):
    schema_version: int = SCHEMA_VERSION
    meta: DeckMeta
    structure: Structure = Structure()
    slides: list[Slide] = []
```

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_deck_schema.py -q`
Expected: `6 passed`

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/models/deck.py backend/tests/test_deck_schema.py
git commit -m "feat: deck.json 스키마 (템플릿 6종 슬롯 union, 좌표 없는 데이터 모델)"
```

---

### Task 3: 폰트 폭 실측기

**Files:**
- Create: `backend/slidecaptain/metrics/__init__.py`, `backend/slidecaptain/metrics/font_metrics.py`, `backend/scripts/extract_font_metrics.py`, `backend/slidecaptain/metrics/assets/malgun_metrics.json` (스크립트 실행으로 생성)
- Test: `backend/tests/test_font_metrics.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `FaceMetrics` (폭 데이터 한 벌. 메서드 `width_pt(text: str, font_pt: float) -> float`)
  - `FontMetrics` (레귤러와 볼드 두 벌 묶음. 메서드 `face(bold: bool) -> FaceMetrics`, 클래스메서드 `from_ttf(regular_path, bold_path) -> FontMetrics`, `from_bundled() -> FontMetrics`, `load_default() -> FontMetrics`)

설계 결정 두 가지 (2026-08-27 실측 검증 근거):
1. 맑은 고딕 폰트 파일은 재배포할 수 없으므로, 폭 수치(정수 데이터)만 JSON으로 추출해 패키지에 번들한다. 폰트 파일이 있는 환경(이 PC)에서는 실측 로드도 가능하고, 없는 환경(macOS 등)에서는 번들 수치로 같은 결과를 낸다.
2. 볼드는 별도 폭 데이터로 잰다. 실측 결과 한글 음절 11,172자는 레귤러와 볼드 모두 정확히 1em(2048/2048)으로 균일하지만, 영문은 볼드에서 더 넓다(W가 1953 대 2068). 제목, 결론 박스, 표 머리글이 굵은 글자이므로 레귤러 폭으로 재면 과소 측정이 된다. 커닝은 무시한다(한글 커닝 쌍 0건으로 정확하고, 영문은 대부분 음수 커닝이라 과대 측정 쪽이며, 소수의 양수 쌍은 안전 여유율이 흡수한다).

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_font_metrics.py`:

```python
from pathlib import Path

import pytest

from slidecaptain.metrics.font_metrics import FontMetrics

MALGUN = Path("C:/Windows/Fonts/malgun.ttf")
MALGUN_BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")


def test_bundled_metrics_load_both_faces():
    m = FontMetrics.from_bundled()
    assert m.face(False).width_pt("가", 12.0) > 0
    assert m.face(True).width_pt("가", 12.0) > 0


def test_hangul_is_exactly_one_em_in_both_faces():
    # 실측 검증(2026-08-27): 한글 음절은 레귤러와 볼드 모두 2048/2048 = 1em
    m = FontMetrics.from_bundled()
    assert m.face(False).width_pt("가", 12.0) == pytest.approx(12.0)
    assert m.face(True).width_pt("가", 12.0) == pytest.approx(12.0)
    assert m.face(False).width_pt("늬", 12.0) == pytest.approx(12.0)


def test_width_scales_linearly_with_font_size():
    face = FontMetrics.from_bundled().face(False)
    assert face.width_pt("가나다", 24.0) == pytest.approx(2 * face.width_pt("가나다", 12.0))


def test_width_additive_over_chars():
    face = FontMetrics.from_bundled().face(False)
    assert face.width_pt("가가", 12.0) == pytest.approx(2 * face.width_pt("가", 12.0))


def test_latin_is_proportional_and_narrower_than_hangul():
    face = FontMetrics.from_bundled().face(False)
    assert face.width_pt("iiii", 12.0) < face.width_pt("WWWW", 12.0)
    assert face.width_pt("a", 12.0) < face.width_pt("가", 12.0)


def test_bold_latin_wider_than_regular():
    # 실측 검증(2026-08-27): W는 레귤러 1953, 볼드 2068 유닛
    m = FontMetrics.from_bundled()
    assert m.face(True).width_pt("W", 12.0) > m.face(False).width_pt("W", 12.0)


def test_unknown_char_falls_back_to_safe_width():
    face = FontMetrics.from_bundled().face(False)
    # 수집 범위 밖의 글자도 1em 폭으로 계산된다 (과소 측정 방지)
    assert face.width_pt("\u2603", 12.0) == pytest.approx(12.0)  # SNOWMAN: 번들에 없는 글자


@pytest.mark.skipif(not (MALGUN.exists() and MALGUN_BOLD.exists()), reason="맑은 고딕이 없는 환경")
def test_bundled_matches_live_ttf():
    live = FontMetrics.from_ttf(MALGUN, MALGUN_BOLD)
    bundled = FontMetrics.from_bundled()
    for bold in (False, True):
        for text in ("가나다", "Market 12,300", "요약: 결론 우선"):
            assert bundled.face(bold).width_pt(text, 12.0) == pytest.approx(
                live.face(bold).width_pt(text, 12.0)
            )
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_font_metrics.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`backend/slidecaptain/metrics/__init__.py` 는 빈 파일. `backend/slidecaptain/metrics/font_metrics.py`:

```python
"""글자 폭 데이터: 실제 폰트의 advance width로 줄바꿈 지점을 결정론적으로 계산한다 (설계서 5.2).

폭 공식: width_pt = advance / unitsPerEm * font_size_pt
레귤러(malgun.ttf)와 볼드(malgunbd.ttf)는 영문 폭이 다르므로 두 벌을 따로 잰다.
"""

import json
from importlib import resources
from pathlib import Path

HANGUL_START = 0xAC00
HANGUL_END = 0xD7A3

# ASCII 전체 + 자주 나오는 기호 (엔대시, 줄임표, 원화)
_COLLECT_CODEPOINTS = list(range(0x20, 0x7F)) + [0x2013, 0x2026, 0x20A9]

_MALGUN = Path("C:/Windows/Fonts/malgun.ttf")
_MALGUN_BOLD = Path("C:/Windows/Fonts/malgunbd.ttf")


class FaceMetrics:
    """폭 데이터 한 벌 (레귤러 또는 볼드)."""

    def __init__(
        self,
        upem: int,
        widths: dict[int, int],
        hangul_uniform_width: int | None,
        fallback_width: int,
    ) -> None:
        self.upem = upem
        self.widths = widths
        self.hangul_uniform_width = hangul_uniform_width
        self.fallback_width = fallback_width

    def _advance(self, codepoint: int) -> int:
        if HANGUL_START <= codepoint <= HANGUL_END and self.hangul_uniform_width is not None:
            return self.hangul_uniform_width
        return self.widths.get(codepoint, self.fallback_width)

    def width_pt(self, text: str, font_pt: float) -> float:
        units = sum(self._advance(ord(ch)) for ch in text)
        return units / self.upem * font_pt

    @classmethod
    def from_ttf_file(cls, path: str | Path) -> "FaceMetrics":
        from fontTools.ttLib import TTFont

        font = TTFont(str(path))
        upem = font["head"].unitsPerEm
        cmap = font.getBestCmap()
        hmtx = font["hmtx"]

        widths: dict[int, int] = {}
        for cp in _COLLECT_CODEPOINTS:
            glyph = cmap.get(cp)
            if glyph is not None:
                widths[cp] = hmtx[glyph][0]

        # 한글 음절 폭: 전부 같으면 값 하나로 압축, 다르면 전체 표를 보관
        hangul_widths = {
            cp: hmtx[cmap[cp]][0] for cp in range(HANGUL_START, HANGUL_END + 1) if cp in cmap
        }
        distinct = set(hangul_widths.values())
        if len(distinct) == 1:
            hangul_uniform = distinct.pop()
        else:
            hangul_uniform = None
            widths.update(hangul_widths)

        fallback = hangul_uniform if hangul_uniform is not None else max(distinct)
        return cls(upem, widths, hangul_uniform, fallback)

    def to_dict(self) -> dict:
        return {
            "upem": self.upem,
            "widths": {str(k): v for k, v in self.widths.items()},
            "hangul_uniform_width": self.hangul_uniform_width,
            "fallback_width": self.fallback_width,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FaceMetrics":
        return cls(
            upem=data["upem"],
            widths={int(k): v for k, v in data["widths"].items()},
            hangul_uniform_width=data["hangul_uniform_width"],
            fallback_width=data["fallback_width"],
        )


class FontMetrics:
    """레귤러와 볼드 폭 데이터 묶음."""

    def __init__(self, regular: FaceMetrics, bold: FaceMetrics) -> None:
        self.regular = regular
        self.bold = bold

    def face(self, bold: bool) -> FaceMetrics:
        return self.bold if bold else self.regular

    @classmethod
    def from_ttf(cls, regular_path: str | Path, bold_path: str | Path) -> "FontMetrics":
        return cls(
            regular=FaceMetrics.from_ttf_file(regular_path),
            bold=FaceMetrics.from_ttf_file(bold_path),
        )

    @classmethod
    def from_bundled(cls) -> "FontMetrics":
        raw = resources.files("slidecaptain.metrics").joinpath("assets/malgun_metrics.json").read_text("utf-8")
        data = json.loads(raw)
        return cls(
            regular=FaceMetrics.from_dict(data["regular"]),
            bold=FaceMetrics.from_dict(data["bold"]),
        )

    @classmethod
    def load_default(cls) -> "FontMetrics":
        """폰트 파일이 있으면 실측, 없으면 번들 수치 (코어의 OS 무관 동작 보장)."""
        if _MALGUN.exists() and _MALGUN_BOLD.exists():
            return cls.from_ttf(_MALGUN, _MALGUN_BOLD)
        return cls.from_bundled()

    def to_json(self) -> str:
        return json.dumps(
            {"regular": self.regular.to_dict(), "bold": self.bold.to_dict()},
            ensure_ascii=True,
        )
```

`backend/scripts/extract_font_metrics.py`:

```python
"""맑은 고딕(레귤러, 볼드) 폭 수치를 패키지 자산 JSON으로 추출한다 (Windows에서 1회 실행)."""

from pathlib import Path

from slidecaptain.metrics.font_metrics import FontMetrics

OUT = Path(__file__).resolve().parents[1] / "slidecaptain" / "metrics" / "assets" / "malgun_metrics.json"

if __name__ == "__main__":
    metrics = FontMetrics.from_ttf("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(metrics.to_json(), encoding="utf-8")
    print(f"저장: {OUT}")
    print(f"레귤러 한글 균일 폭={metrics.regular.hangul_uniform_width}, 볼드={metrics.bold.hangul_uniform_width}")
```

- [ ] **Step 4: 자산 생성 후 통과 확인**

```powershell
backend/.venv/Scripts/python.exe backend/scripts/extract_font_metrics.py
```

Expected: `저장: ...malgun_metrics.json` 출력과 파일 생성.

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_font_metrics.py -q`
Expected: `8 passed`

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/metrics backend/scripts/extract_font_metrics.py backend/tests/test_font_metrics.py
git commit -m "feat: 폰트 폭 실측기 (fontTools 추출 + 번들 수치, OS 무관 동작)"
```

---

### Task 4: 어절 줄바꿈 계산기

**Files:**
- Create: `backend/slidecaptain/metrics/line_breaker.py`
- Test: `backend/tests/test_line_breaker.py`

**Interfaces:**
- Consumes: `FontMetrics.width_pt(text, font_pt)` (Task 3)
- Produces: `break_paragraph(text: str, max_width_pt: float, font_pt: float, metrics, safety_ratio: float = 1.0) -> list[str]` (metrics는 `width_pt`를 가진 객체면 무엇이든 받는다: 테스트에서는 가짜 실측기 사용)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_line_breaker.py`:

```python
from slidecaptain.metrics.line_breaker import break_paragraph


class FakeMetrics:
    """글자 하나 = font_pt 만큼의 폭. 폭 10pt 글자 10개 = 100pt 식으로 셈이 쉬운 가짜."""

    def width_pt(self, text: str, font_pt: float) -> float:
        return len(text) * font_pt


FAKE = FakeMetrics()


def test_greedy_word_wrap():
    # 폭 한도 100pt, 글자당 10pt: 한 줄에 10글자 (공백 포함)
    lines = break_paragraph("가나다 라마바 사아자차카타", 100.0, 10.0, FAKE)
    assert lines == ["가나다 라마바", "사아자차카타"]


def test_single_short_line_unchanged():
    assert break_paragraph("짧은 문장", 100.0, 10.0, FAKE) == ["짧은 문장"]


def test_long_word_splits_by_char():
    # 14글자 한 어절: 10글자에서 쪼개진다
    lines = break_paragraph("가나다라마바사아자차카타파하", 100.0, 10.0, FAKE)
    assert lines == ["가나다라마바사아자차", "카타파하"]


def test_newline_forces_break():
    lines = break_paragraph("첫 줄\n둘째 줄", 100.0, 10.0, FAKE)
    assert lines == ["첫 줄", "둘째 줄"]


def test_empty_text_is_one_line():
    assert break_paragraph("", 100.0, 10.0, FAKE) == [""]


def test_safety_ratio_shrinks_budget():
    # 여유율 0.5 → 실효 한도 50pt = 5글자
    lines = break_paragraph("가나다 라마바", 100.0, 10.0, FAKE, safety_ratio=0.5)
    assert lines == ["가나다", "라마바"]


def test_multiple_spaces_collapse_into_word_split():
    lines = break_paragraph("하나  둘", 100.0, 10.0, FAKE)
    assert lines == ["하나 둘"]
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_line_breaker.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`backend/slidecaptain/metrics/line_breaker.py`:

```python
"""어절(공백) 단위 탐욕 줄바꿈. PowerPoint의 ko-KR 어절 줄바꿈과 같은 규칙을 코드로 재현한다.

여기서 계산한 줄수는 용량 검증에 쓰고, 실제 줄바꿈은 PowerPoint가 수행한다
(강제 개행을 심지 않으므로 내보낸 파일을 나중에 손으로 고치기 쉽다).
"""


def _split_long_word(word: str, budget_pt: float, font_pt: float, metrics) -> list[str]:
    parts: list[str] = []
    current = ""
    for ch in word:
        if current and metrics.width_pt(current + ch, font_pt) > budget_pt:
            parts.append(current)
            current = ch
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def break_paragraph(
    text: str,
    max_width_pt: float,
    font_pt: float,
    metrics,
    safety_ratio: float = 1.0,
) -> list[str]:
    budget = max_width_pt * safety_ratio
    lines: list[str] = []
    for raw_line in text.split("\n"):
        current = ""
        for word in [w for w in raw_line.split(" ") if w]:
            if metrics.width_pt(word, font_pt) > budget:
                # 한 어절이 한 줄을 넘으면 글자 단위로 쪼갠다
                if current:
                    lines.append(current)
                parts = _split_long_word(word, budget, font_pt, metrics)
                lines.extend(parts[:-1])
                current = parts[-1]
            elif not current:
                current = word
            elif metrics.width_pt(current + " " + word, font_pt) <= budget:
                current = current + " " + word
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines
```

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_line_breaker.py -q`
Expected: `7 passed`

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/metrics/line_breaker.py backend/tests/test_line_breaker.py
git commit -m "feat: 어절 단위 줄바꿈 계산기 (결정론, 안전 여유율)"
```

---

### Task 5: 용량 계약과 분량 실측

**Files:**
- Create: `backend/slidecaptain/metrics/capacity.py`
- Test: `backend/tests/test_capacity.py`

**Interfaces:**
- Consumes: `break_paragraph` (Task 4), `Preset` (Task 1), `Bullet` (Task 2)
- Produces:
  - `line_height_pt(font_pt: float, line_spacing: float) -> float`
  - `max_lines(area_height_pt: float, font_pt: float, line_spacing: float) -> int`
  - `measure_lines(text: str, area_width_pt: float, font_pt: float, face, spacing: Spacing) -> int` (문단 하나의 실측 줄수. `face`는 `width_pt(text, font_pt)`를 가진 객체: `FaceMetrics` 또는 테스트 가짜)
  - `measure_bullets(bullets: list[Bullet], area_width_pt: float, font_pt: float, face, spacing: Spacing) -> BulletsMeasure` (`BulletsMeasure`는 pydantic 모델: `total_height_pt: float`, `lines_per_bullet: list[int]`)
  - `capacity_contract(template: str, preset: Preset) -> dict[str, int]` (AI 생성의 계약 조건으로 쓸 슬롯별 한도. 줄수 역산이라 폭 실측기가 필요 없다. 단계 3의 프롬프트가 소비)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_capacity.py`:

```python
import pytest

from slidecaptain.metrics.capacity import (
    BulletsMeasure,
    capacity_contract,
    line_height_pt,
    max_lines,
    measure_bullets,
    measure_lines,
)
from slidecaptain.models.deck import Bullet
from slidecaptain.models.preset import Preset


class FakeFace:
    def width_pt(self, text: str, font_pt: float) -> float:
        return len(text) * font_pt


FAKE = FakeFace()
PRESET = Preset()


def test_line_height():
    assert line_height_pt(12.0, 1.4) == pytest.approx(16.8)


def test_max_lines_floor():
    # 318pt 영역, 12pt 본문, 행간 1.4 → 16.8pt/줄 → 18줄
    assert max_lines(318.0, 12.0, 1.4) == 18


def test_measure_lines_single_paragraph():
    # 폭 120pt, 여유율 0.97 → 실효 116.4pt, 글자당 12pt → 9글자/줄
    assert measure_lines("가나다라마바사아자", 120.0, 12.0, FAKE, PRESET.spacing) == 1
    assert measure_lines("가나다라마바사아자차", 120.0, 12.0, FAKE, PRESET.spacing) == 2


def test_measure_bullets_heights_and_gaps():
    # 폭 120pt, 글자당 12pt, 들여쓰기 18pt → 실효 폭 102pt에 여유율 → 8글자/줄
    bullets = [Bullet(text="가나다라마바사아"), Bullet(text="하나 둘")]  # 1줄 + 1줄
    m = measure_bullets(bullets, 120.0, 12.0, FAKE, PRESET.spacing)
    assert isinstance(m, BulletsMeasure)
    assert m.lines_per_bullet == [1, 1]
    # 16.8*2 + 불릿 간격 6 = 39.6
    assert m.total_height_pt == pytest.approx(2 * 16.8 + 6.0)


def test_measure_bullets_wrapping_counts_lines():
    # 9글자 → 실효 폭 8글자 기준 2줄
    bullets = [Bullet(text="가나다라마바사아자")]
    m = measure_bullets(bullets, 120.0, 12.0, FAKE, PRESET.spacing)
    assert m.lines_per_bullet == [2]


def test_level1_bullet_gets_deeper_indent():
    # level 1은 들여쓰기 2배 → 실효 폭이 좁아져 같은 문장이 더 많은 줄을 차지한다
    text = "가나다라마바사아"
    flat = measure_bullets([Bullet(text=text, level=0)], 120.0, 12.0, FAKE, PRESET.spacing)
    deep = measure_bullets([Bullet(text=text, level=1)], 120.0, 12.0, FAKE, PRESET.spacing)
    assert deep.lines_per_bullet[0] >= flat.lines_per_bullet[0]


def test_capacity_contract_bullet_box():
    contract = capacity_contract("bullet_box", PRESET)
    # 기본 프리셋에서 불릿 영역 높이는 318pt (Task 6의 프레임 수식과 같은 값)
    assert contract["bullets_max_lines"] == 18
    assert contract["conclusion_max_lines"] == 2
    assert contract["footnote_max_lines"] == 1


def test_capacity_contract_unknown_template():
    with pytest.raises(KeyError):
        capacity_contract("fancy_chart", PRESET)
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_capacity.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`backend/slidecaptain/metrics/capacity.py`:

```python
"""용량 계약 (설계서 5.1): 프리셋이 확정한 규격에서 슬롯별 최대 분량을 역산한다.

이 한도는 AI 생성의 계약 조건으로 걸리고(단계 3), 편집 중 분량 검증에도 쓰인다.
`face` 인자는 `width_pt(text, font_pt)`를 가진 폭 데이터 한 벌이다 (FaceMetrics).
"""

import math

from pydantic import BaseModel

from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.deck import Bullet
from slidecaptain.models.preset import Preset, Spacing


def line_height_pt(font_pt: float, line_spacing: float) -> float:
    return font_pt * line_spacing


def max_lines(area_height_pt: float, font_pt: float, line_spacing: float) -> int:
    return math.floor(area_height_pt / line_height_pt(font_pt, line_spacing))


def measure_lines(text: str, area_width_pt: float, font_pt: float, face, spacing: Spacing) -> int:
    return len(break_paragraph(text, area_width_pt, font_pt, face, spacing.safety_ratio))


class BulletsMeasure(BaseModel):
    total_height_pt: float
    lines_per_bullet: list[int]


def measure_bullets(
    bullets: list[Bullet],
    area_width_pt: float,
    font_pt: float,
    face,
    spacing: Spacing,
) -> BulletsMeasure:
    lh = line_height_pt(font_pt, spacing.line_spacing)
    total = 0.0
    lines_per_bullet: list[int] = []
    for i, bullet in enumerate(bullets):
        indent = spacing.bullet_indent * (bullet.level + 1)
        lines = break_paragraph(
            bullet.text, area_width_pt - indent, font_pt, face, spacing.safety_ratio
        )
        lines_per_bullet.append(len(lines))
        total += len(lines) * lh
        if i > 0:
            # 불릿 간격은 항목 사이에만 있다
            total += spacing.bullet_gap
    return BulletsMeasure(total_height_pt=total, lines_per_bullet=lines_per_bullet)


def _content_geometry(preset: Preset) -> dict[str, float]:
    """레이아웃 엔진(Task 6)과 공유하는 파생 좌표. 수식의 진본은 여기 한 곳이다."""
    s = preset.spacing
    content_top = s.margin_top + s.title_height + s.title_gap
    footnote_top = preset.page_height_pt - s.margin_bottom - s.footnote_height
    content_bottom = footnote_top - s.footnote_gap
    content_width = preset.page_width_pt - s.margin_left - s.margin_right
    return {
        "content_top": content_top,
        "content_bottom": content_bottom,
        "content_width": content_width,
        "footnote_top": footnote_top,
    }


def capacity_contract(template: str, preset: Preset) -> dict[str, int]:
    s = preset.spacing
    r = preset.font_roles
    g = _content_geometry(preset)
    content_h = g["content_bottom"] - g["content_top"]
    box_inner_h = s.box_height - 2 * s.box_padding

    contracts: dict[str, dict[str, int]] = {
        "cover": {},
        "divider": {},
        "summary": {
            "points_max_lines": max_lines(
                content_h - s.box_height - s.summary_box_gap, r.body_pt, s.line_spacing
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, s.line_spacing),
        },
        "bullet_box": {
            "bullets_max_lines": max_lines(
                content_h - s.box_height - s.box_gap, r.body_pt, s.line_spacing
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, s.line_spacing),
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, s.line_spacing),
        },
        "table": {
            "rows_max_single_line": max_lines(
                content_h, r.table_pt, s.line_spacing
            ),  # 한 줄짜리 행 기준 상한 (머리글 포함)
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, s.line_spacing),
        },
        "compare2": {
            "card_bullets_max_lines": max_lines(
                content_h - s.box_height - s.box_gap - s.card_heading_height - s.card_heading_gap,
                r.body_pt,
                s.line_spacing,
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, s.line_spacing),
        },
    }
    return contracts[template]
```

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_capacity.py -q`
Expected: `8 passed`

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/metrics/capacity.py backend/tests/test_capacity.py
git commit -m "feat: 용량 계약 역산과 불릿 분량 실측"
```

---

### Task 6: 렌더 계획 모델 + 템플릿 프레임 수식 + 레이아웃 엔진

**Files:**
- Create: `backend/slidecaptain/models/render.py`, `backend/slidecaptain/layout/__init__.py`, `backend/slidecaptain/layout/templates.py`, `backend/slidecaptain/layout/engine.py`
- Test: `backend/tests/test_layout_engine.py`

**Interfaces:**
- Consumes: `Deck`, `Chapter`, 슬롯 모델들 (Task 2), `Preset` (Task 1), `FontMetrics` 호환 객체 (`face(bold)` 제공, Task 3), `measure_bullets`, `measure_lines`, `max_lines`, `line_height_pt`, `_content_geometry` (Task 5)
- Produces:
  - `render.py`: `Para(text, level, font_pt, bold, color, align)`, `TablePlan(col_widths_pt, header, rows, font_pt, header_fill, row_heights_pt)`, `Frame(name, x, y, w, h, fill, border, paras, table, valign="top")`, `CapacityWarning(chapter_id, slot, message, needed_pt, available_pt)`, `SlidePlan(chapter_id, template, frames, warnings)`, `RenderPlan(page_width_pt, page_height_pt, slides)`
  - `engine.py`: `build_render_plan(deck: Deck, preset: Preset, metrics) -> RenderPlan`
  - `templates.py`: `build_slide(chapter: Chapter, slots, page_no: int | None, preset: Preset, metrics) -> SlidePlan` (템플릿별 내부 함수로 위임)

프레임 좌표 수식 (기본 프리셋 값으로 계산한 기대값. 모든 수치는 프리셋에서 파생):

| 프레임 | x | y | w | h | 근거 수식 |
|---|---|---|---|---|---|
| 본문 장 제목 | 50 | 36 | 860 | 40 | margin_left, margin_top, 페이지폭-좌우여백, title_height |
| 본문 영역 시작 | 50 | 92 | 860 | - | content_top = 36+40+16 |
| 각주 | 50 | 482 | 860 | 24 | footnote_top = 540-34-24 |
| 본문 영역 끝 | - | 474 | - | - | content_bottom = 482-8 |
| 결론 박스 (bullet_box, compare2) | 50 | 418 | 860 | 56 | content_bottom - box_height |
| 불릿 영역 (bullet_box) | 50 | 92 | 860 | 318 | 474-56-8-92 |
| 결론 박스 (summary, 상단) | 50 | 92 | 860 | 56 | content_top |
| 요점 영역 (summary) | 50 | 160 | 860 | 314 | 92+56+12, 474-160 |
| 표 프레임 | 50 | 92 | 860 | 382 | content_h 전체 |
| 카드 왼쪽 (compare2) | 50 | 92 | 420 | 318 | (860-20)/2 |
| 카드 오른쪽 (compare2) | 490 | 92 | 420 | 318 | 50+420+20 |
| 쪽번호 | 850 | 512 | 60 | 16 | 960-50-60, 540-28 |
| 표지 제목 | 80 | 200 | 800 | 48 | margin_left+cover_indent |
| 간지 섹션 제목 | 80 | 246 | 800 | 44 | margin_left+cover_indent |

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_layout_engine.py`:

```python
import pytest

from slidecaptain.layout.engine import build_render_plan
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    Card,
    Chapter,
    CompareSlots,
    CoverSlots,
    Deck,
    DeckMeta,
    DividerSlots,
    Slide,
    Structure,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.preset import Preset


class FakeFace:
    def width_pt(self, text: str, font_pt: float) -> float:
        return len(text) * font_pt * 0.5


class FakeMetrics:
    """FontMetrics와 같은 모양의 가짜: 볼드 구분 없이 같은 폭을 돌려준다."""

    def face(self, bold: bool) -> FakeFace:
        return FakeFace()


PRESET = Preset()
FAKE = FakeMetrics()


def _deck(chapters_and_slots) -> Deck:
    chapters = []
    slides = []
    for i, (template, slots) in enumerate(chapters_and_slots, start=1):
        cid = f"ch{i:02d}"
        chapters.append(Chapter(id=cid, topic=f"{i}장 주제", template=template))
        slides.append(Slide(chapter_id=cid, slots=slots))
    return Deck(
        meta=DeckMeta(title="테스트 덱"),
        structure=Structure(chapters=chapters),
        slides=slides,
    )


def _bullet_box_deck() -> Deck:
    return _deck(
        [
            (
                "bullet_box",
                BulletBoxSlots(
                    bullets=[Bullet(text="첫 불릿"), Bullet(text="둘째 불릿", level=1)],
                    conclusion="결론 한 줄",
                    footnote="주: 출처는 내부 자료",
                ),
            )
        ]
    )


def _frame(plan_slide, name_suffix):
    matches = [f for f in plan_slide.frames if f.name.endswith(name_suffix)]
    assert len(matches) == 1, f"{name_suffix} 프레임이 정확히 1개 있어야 합니다"
    return matches[0]


def test_bullet_box_frame_positions():
    plan = build_render_plan(_bullet_box_deck(), PRESET, FAKE)
    slide = plan.slides[0]
    title = _frame(slide, ":title")
    assert (title.x, title.y, title.w, title.h) == (50.0, 36.0, 860.0, 40.0)
    bullets = _frame(slide, ":bullets")
    assert (bullets.x, bullets.y, bullets.w, bullets.h) == (50.0, 92.0, 860.0, 318.0)
    box = _frame(slide, ":conclusion")
    assert (box.x, box.y, box.w, box.h) == (50.0, 418.0, 860.0, 56.0)
    footnote = _frame(slide, ":footnote")
    assert (footnote.x, footnote.y, footnote.w, footnote.h) == (50.0, 482.0, 860.0, 24.0)


def test_title_comes_from_structure_topic():
    plan = build_render_plan(_bullet_box_deck(), PRESET, FAKE)
    title = _frame(plan.slides[0], ":title")
    assert title.paras[0].text == "1장 주제"


def test_frame_names_carry_role_tags():
    plan = build_render_plan(_bullet_box_deck(), PRESET, FAKE)
    names = {f.name for f in plan.slides[0].frames}
    assert names == {"ch01:title", "ch01:bullets", "ch01:conclusion", "ch01:footnote", "ch01:page_number"}


def test_same_role_same_position_across_slides():
    deck = _deck(
        [
            ("bullet_box", BulletBoxSlots(bullets=[Bullet(text="가")], conclusion="결론 A")),
            ("bullet_box", BulletBoxSlots(bullets=[Bullet(text="나")], conclusion="결론 B")),
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    f1 = _frame(plan.slides[0], ":title")
    f2 = _frame(plan.slides[1], ":title")
    assert (f1.x, f1.y, f1.w, f1.h) == (f2.x, f2.y, f2.w, f2.h)


def test_deterministic_output():
    deck = _bullet_box_deck()
    plan_a = build_render_plan(deck, PRESET, FAKE)
    plan_b = build_render_plan(deck, PRESET, FAKE)
    assert plan_a == plan_b


def test_cover_and_divider_have_no_page_number_or_title_frame():
    deck = _deck(
        [
            ("cover", CoverSlots(title="보고 제목", subtitle="부제", date="2026-08-27", audience="보고 대상")),
            ("divider", DividerSlots(section_no="1", section_title="첫 섹션")),
            ("bullet_box", BulletBoxSlots(bullets=[Bullet(text="가")], conclusion="결론")),
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    cover_names = {f.name for f in plan.slides[0].frames}
    assert not any(n.endswith(":page_number") for n in cover_names)
    divider_names = {f.name for f in plan.slides[1].frames}
    assert any(n.endswith(":section_title") for n in divider_names)
    # 본문 장에는 쪽번호가 있고, 번호는 표지 포함 실제 순번이다
    content_pn = _frame(plan.slides[2], ":page_number")
    assert content_pn.paras[0].text == "3"


def test_summary_box_on_top():
    deck = _deck([("summary", SummarySlots(conclusion="핵심 결론", points=[Bullet(text="요점")]))])
    plan = build_render_plan(deck, PRESET, FAKE)
    box = _frame(plan.slides[0], ":conclusion")
    assert (box.y, box.h) == (92.0, 56.0)
    points = _frame(plan.slides[0], ":points")
    assert (points.y, points.h) == (160.0, 314.0)


def test_compare2_cards_symmetric():
    deck = _deck(
        [
            (
                "compare2",
                CompareSlots(
                    left=Card(heading="옵션 A", bullets=[Bullet(text="장점")]),
                    right=Card(heading="옵션 B", bullets=[Bullet(text="단점")]),
                    conclusion="A를 권장",
                ),
            )
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    left = _frame(plan.slides[0], ":left_card")
    right = _frame(plan.slides[0], ":right_card")
    assert (left.x, left.y, left.w, left.h) == (50.0, 92.0, 420.0, 318.0)
    assert (right.x, right.y, right.w, right.h) == (490.0, 92.0, 420.0, 318.0)


def test_table_column_widths_sum_to_frame_width():
    deck = _deck(
        [
            (
                "table",
                TableSlots(
                    columns=["항목", "상세 내용 설명"],
                    rows=[["가", "이 칸은 내용이 훨씬 길어서 넓은 열이 필요하다"]],
                ),
            )
        ]
    )
    plan = build_render_plan(deck, PRESET, FAKE)
    table = _frame(plan.slides[0], ":table")
    assert table.table is not None
    widths = table.table.col_widths_pt
    assert sum(widths) == pytest.approx(860.0)
    assert widths[1] > widths[0]  # 내용이 긴 열이 더 넓다
    assert min(widths) >= PRESET.spacing.table_min_col_width


def test_conclusion_overflow_warns():
    # 결론 박스는 높이 고정(56pt)이라 2줄을 넘으면 경고가 남는다
    long_conclusion = "결론 문장이 지나치게 길어서 박스 용량을 넘는다 " * 20
    deck = _deck([("bullet_box", BulletBoxSlots(bullets=[Bullet(text="가")], conclusion=long_conclusion))])
    plan = build_render_plan(deck, PRESET, FAKE)
    assert any(w.slot == "conclusion" for w in plan.slides[0].warnings)


def test_overflow_produces_warning_not_resize():
    # 본문 영역을 넘치는 불릿 더미: 경고가 남고 글자 크기는 그대로다
    many = [Bullet(text=f"불릿 항목 {i}: 내용이 제법 길어서 여러 줄로 나뉘게 되는 문장이다") for i in range(30)]
    deck = _deck([("bullet_box", BulletBoxSlots(bullets=many, conclusion="결론"))])
    plan = build_render_plan(deck, PRESET, FAKE)
    slide = plan.slides[0]
    assert len(slide.warnings) >= 1
    warning = slide.warnings[0]
    assert warning.slot == "bullets"
    assert warning.needed_pt > warning.available_pt
    bullets = _frame(slide, ":bullets")
    assert all(p.font_pt == PRESET.font_roles.body_pt for p in bullets.paras)


def test_body_font_sizes_at_most_two_steps_on_content_slides():
    deck = _bullet_box_deck()
    plan = build_render_plan(deck, PRESET, FAKE)
    slide = plan.slides[0]
    body_sizes = {
        p.font_pt
        for f in slide.frames
        if not (f.name.endswith(":title") or f.name.endswith(":page_number"))
        for p in f.paras
    }
    assert len(body_sizes) <= 2
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_layout_engine.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 렌더 계획 모델 구현**

`backend/slidecaptain/models/render.py`:

```python
"""렌더 계획: 레이아웃 엔진의 출력. PPTX 라이터와 (이후 단계의) 화면 미리보기가 함께 소비한다.

여기 담긴 좌표와 글자 크기는 프리셋에서 계산된 결과이지, 조정 대상이 아니다.
"""

from typing import Literal

from pydantic import BaseModel


class Para(BaseModel):
    text: str
    level: int = 0
    font_pt: float
    bold: bool = False
    color: str = "202020"
    align: Literal["left", "center", "right"] = "left"
    bullet: bool = False  # True면 라이터가 목록 표식(•)과 내어쓰기를 적용


class TablePlan(BaseModel):
    col_widths_pt: list[float]
    header: list[str]
    rows: list[list[str]]
    font_pt: float
    header_fill: str
    row_heights_pt: list[float]  # 머리글 포함, 위에서부터


class Frame(BaseModel):
    name: str  # 역할 태깅: "장ID:슬롯" (설계서 7.1)
    x: float
    y: float
    w: float
    h: float
    fill: str | None = None
    border: str | None = None
    paras: list[Para] = []
    table: TablePlan | None = None


class CapacityWarning(BaseModel):
    chapter_id: str
    slot: str
    message: str
    needed_pt: float
    available_pt: float


class SlidePlan(BaseModel):
    chapter_id: str
    template: str
    frames: list[Frame]
    warnings: list[CapacityWarning] = []


class RenderPlan(BaseModel):
    page_width_pt: float
    page_height_pt: float
    slides: list[SlidePlan]
```

- [ ] **Step 4: 템플릿 수식 구현**

`backend/slidecaptain/layout/__init__.py` 는 빈 파일. `backend/slidecaptain/layout/templates.py`:

```python
"""템플릿 6종: 슬롯 내용 → 프레임 목록. 좌표는 전부 프리셋 수치의 수식 결과다 (설계서 5.4).

같은 역할은 모든 장에서 같은 위치: 수식에 슬롯 내용이 들어가지 않는다
(내용은 프레임 안에 담길 뿐, 프레임을 움직이지 못한다).
"""

from slidecaptain.metrics.capacity import (
    _content_geometry,
    line_height_pt,
    max_lines,
    measure_bullets,
    measure_lines,
)
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    Chapter,
    CompareSlots,
    CoverSlots,
    DividerSlots,
    SummarySlots,
    TableSlots,
)
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import CapacityWarning, Frame, Para, SlidePlan, TablePlan


def _bullet_paras(bullets: list[Bullet], preset: Preset) -> list[Para]:
    r = preset.font_roles
    c = preset.colors
    return [
        Para(text=b.text, level=b.level, font_pt=r.body_pt, color=c.text, bullet=True)
        for b in bullets
    ]


def _title_frame(chapter: Chapter, preset: Preset) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    return Frame(
        name=f"{chapter.id}:title",
        x=s.margin_left,
        y=s.margin_top,
        w=g["content_width"],
        h=s.title_height,
        paras=[Para(text=chapter.topic, font_pt=r.title_pt, bold=True, color=c.text)],
    )


def _footnote_frame(chapter: Chapter, text: str, preset: Preset) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    return Frame(
        name=f"{chapter.id}:footnote",
        x=s.margin_left,
        y=g["footnote_top"],
        w=g["content_width"],
        h=s.footnote_height,
        paras=[Para(text=text, font_pt=r.footnote_pt, color=c.text)],
    )


def _page_number_frame(chapter: Chapter, page_no: int, preset: Preset) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    return Frame(
        name=f"{chapter.id}:page_number",
        x=preset.page_width_pt - s.margin_right - s.page_number_width,
        y=preset.page_height_pt - s.page_number_bottom,
        w=s.page_number_width,
        h=s.page_number_height,
        paras=[Para(text=str(page_no), font_pt=r.page_number_pt, color=c.text, align="right")],
    )


def _conclusion_box_frame(chapter: Chapter, text: str, y: float, preset: Preset) -> Frame:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    return Frame(
        name=f"{chapter.id}:conclusion",
        x=s.margin_left,
        y=y,
        w=g["content_width"],
        h=s.box_height,
        fill=c.box_fill,
        border=c.border,
        paras=[Para(text=text, font_pt=r.box_pt, bold=True, color=c.accent)],
    )


def _measure_warning(
    chapter: Chapter, slot: str, needed: float, available: float
) -> CapacityWarning:
    return CapacityWarning(
        chapter_id=chapter.id,
        slot=slot,
        message=f"{slot} 분량이 영역을 {needed - available:.0f}pt 넘습니다. 내용을 줄이거나 장을 나누세요",
        needed_pt=needed,
        available_pt=available,
    )


def _conclusion_warning(chapter: Chapter, text: str, preset: Preset, metrics) -> CapacityWarning | None:
    """결론 박스는 높이가 고정이므로, 굵은 글꼴 폭으로 실측해 초과를 잡는다."""
    s, r = preset.spacing, preset.font_roles
    g = _content_geometry(preset)
    inner_w = g["content_width"] - 2 * s.box_padding
    inner_h = s.box_height - 2 * s.box_padding
    capacity = max_lines(inner_h, r.box_pt, s.line_spacing)
    lines = measure_lines(text, inner_w, r.box_pt, metrics.face(True), s)
    if lines <= capacity:
        return None
    lh = line_height_pt(r.box_pt, s.line_spacing)
    return _measure_warning(chapter, "conclusion", lines * lh, inner_h)


def _build_cover(chapter: Chapter, slots: CoverSlots, preset: Preset) -> SlidePlan:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    x = s.margin_left + s.cover_indent
    w = preset.page_width_pt - 2 * (s.margin_left + s.cover_indent)
    frames = [
        Frame(
            name=f"{chapter.id}:cover_title", x=x, y=200.0, w=w, h=48.0,
            paras=[Para(text=slots.title, font_pt=r.cover_title_pt, bold=True, color=c.text)],
        ),
        Frame(
            name=f"{chapter.id}:subtitle", x=x, y=260.0, w=w, h=24.0,
            paras=[Para(text=slots.subtitle, font_pt=r.subtitle_pt, color=c.accent)],
        ),
        Frame(
            name=f"{chapter.id}:date", x=x, y=430.0, w=w / 2, h=18.0,
            paras=[Para(text=slots.date, font_pt=r.body_pt, color=c.text)],
        ),
        Frame(
            name=f"{chapter.id}:audience", x=x, y=452.0, w=w / 2, h=18.0,
            paras=[Para(text=slots.audience, font_pt=r.body_pt, color=c.text)],
        ),
    ]
    return SlidePlan(chapter_id=chapter.id, template="cover", frames=frames)


def _build_divider(chapter: Chapter, slots: DividerSlots, page_no: int, preset: Preset) -> SlidePlan:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    x = s.margin_left + s.cover_indent
    w = preset.page_width_pt - 2 * (s.margin_left + s.cover_indent)
    frames = [
        Frame(
            name=f"{chapter.id}:section_no", x=x, y=218.0, w=w, h=20.0,
            paras=[Para(text=slots.section_no, font_pt=r.subtitle_pt, color=c.accent)],
        ),
        Frame(
            name=f"{chapter.id}:section_title", x=x, y=246.0, w=w, h=44.0,
            paras=[Para(text=slots.section_title, font_pt=r.section_title_pt, bold=True, color=c.text)],
        ),
    ]
    return SlidePlan(chapter_id=chapter.id, template="divider", frames=frames)


def _build_bullet_box(
    chapter: Chapter, slots: BulletBoxSlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    s = preset.spacing
    g = _content_geometry(preset)
    bullets_h = g["content_bottom"] - g["content_top"] - s.box_height - s.box_gap
    warnings = []
    measure = measure_bullets(
        slots.bullets, g["content_width"], preset.font_roles.body_pt, metrics.face(False), s
    )
    if measure.total_height_pt > bullets_h:
        warnings.append(_measure_warning(chapter, "bullets", measure.total_height_pt, bullets_h))
    if (cw := _conclusion_warning(chapter, slots.conclusion, preset, metrics)) is not None:
        warnings.append(cw)
    frames = [
        _title_frame(chapter, preset),
        Frame(
            name=f"{chapter.id}:bullets",
            x=s.margin_left, y=g["content_top"], w=g["content_width"], h=bullets_h,
            paras=_bullet_paras(slots.bullets, preset),
        ),
        _conclusion_box_frame(chapter, slots.conclusion, g["content_bottom"] - s.box_height, preset),
        _page_number_frame(chapter, page_no, preset),
    ]
    if slots.footnote:
        frames.insert(3, _footnote_frame(chapter, slots.footnote, preset))
    return SlidePlan(chapter_id=chapter.id, template="bullet_box", frames=frames, warnings=warnings)


def _build_summary(
    chapter: Chapter, slots: SummarySlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    s = preset.spacing
    g = _content_geometry(preset)
    points_top = g["content_top"] + s.box_height + s.summary_box_gap
    points_h = g["content_bottom"] - points_top
    warnings = []
    measure = measure_bullets(
        slots.points, g["content_width"], preset.font_roles.body_pt, metrics.face(False), s
    )
    if measure.total_height_pt > points_h:
        warnings.append(_measure_warning(chapter, "points", measure.total_height_pt, points_h))
    if (cw := _conclusion_warning(chapter, slots.conclusion, preset, metrics)) is not None:
        warnings.append(cw)
    frames = [
        _title_frame(chapter, preset),
        _conclusion_box_frame(chapter, slots.conclusion, g["content_top"], preset),
        Frame(
            name=f"{chapter.id}:points",
            x=s.margin_left, y=points_top, w=g["content_width"], h=points_h,
            paras=_bullet_paras(slots.points, preset),
        ),
        _page_number_frame(chapter, page_no, preset),
    ]
    return SlidePlan(chapter_id=chapter.id, template="summary", frames=frames, warnings=warnings)


def _table_col_widths(slots: TableSlots, frame_w: float, preset: Preset, metrics) -> list[float]:
    """열 폭은 열 내용의 최대 실측 폭에 비례 배분하되, 최소 폭을 보장하고 합을 프레임 폭에 맞춘다."""
    s, r = preset.spacing, preset.font_roles
    raw: list[float] = []
    for col_idx, col_name in enumerate(slots.columns):
        header_w = metrics.face(True).width_pt(col_name, r.table_pt)  # 머리글은 굵은 글꼴
        cell_w = max(
            (metrics.face(False).width_pt(row[col_idx], r.table_pt) for row in slots.rows),
            default=0.0,
        )
        raw.append(max(header_w, cell_w) + 2 * s.table_cell_pad_x)
    scale = frame_w / sum(raw)
    widths = [max(w * scale, s.table_min_col_width) for w in raw]
    # 최소 폭 보정으로 합이 넘치면 넘친 만큼 가장 넓은 열에서 회수한다
    excess = sum(widths) - frame_w
    if excess > 0:
        widest_idx = widths.index(max(widths))
        widths[widest_idx] -= excess
    return widths


def _build_table(
    chapter: Chapter, slots: TableSlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    from slidecaptain.metrics.line_breaker import break_paragraph

    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    table_h = g["content_bottom"] - g["content_top"]
    col_widths = _table_col_widths(slots, g["content_width"], preset, metrics)
    lh = line_height_pt(r.table_pt, s.line_spacing)

    def row_height(cells: list[str], bold: bool) -> float:
        face = metrics.face(bold)
        lines = max(
            len(break_paragraph(cell, col_widths[i] - 2 * s.table_cell_pad_x, r.table_pt, face, s.safety_ratio))
            for i, cell in enumerate(cells)
        )
        return lines * lh + 2 * s.table_cell_pad_y

    row_heights = [row_height(slots.columns, True)] + [row_height(row, False) for row in slots.rows]
    warnings = []
    total_h = sum(row_heights)
    if total_h > table_h:
        warnings.append(_measure_warning(chapter, "table", total_h, table_h))
    frames = [
        _title_frame(chapter, preset),
        Frame(
            name=f"{chapter.id}:table",
            x=s.margin_left, y=g["content_top"], w=g["content_width"], h=table_h,
            table=TablePlan(
                col_widths_pt=col_widths,
                header=slots.columns,
                rows=slots.rows,
                font_pt=r.table_pt,
                header_fill=c.table_header_fill,
                row_heights_pt=row_heights,
            ),
        ),
        _page_number_frame(chapter, page_no, preset),
    ]
    if slots.footnote:
        frames.insert(2, _footnote_frame(chapter, slots.footnote, preset))
    return SlidePlan(chapter_id=chapter.id, template="table", frames=frames, warnings=warnings)


def _build_compare2(
    chapter: Chapter, slots: CompareSlots, page_no: int, preset: Preset, metrics
) -> SlidePlan:
    s, r, c = preset.spacing, preset.font_roles, preset.colors
    g = _content_geometry(preset)
    card_h = g["content_bottom"] - g["content_top"] - s.box_height - s.box_gap
    card_w = (g["content_width"] - s.card_gap) / 2
    warnings = []
    if (cw := _conclusion_warning(chapter, slots.conclusion, preset, metrics)) is not None:
        warnings.append(cw)

    def card_frame(name: str, card, x: float) -> Frame:
        paras = [Para(text=card.heading, font_pt=r.body_pt, bold=True, color=c.accent)]
        paras += _bullet_paras(card.bullets, preset)
        bullets_h_available = card_h - s.card_heading_height - s.card_heading_gap
        measure = measure_bullets(card.bullets, card_w, r.body_pt, metrics.face(False), s)
        if measure.total_height_pt > bullets_h_available:
            warnings.append(_measure_warning(chapter, name, measure.total_height_pt, bullets_h_available))
        return Frame(
            name=f"{chapter.id}:{name}",
            x=x, y=g["content_top"], w=card_w, h=card_h,
            border=c.border,
            paras=paras,
        )

    frames = [
        _title_frame(chapter, preset),
        card_frame("left_card", slots.left, s.margin_left),
        card_frame("right_card", slots.right, s.margin_left + card_w + s.card_gap),
        _conclusion_box_frame(chapter, slots.conclusion, g["content_bottom"] - s.box_height, preset),
        _page_number_frame(chapter, page_no, preset),
    ]
    return SlidePlan(chapter_id=chapter.id, template="compare2", frames=frames, warnings=warnings)


def build_slide(chapter: Chapter, slots, page_no: int, preset: Preset, metrics) -> SlidePlan:
    if isinstance(slots, CoverSlots):
        return _build_cover(chapter, slots, preset)
    if isinstance(slots, DividerSlots):
        return _build_divider(chapter, slots, page_no, preset)
    if isinstance(slots, SummarySlots):
        return _build_summary(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, BulletBoxSlots):
        return _build_bullet_box(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, TableSlots):
        return _build_table(chapter, slots, page_no, preset, metrics)
    if isinstance(slots, CompareSlots):
        return _build_compare2(chapter, slots, page_no, preset, metrics)
    raise ValueError(f"알 수 없는 슬롯 유형: {type(slots).__name__}")
```

- [ ] **Step 5: 엔진 구현**

`backend/slidecaptain/layout/engine.py`:

```python
"""덱 + 프리셋 + 폰트 실측 → 렌더 계획. 같은 입력은 항상 같은 출력을 낸다."""

from slidecaptain.layout.templates import build_slide
from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import RenderPlan


def build_render_plan(deck: Deck, preset: Preset, metrics) -> RenderPlan:
    chapters = {ch.id: ch for ch in deck.structure.chapters}
    slides = []
    for page_no, slide in enumerate(deck.slides, start=1):
        chapter = chapters.get(slide.chapter_id)
        if chapter is None:
            raise ValueError(f"구조안에 없는 장을 그릴 수 없습니다: {slide.chapter_id}")
        slides.append(build_slide(chapter, slide.slots, page_no, preset, metrics))
    return RenderPlan(
        page_width_pt=preset.page_width_pt,
        page_height_pt=preset.page_height_pt,
        slides=slides,
    )
```

- [ ] **Step 6: 통과 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_layout_engine.py -q`
Expected: `12 passed`

주의: `_build_cover`의 y 좌표(200, 260, 430, 452)와 `_build_divider`의 y 좌표(218, 246)는 v0.1에서 고정 수치로 둔다 (표지와 간지는 페이지당 1회만 나오는 특수 장이라 프리셋 파생 수식의 이득이 작다). 프리셋으로 옮기는 것은 환류 기능(단계 5)에서 필요해질 때 한다.

- [ ] **Step 7: 커밋**

```bash
git add backend/slidecaptain/models/render.py backend/slidecaptain/layout backend/tests/test_layout_engine.py
git commit -m "feat: 템플릿 6종 프레임 수식과 레이아웃 엔진 (렌더 계획, 용량 경고)"
```

---

### Task 7: PPTX 라이터 (텍스트 프레임)

**Files:**
- Create: `backend/slidecaptain/export/__init__.py`, `backend/slidecaptain/export/pptx_writer.py`
- Test: `backend/tests/test_pptx_writer.py`

**Interfaces:**
- Consumes: `RenderPlan`, `Frame`, `Para` (Task 6)
- Produces: `write_pptx(plan: RenderPlan, out_path: str | Path, preset: Preset) -> None`

핵심 기법 (방법론 히스토리 C절):
- 모든 run에 `lang="ko-KR"` + 한글 폰트(`a:ea`)와 영문 폰트(`a:latin`)를 함께 지정
- `MSO_AUTO_SIZE.NONE`으로 자동 맞춤 차단 (글자 크기 축소 금지의 기계적 보장)
- 도형 이름 = 프레임 이름 (역할 태깅)
- 도형 기본 그림자 제거 (장식 최소)
- 행간은 배수가 아니라 고정 pt(글자 크기 x 프리셋 행간 계수)로 기록한다. PowerPoint의 배수 행간은
  폰트 고유의 세로 규격(1em보다 큼)에 곱해져 용량 계산과 어긋나므로, 고정 pt로 기록해야
  실측 줄수 계산(16.8pt/줄)과 실제 렌더가 일치한다

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_pptx_writer.py`:

```python
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu

from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import Frame, Para, RenderPlan, SlidePlan

OUT_DIR = Path("backend/tests/_out")
PRESET = Preset()


def _simple_plan() -> RenderPlan:
    return RenderPlan(
        page_width_pt=960.0,
        page_height_pt=540.0,
        slides=[
            SlidePlan(
                chapter_id="ch01",
                template="bullet_box",
                frames=[
                    Frame(
                        name="ch01:title", x=50.0, y=36.0, w=860.0, h=40.0,
                        paras=[Para(text="장 제목", font_pt=20.0, bold=True)],
                    ),
                    Frame(
                        name="ch01:bullets", x=50.0, y=92.0, w=860.0, h=318.0,
                        paras=[
                            Para(text="첫 불릿", font_pt=12.0, bullet=True),
                            Para(text="하위 불릿", font_pt=12.0, level=1, bullet=True),
                        ],
                    ),
                    Frame(
                        name="ch01:conclusion", x=50.0, y=418.0, w=860.0, h=56.0,
                        fill="EEF3F9", border="D0D7E2",
                        paras=[Para(text="결론 문장", font_pt=12.0, bold=True, color="1F4E79")],
                    ),
                ],
            )
        ],
    )


@pytest.fixture()
def saved(tmp_path) -> Presentation:
    out = tmp_path / "out.pptx"
    write_pptx(_simple_plan(), out, PRESET)
    return Presentation(str(out))


def test_page_size_16_9(saved):
    assert saved.slide_width == Emu(12192000)
    assert saved.slide_height == Emu(6858000)


def test_shape_names_and_positions(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    assert set(shapes) == {"ch01:title", "ch01:bullets", "ch01:conclusion"}
    title = shapes["ch01:title"]
    # 1pt = 12700 EMU
    assert title.left == Emu(round(50.0 * 12700))
    assert title.top == Emu(round(36.0 * 12700))
    assert title.width == Emu(round(860.0 * 12700))
    assert title.height == Emu(round(40.0 * 12700))


def test_every_run_has_korean_lang_and_fonts(saved):
    for shape in saved.slides[0].shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                rPr = run._r.find(qn("a:rPr"))
                assert rPr is not None
                assert rPr.get("lang") == "ko-KR"
                latin = rPr.find(qn("a:latin"))
                ea = rPr.find(qn("a:ea"))
                assert latin is not None and latin.get("typeface") == "맑은 고딕"
                assert ea is not None and ea.get("typeface") == "맑은 고딕"


def test_autofit_disabled_everywhere(saved):
    from pptx.enum.text import MSO_AUTO_SIZE

    for shape in saved.slides[0].shapes:
        if shape.has_text_frame:
            assert shape.text_frame.auto_size == MSO_AUTO_SIZE.NONE
            assert shape.text_frame.word_wrap is True


def test_font_sizes_written_exactly(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    title_run = shapes["ch01:title"].text_frame.paragraphs[0].runs[0]
    assert title_run.font.size.pt == 20.0
    assert title_run.font.bold is True
    bullet_run = shapes["ch01:bullets"].text_frame.paragraphs[0].runs[0]
    assert bullet_run.font.size.pt == 12.0


def test_bullet_paragraphs_have_marker_and_level(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    paras = shapes["ch01:bullets"].text_frame.paragraphs
    p0 = paras[0]._p.find(qn("a:pPr"))
    assert p0 is not None
    assert p0.find(qn("a:buChar")) is not None
    assert paras[1].level == 1


def test_box_fill_and_border(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    box = shapes["ch01:conclusion"]
    assert box.fill.fore_color.rgb == 0xEEF3F9 or str(box.fill.fore_color.rgb) == "EEF3F9"
    assert str(box.line.color.rgb) == "D0D7E2"
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_pptx_writer.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`backend/slidecaptain/export/__init__.py` 는 빈 파일. `backend/slidecaptain/export/pptx_writer.py`:

```python
"""렌더 계획 → PPTX. 축적된 기법을 내장한다 (설계서 7.1, 방법론 히스토리 C절).

- 모든 run에 ko-KR 언어 속성 (어절 단위 줄바꿈)
- a:latin과 a:ea 폰트를 함께 지정 (한글 폰트 확실 적용)
- MSO_AUTO_SIZE.NONE (자동 맞춤이 글자를 줄이는 일을 기계적으로 차단)
- 도형 이름 = 역할 태그 (향후 양방향 재수입의 열쇠)
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.lang import MSO_LANGUAGE_ID
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from slidecaptain.models.preset import Preset
from slidecaptain.models.render import Frame, Para, RenderPlan, TablePlan

EMU_PER_PT = 12700

_ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}


def _emu(pt: float) -> Emu:
    return Emu(round(pt * EMU_PER_PT))


def _style_run(run, para: Para, preset: Preset) -> None:
    run.font.size = Pt(para.font_pt)
    run.font.bold = para.bold
    run.font.color.rgb = RGBColor.from_string(para.color)
    run.font.name = preset.fonts.latin  # a:latin만 기록된다 (실측 검증 2026-08-27)
    # 공식 API가 a:rPr에 lang="ko-KR"을 기록한다 (v0.1은 한국어 고정)
    run.font.language_id = MSO_LANGUAGE_ID.KOREAN
    # 한글 폰트는 a:ea 요소로 지정해야 실제 렌더에 적용된다. 스키마 순서상 a:latin 바로 뒤에 넣는다
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        latin = rPr.find(qn("a:latin"))
        if latin is not None:
            latin.addnext(ea)
        else:
            rPr.append(ea)
    ea.set("typeface", preset.fonts.korean)


def _apply_bullet(paragraph, para: Para, preset: Preset) -> None:
    indent_emu = round(preset.spacing.bullet_indent * EMU_PER_PT)
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("marL", str(indent_emu * (para.level + 1)))
    pPr.set("indent", str(-indent_emu))
    bu_font = pPr.makeelement(qn("a:buFont"), {"typeface": "Arial"})
    bu_char = pPr.makeelement(qn("a:buChar"), {"char": "\u2022"})
    pPr.append(bu_font)
    pPr.append(bu_char)


def _fill_text_frame(tf, frame: Frame, preset: Preset) -> None:
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    pad = _emu(preset.spacing.box_padding) if frame.fill else 0
    tf.margin_left = pad
    tf.margin_right = pad
    tf.margin_top = pad
    tf.margin_bottom = pad
    for i, para in enumerate(frame.paras):
        paragraph = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        paragraph.alignment = _ALIGN[para.align]
        # 고정 pt 행간: 용량 계산(line_height_pt)과 렌더를 일치시킨다
        paragraph.line_spacing = Pt(para.font_pt * preset.spacing.line_spacing)
        paragraph.level = para.level
        if para.bullet:
            _apply_bullet(paragraph, para, preset)
        if i > 0 and para.bullet:
            paragraph.space_before = Pt(preset.spacing.bullet_gap)
        run = paragraph.add_run()
        run.text = para.text
        _style_run(run, para, preset)


def _add_text_shape(slide, frame: Frame, preset: Preset) -> None:
    if frame.fill or frame.border:
        shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, _emu(frame.x), _emu(frame.y), _emu(frame.w), _emu(frame.h)
        )
        shape.shadow.inherit = False
        if frame.fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string(frame.fill)
        else:
            shape.fill.background()
        if frame.border:
            shape.line.color.rgb = RGBColor.from_string(frame.border)
            shape.line.width = Pt(0.75)
        else:
            shape.line.fill.background()
    else:
        shape = slide.shapes.add_textbox(_emu(frame.x), _emu(frame.y), _emu(frame.w), _emu(frame.h))
    shape.name = frame.name
    _fill_text_frame(shape.text_frame, frame, preset)


def _add_table_shape(slide, frame: Frame, preset: Preset) -> None:
    plan: TablePlan = frame.table
    n_rows = len(plan.rows) + 1
    n_cols = len(plan.header)
    graphic_frame = slide.shapes.add_table(
        n_rows, n_cols, _emu(frame.x), _emu(frame.y), _emu(frame.w), _emu(frame.h)
    )
    graphic_frame.name = frame.name
    table = graphic_frame.table
    table.first_row = False  # 내장 스타일 밴딩을 쓰지 않고 직접 칠한다 (균일성)
    table.horz_banding = False
    for i, width in enumerate(plan.col_widths_pt):
        table.columns[i].width = _emu(width)
    for i, height in enumerate(plan.row_heights_pt):
        table.rows[i].height = _emu(height)
    all_rows = [plan.header] + plan.rows
    for r_idx, row in enumerate(all_rows):
        for c_idx, text in enumerate(row):
            cell = table.cell(r_idx, c_idx)
            cell.margin_left = _emu(preset.spacing.table_cell_pad_x)
            cell.margin_right = _emu(preset.spacing.table_cell_pad_x)
            cell.margin_top = _emu(preset.spacing.table_cell_pad_y)
            cell.margin_bottom = _emu(preset.spacing.table_cell_pad_y)
            if r_idx == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(plan.header_fill)
            tf = cell.text_frame
            tf.word_wrap = True
            paragraph = tf.paragraphs[0]
            paragraph.line_spacing = Pt(plan.font_pt * preset.spacing.line_spacing)
            run = paragraph.add_run()
            run.text = text
            _style_run(
                run,
                Para(text=text, font_pt=plan.font_pt, bold=(r_idx == 0), color=preset.colors.text),
                preset,
            )


def write_pptx(plan: RenderPlan, out_path: str | Path, preset: Preset) -> None:
    prs = Presentation()
    prs.slide_width = _emu(plan.page_width_pt)
    prs.slide_height = _emu(plan.page_height_pt)
    blank_layout = prs.slide_layouts[6]
    for slide_plan in plan.slides:
        slide = prs.slides.add_slide(blank_layout)
        for frame in slide_plan.frames:
            if frame.table is not None:
                _add_table_shape(slide, frame, preset)
            else:
                _add_text_shape(slide, frame, preset)
    prs.save(str(out_path))
```

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_pptx_writer.py -q`
Expected: `7 passed`

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/export backend/tests/test_pptx_writer.py
git commit -m "feat: PPTX 라이터 (ko-KR run 속성, 역할 태깅, autofit 차단)"
```

---

### Task 8: 표 렌더링 골든 테스트

**Files:**
- Test: `backend/tests/test_table_render.py`

**Interfaces:**
- Consumes: `write_pptx` (Task 7), `build_render_plan` (Task 6), `FontMetrics` (Task 3)

표는 라이터에서 이미 구현했으므로(Task 7), 이 태스크는 실제 폰트 실측과 결합한 관통 골든 테스트로 표 경로를 고정한다.

- [ ] **Step 1: 실패하는 테스트 작성** (표 경로에 결함이 있으면 여기서 드러난다)

`backend/tests/test_table_render.py`:

```python
import pytest
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu

from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Chapter, Deck, DeckMeta, Slide, Structure, TableSlots
from slidecaptain.models.preset import Preset

PRESET = Preset()


def _table_deck() -> Deck:
    return Deck(
        meta=DeckMeta(title="표 테스트"),
        structure=Structure(
            chapters=[Chapter(id="ch01", topic="비교 결과", template="table")]
        ),
        slides=[
            Slide(
                chapter_id="ch01",
                slots=TableSlots(
                    columns=["항목", "옵션 A", "옵션 B"],
                    rows=[
                        ["도입 비용", "1,200만 원", "800만 원"],
                        ["운영 부담", "낮음", "중간"],
                    ],
                    footnote="주: 2026년 상반기 견적 기준",
                ),
            )
        ],
    )


@pytest.fixture()
def saved(tmp_path):
    metrics = FontMetrics.from_bundled()
    plan = build_render_plan(_table_deck(), PRESET, metrics)
    out = tmp_path / "table.pptx"
    write_pptx(plan, out, PRESET)
    return Presentation(str(out))


def test_table_shape_exists_with_role_name(saved):
    shapes = {s.name: s for s in saved.slides[0].shapes}
    assert "ch01:table" in shapes
    assert shapes["ch01:table"].has_table


def test_table_dimensions(saved):
    table = next(s for s in saved.slides[0].shapes if s.name == "ch01:table").table
    assert len(table.rows) == 3  # 머리글 + 데이터 2행
    assert len(table.columns) == 3
    total_w = sum(col.width for col in table.columns)
    assert total_w == pytest.approx(Emu(round(860.0 * 12700)), rel=0.01)


def test_table_cells_have_korean_lang(saved):
    table = next(s for s in saved.slides[0].shapes if s.name == "ch01:table").table
    for row in table.rows:
        for cell in row.cells:
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    assert run._r.find(qn("a:rPr")).get("lang") == "ko-KR"


def test_table_font_at_body_size(saved):
    table = next(s for s in saved.slides[0].shapes if s.name == "ch01:table").table
    run = table.cell(1, 0).text_frame.paragraphs[0].runs[0]
    assert run.font.size.pt == PRESET.font_roles.table_pt


def test_header_bold_and_filled(saved):
    table = next(s for s in saved.slides[0].shapes if s.name == "ch01:table").table
    header_run = table.cell(0, 0).text_frame.paragraphs[0].runs[0]
    assert header_run.font.bold is True
```

- [ ] **Step 2: 실행해 통과 또는 결함 수정**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_table_render.py -q`
Expected: `5 passed` (실패하면 Task 7의 `_add_table_shape`를 수정해 통과시킨다. `graphic_frame.name` 설정이 동작하지 않으면 `graphic_frame._element.nvGraphicFramePr.cNvPr.set("name", frame.name)` 저수준 경로로 바꾼다)

- [ ] **Step 3: 커밋**

```bash
git add backend/tests/test_table_render.py
git commit -m "test: 표 렌더링 골든 테스트 (역할 태깅, ko-KR, 본문 크기)"
```

---

### Task 9: 내보내기 오케스트레이터 + CLI

**Files:**
- Create: `backend/slidecaptain/export/exporter.py`, `backend/slidecaptain/__main__.py`
- Test: `backend/tests/test_exporter.py`

**Interfaces:**
- Consumes: `Deck` (Task 2), `Preset`, `apply_overrides` (Task 1), `FontMetrics.load_default` (Task 3), `build_render_plan` (Task 6), `write_pptx` (Task 7)
- Produces: `export_deck(deck_path: str | Path, out_dir: str | Path, global_preset: Preset | None = None) -> Path` (내보낸 파일 경로 반환), CLI `python -m slidecaptain export <deck.json> [--out <dir>]`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_exporter.py`:

```python
import json
from pathlib import Path

from pptx import Presentation

from slidecaptain.export.exporter import export_deck
from slidecaptain.models.deck import (
    Bullet,
    BulletBoxSlots,
    Chapter,
    Deck,
    DeckMeta,
    Slide,
    Structure,
)


def _write_deck(path: Path, title: str = "내보내기 테스트") -> Deck:
    deck = Deck(
        meta=DeckMeta(title=title),
        structure=Structure(chapters=[Chapter(id="ch01", topic="개요", template="bullet_box")]),
        slides=[
            Slide(chapter_id="ch01", slots=BulletBoxSlots(bullets=[Bullet(text="항목")], conclusion="결론"))
        ],
    )
    path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    return deck


def test_export_creates_versioned_file(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path)
    out_dir = tmp_path / "exports"
    first = export_deck(deck_path, out_dir)
    second = export_deck(deck_path, out_dir)
    assert first.name == "내보내기 테스트_v001.pptx"
    assert second.name == "내보내기 테스트_v002.pptx"
    assert first.exists() and second.exists()  # 기존 파일을 덮어쓰지 않는다


def test_export_leaves_deck_json_untouched(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path)
    before = deck_path.read_bytes()
    export_deck(deck_path, tmp_path / "exports")
    assert deck_path.read_bytes() == before


def test_exported_file_opens_and_has_slides(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path)
    out = export_deck(deck_path, tmp_path / "exports")
    prs = Presentation(str(out))
    assert len(prs.slides) == 1


def test_title_with_invalid_filename_chars_sanitized(tmp_path):
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path, title="검토: 결과/요약")
    out = export_deck(deck_path, tmp_path / "exports")
    assert out.exists()
    assert ":" not in out.name


def test_bracket_title_versions_increment(tmp_path):
    # 대괄호 제목: glob 문자 클래스 해석으로 버전 스캔이 깨지던 회귀 사례 (2026-08-27 리뷰 실측)
    deck_path = tmp_path / "deck.json"
    _write_deck(deck_path, title="[대외비] 검토 보고")
    out_dir = tmp_path / "exports"
    first = export_deck(deck_path, out_dir)
    second = export_deck(deck_path, out_dir)
    assert first.name.endswith("_v001.pptx")
    assert second.name.endswith("_v002.pptx")
    assert first.exists() and second.exists()


def test_export_works_from_non_ascii_paths(tmp_path):
    korean_dir = tmp_path / "한글 폴더"
    korean_dir.mkdir()
    deck_path = korean_dir / "deck.json"
    _write_deck(deck_path, title="한글 경로 덱")
    out = export_deck(deck_path, korean_dir / "내보내기")
    assert out.exists()
    assert Presentation(str(out))


def test_preset_overrides_from_meta_applied(tmp_path):
    deck_path = tmp_path / "deck.json"
    deck = _write_deck(deck_path)
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    data["meta"]["preset_overrides"] = {"font_roles": {"title_pt": 22.0}}
    deck_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = export_deck(deck_path, tmp_path / "exports")
    prs = Presentation(str(out))
    title_shape = next(s for s in prs.slides[0].shapes if s.name == "ch01:title")
    assert title_shape.text_frame.paragraphs[0].runs[0].font.size.pt == 22.0
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_exporter.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

`backend/slidecaptain/export/exporter.py`:

```python
"""내보내기 파일 처리 (설계서 7.1).

- 저장은 ASCII 임시 경로에서 수행한 뒤 최종 위치로 이동한다 (한글 경로 안전)
- 기존 파일을 덮어쓰지 않고 v001, v002 새 버전으로 저장한다
  (사용자가 PowerPoint에서 직접 고친 수정분의 소실 방지)
- deck.json은 읽기만 하고 절대 고치지 않는다
"""

import re
import shutil
import tempfile
from pathlib import Path

from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck
from slidecaptain.models.preset import Preset, apply_overrides

_VERSION_RE = re.compile(r"_v(\d{3,})\.pptx$")
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_title(title: str) -> str:
    """Windows에서 쓸 수 없는 파일명 문자를 밑줄로 바꾼다 (덱 제목에 콜론이 흔하다)."""
    return _INVALID_FILENAME_CHARS.sub("_", title).strip() or "deck"


def _next_version_path(out_dir: Path, title: str) -> Path:
    # glob을 쓰지 않는다: 제목의 대괄호가 문자 클래스로 해석되어 스캔이 깨진다 (2026-08-27 리뷰 실측)
    prefix = f"{title}_v"
    existing = [
        int(m.group(1))
        for p in out_dir.iterdir()
        if p.name.startswith(prefix) and (m := _VERSION_RE.search(p.name))
    ]
    next_no = max(existing, default=0) + 1
    path = out_dir / f"{title}_v{next_no:03d}.pptx"
    # 백스톱: 어떤 사유로든 스캔이 놓친 파일이 있으면 절대 그 경로를 돌려주지 않는다
    while path.exists():
        next_no += 1
        path = out_dir / f"{title}_v{next_no:03d}.pptx"
    return path


def export_deck(
    deck_path: str | Path,
    out_dir: str | Path,
    global_preset: Preset | None = None,
) -> Path:
    deck_path = Path(deck_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    deck = Deck.model_validate_json(deck_path.read_text(encoding="utf-8"))
    preset = apply_overrides(global_preset or Preset(), deck.meta.preset_overrides)
    metrics = FontMetrics.load_default()
    plan = build_render_plan(deck, preset, metrics)

    final_path = _next_version_path(out_dir, _safe_title(deck.meta.title))
    # tempfile 표준 임시 폴더는 ASCII 경로다. 임시로 저장한 뒤 최종 경로로 이동한다
    with tempfile.TemporaryDirectory(prefix="slidecaptain_") as tmp:
        tmp_file = Path(tmp) / "deck.pptx"
        write_pptx(plan, tmp_file, preset)
        shutil.move(str(tmp_file), str(final_path))
    return final_path
```

`backend/slidecaptain/__main__.py`:

```python
"""CLI: python -m slidecaptain export <deck.json> [--out <dir>]"""

import argparse
import sys
from pathlib import Path

from slidecaptain.export.exporter import export_deck


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slidecaptain")
    sub = parser.add_subparsers(dest="command", required=True)
    p_export = sub.add_parser("export", help="deck.json을 PPTX로 내보낸다")
    p_export.add_argument("deck", type=Path)
    p_export.add_argument("--out", type=Path, default=None, help="내보내기 폴더 (기본: 덱 옆 exports/)")
    args = parser.parse_args(argv)

    out_dir = args.out if args.out is not None else args.deck.parent / "exports"
    result = export_deck(args.deck, out_dir)
    print(f"내보내기 완료: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_exporter.py -q`
Expected: `7 passed`

- [ ] **Step 5: 커밋**

```bash
git add backend/slidecaptain/export/exporter.py backend/slidecaptain/__main__.py backend/tests/test_exporter.py
git commit -m "feat: 내보내기 오케스트레이터와 CLI (ASCII 임시 경로, 버전 파일명, 덱 불변)"
```

---

### Task 10: 견본 덱 + 회귀 테스트 묶음

**Files:**
- Create: `backend/samples/sample_deck.json`
- Test: `backend/tests/test_regression.py`

**Interfaces:**
- Consumes: 전체 파이프라인 (Task 1~9)

방법론 히스토리의 실패 목록(E절 2)을 회귀 테스트로 고정한다. 이 테스트 묶음이 이후 모든 단계의 안전망이다.

- [ ] **Step 1: 견본 덱 작성**

`backend/samples/sample_deck.json` (템플릿 6종 전부 사용):

```json
{
  "schema_version": 1,
  "meta": {
    "title": "시장 진입 검토 견본",
    "report_type": "research",
    "audience": "경영진",
    "preset_overrides": {}
  },
  "structure": {
    "chapters": [
      {"id": "ch01", "topic": "표지", "conclusion": "", "template": "cover", "source_refs": []},
      {"id": "ch02", "topic": "핵심 요약", "conclusion": "3개 시장 중 1곳이 진입 요건을 충족", "template": "summary", "source_refs": []},
      {"id": "ch03", "topic": "1부: 시장 현황", "conclusion": "", "template": "divider", "source_refs": []},
      {"id": "ch04", "topic": "시장 규모와 성장률", "conclusion": "성장률 기준으로는 B 시장이 우위", "template": "bullet_box", "source_refs": []},
      {"id": "ch05", "topic": "시장별 지표 비교", "conclusion": "", "template": "table", "source_refs": []},
      {"id": "ch06", "topic": "진입 방식 비교", "conclusion": "직접 진출보다 제휴 진출이 리스크 대비 효율 우위", "template": "compare2", "source_refs": []}
    ]
  },
  "slides": [
    {"chapter_id": "ch01", "slots": {"template": "cover", "title": "시장 진입 검토", "subtitle": "3개 후보 시장 비교 분석", "date": "2026-08-27", "audience": "경영진 보고"}},
    {"chapter_id": "ch02", "slots": {"template": "summary", "conclusion": "3개 시장 중 1곳이 진입 요건을 충족", "points": [
      {"text": "후보 3개 시장의 규모, 성장률, 규제 환경을 비교", "level": 0},
      {"text": "정량 지표는 공개 통계 기준, 정성 평가는 현지 인터뷰 기준", "level": 0},
      {"text": "재무 시뮬레이션은 보수 시나리오 단일 적용", "level": 1}
    ]}},
    {"chapter_id": "ch03", "slots": {"template": "divider", "section_no": "1", "section_title": "시장 현황"}},
    {"chapter_id": "ch04", "slots": {"template": "bullet_box", "bullets": [
      {"text": "A 시장: 규모 최대, 성장 정체", "level": 0},
      {"text": "B 시장: 규모 중간, 연 12% 성장", "level": 0},
      {"text": "성장 동인: 구독형 소비 확산", "level": 1},
      {"text": "C 시장: 규모 최소, 규제 불확실성", "level": 0}
    ], "conclusion": "성장률 기준으로는 B 시장이 우위", "footnote": "주: 규모는 2025년 공개 통계 기준"}},
    {"chapter_id": "ch05", "slots": {"template": "table", "columns": ["지표", "A 시장", "B 시장", "C 시장"], "rows": [
      ["시장 규모", "12.0조 원", "6.5조 원", "2.1조 원"],
      ["연 성장률", "2%", "12%", "8%"],
      ["규제 리스크", "낮음", "중간", "높음"]
    ], "footnote": "주: 성장률은 3개년 평균"}},
    {"chapter_id": "ch06", "slots": {"template": "compare2",
      "left": {"heading": "직접 진출", "bullets": [{"text": "통제력 높음", "level": 0}, {"text": "초기 투자 큼", "level": 0}]},
      "right": {"heading": "제휴 진출", "bullets": [{"text": "초기 투자 작음", "level": 0}, {"text": "현지 정보 접근 유리", "level": 0}]},
      "conclusion": "직접 진출보다 제휴 진출이 리스크 대비 효율 우위"}}
  ]
}
```

- [ ] **Step 2: 회귀 테스트 작성**

`backend/tests/test_regression.py`:

```python
"""방법론 히스토리의 실패 목록을 고정하는 회귀 묶음 (설계서 8).

항목: 어절 줄바꿈 속성, 12pt 하한, 페이지당 크기 단계, 역할 태깅,
내보내기 전후 deck.json 불변, 결정론(같은 입력 → 같은 산출).
"""

import shutil
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn

from slidecaptain.export.exporter import export_deck
from slidecaptain.models.preset import BODY_MIN_PT, FOOTNOTE_MIN_PT

SAMPLE = Path("backend/samples/sample_deck.json")


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    work = tmp_path_factory.mktemp("regression")
    deck_path = work / "deck.json"
    shutil.copy(SAMPLE, deck_path)
    out = export_deck(deck_path, work / "exports")
    return Presentation(str(out))


def _iter_runs(prs):
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    yield from para.runs
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for para in cell.text_frame.paragraphs:
                            yield from para.runs


def test_every_run_has_korean_lang(exported):
    runs = list(_iter_runs(exported))
    assert runs, "run이 하나도 없으면 테스트가 무의미하다"
    for run in runs:
        rPr = run._r.find(qn("a:rPr"))
        assert rPr is not None and rPr.get("lang") == "ko-KR"


def test_no_run_below_floors(exported):
    # 각주와 쪽번호는 각주 하한(9pt), 그 밖의 모든 역할은 본문 하한(12pt) 이상
    for slide in exported.slides:
        for shape in slide.shapes:
            small_ok = shape.name.endswith(":footnote") or shape.name.endswith(":page_number")
            floor = FOOTNOTE_MIN_PT if small_ok else BODY_MIN_PT
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        assert run.font.size.pt >= floor, f"{shape.name}: {run.font.size.pt}pt"
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                assert run.font.size.pt >= BODY_MIN_PT


def test_every_shape_carries_role_tag(exported):
    for slide in exported.slides:
        for shape in slide.shapes:
            assert ":" in shape.name, f"역할 태그 없는 도형: {shape.name!r}"


def test_body_area_font_steps_at_most_two_per_content_slide(exported):
    # 표지(1장)와 간지(3장)는 예외. 본문 장만 검사한다
    content_indexes = [1, 3, 4, 5]  # 0부터: summary, bullet_box, table, compare2
    for idx in content_indexes:
        slide = exported.slides[idx]
        sizes = set()
        for shape in slide.shapes:
            if shape.name.endswith(":title") or shape.name.endswith(":page_number"):
                continue
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        if not shape.name.endswith(":footnote"):
                            sizes.add(run.font.size.pt)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                sizes.add(run.font.size.pt)
        assert len(sizes) <= 2, f"{idx + 1}번째 장의 본문 크기 단계가 {sorted(sizes)}로 2개를 넘습니다"


def test_deterministic_export(tmp_path):
    def signature(prs):
        return [
            [
                (s.name, s.left, s.top, s.width, s.height,
                 s.text_frame.text if s.has_text_frame else "")
                for s in slide.shapes
            ]
            for slide in prs.slides
        ]

    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    for d in (a_dir, b_dir):
        d.mkdir()
        shutil.copy(SAMPLE, d / "deck.json")
    out_a = export_deck(a_dir / "deck.json", a_dir / "exports")
    out_b = export_deck(b_dir / "deck.json", b_dir / "exports")
    assert signature(Presentation(str(out_a))) == signature(Presentation(str(out_b)))


def test_sample_deck_json_not_modified_by_export(tmp_path):
    deck_path = tmp_path / "deck.json"
    shutil.copy(SAMPLE, deck_path)
    before = deck_path.read_bytes()
    export_deck(deck_path, tmp_path / "exports")
    assert deck_path.read_bytes() == before
```

- [ ] **Step 3: 전체 실행**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: 전 태스크 테스트 포함 전부 PASS

- [ ] **Step 4: 실물 확인 (수동)**

```powershell
backend/.venv/Scripts/python.exe -m slidecaptain export backend/samples/sample_deck.json --out backend/tests/_out
```

Expected: `내보내기 완료: ...시장 진입 검토 견본_v001.pptx`. PowerPoint로 열어 6장이 규칙대로 보이는지 눈으로 확인한다 (제목 위치 균일, 결론 박스, 표 스타일, 어절 줄바꿈).

- [ ] **Step 5: 커밋**

```bash
git add backend/samples/sample_deck.json backend/tests/test_regression.py
git commit -m "test: 견본 덱과 회귀 테스트 묶음 (실패 목록의 테스트화)"
```

---

## 완료 기준

- [ ] `backend/.venv/Scripts/python.exe -m pytest backend/tests -q` 전부 통과
- [ ] 견본 덱 내보내기 실물을 PowerPoint에서 눈으로 확인
- [ ] superpowers:requesting-code-review로 리뷰 후 superpowers:finishing-a-development-branch로 마무리 (머지 4옵션 제시)
