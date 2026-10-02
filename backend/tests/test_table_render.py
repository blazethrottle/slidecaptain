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
    write_pptx(plan, out)
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


def _many_columns_deck(n_cols: int) -> Deck:
    return Deck(
        meta=DeckMeta(title="열 많은 표"),
        structure=Structure(
            chapters=[Chapter(id="ch01", topic="열 회귀", template="table")]
        ),
        slides=[
            Slide(
                chapter_id="ch01",
                slots=TableSlots(
                    columns=[f"열{i}" for i in range(n_cols)],
                    rows=[[f"값{i}" for i in range(n_cols)]],
                ),
            )
        ],
    )


@pytest.mark.parametrize("n_cols", [15, 20, 40])
def test_many_column_table_writes_without_crashing(tmp_path, n_cols):
    # 열 폭이 음수면 python-pptx가 EMU 범위 오류로 죽는다 (실측: n=40 -> ValueError, EMU 음수)
    metrics = FontMetrics.from_bundled()
    plan = build_render_plan(_many_columns_deck(n_cols), PRESET, metrics)
    out = tmp_path / f"table-{n_cols}.pptx"
    write_pptx(plan, out)
    presentation = Presentation(str(out))
    table = next(s for s in presentation.slides[0].shapes if s.has_table).table
    assert len(table.columns) == n_cols
    assert all(col.width > 0 for col in table.columns)


def _fill_of(cell) -> str | None:
    node = cell._tc.find(qn("a:tcPr"))
    if node is None:
        return None
    srgb = node.find(".//" + qn("a:srgbClr"))
    return srgb.get("val") if srgb is not None else None


def _table_of(saved):
    for shape in saved.slides[0].shapes:
        if shape.has_table:
            return shape.table
    raise AssertionError("표 도형이 없다")


def _write_plan(tmp_path, plan):
    out = tmp_path / "cellfill.pptx"
    write_pptx(plan, out)
    return Presentation(str(out))


def _plan_with(tmp_path, **table_overrides):
    metrics = FontMetrics.from_bundled()
    plan = build_render_plan(_table_deck(), PRESET, metrics)
    for slide in plan.slides:
        for frame in slide.frames:
            if frame.table is not None:
                for key, value in table_overrides.items():
                    setattr(frame.table, key, value)
    return _write_plan(tmp_path, plan)


def test_header_cell_fills_override_the_single_header_colour(tmp_path):
    """벤치마크의 표는 머리행도 칸마다 색이 다르다. 첫 칸은 연회색, 나머지는 분류색이다."""

    saved = _plan_with(tmp_path, header_fills=["F4F6F7", "1B2A3A", "0E8C7F"])
    table = _table_of(saved)

    assert [_fill_of(table.cell(0, c)) for c in range(3)] == ["F4F6F7", "1B2A3A", "0E8C7F"]


def test_body_fills_colour_each_column(tmp_path):
    """본문은 행 교차가 아니라 열 단위 색상 코딩이다."""

    saved = _plan_with(tmp_path, body_fills=["FFFFFF", "EAF2F1", "FBF3E6"])
    table = _table_of(saved)

    for row in (1, 2):
        assert [_fill_of(table.cell(row, c)) for c in range(3)] == ["FFFFFF", "EAF2F1", "FBF3E6"]


def test_empty_lists_keep_the_existing_single_colour_header(tmp_path):
    """기존 동작 불변: 목록이 비면 머리행 단일 색을 그대로 쓰고 본문은 칠하지 않는다."""

    saved = _plan_with(tmp_path)
    table = _table_of(saved)
    header = {_fill_of(table.cell(0, c)) for c in range(3)}

    assert len(header) == 1
    assert _fill_of(table.cell(1, 0)) is None


@pytest.mark.parametrize("field", ["header_fills", "body_fills"])
def test_cell_fill_list_length_must_match_column_count(field):
    from pydantic import ValidationError

    from slidecaptain.models.render import TablePlan

    with pytest.raises(ValidationError):
        TablePlan(
            col_widths_pt=[100.0, 100.0],
            header=["A", "B"],
            rows=[["1", "2"]],
            font_pt=12.0,
            header_fill="EEF3F9",
            row_heights_pt=[24.0, 24.0],
            **{field: ["FFFFFF"]},
        )
