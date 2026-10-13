"""직접 수정의 렌더 적용과 PPTX (개정판 D3c-2, 계획 4.4, 4.6).

수정값 다섯 종의 렌더 결과, 빌더 안 글자 배율(문단과 경고가 같은 배율, 높이와 자리 불변), 한계 자르기와 읽기 하한
경고, 페이지 안 자르기, 표 묶음, 숨김과 부분 강조와 차트, PPTX 다시 읽기 대조, 수정값 없는 덱의 렌더 계획과
PPTX 바이트 불변, 출력 지문, 숨긴 근거 표시 검사, 최대 크기 라우트를 지킨다.
"""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.util import Emu, Pt

from slidecaptain.export import pptx_writer
from slidecaptain.export.pptx_writer import write_pptx
from slidecaptain.layout.direct_edits import warning_key
from slidecaptain.layout.engine import build_render_plan
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Chapter, Deck, DeckMeta, Slide, Structure
from slidecaptain.models.direct_edit import frame_keys, numeric_path_key
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.quality import assess_quality
from slidecaptain.server.app import create_app
from slidecaptain.storage.file_store import FileProjectStore

FIXTURES = Path(__file__).parent / "fixtures"
METRICS = FontMetrics.load_default()
PRESET = Preset()


def _deck(template: str, slots: dict, *, topic="장 제목", edits=None, **slide) -> Deck:
    return Deck(meta=DeckMeta(title="보고"),
                structure=Structure(chapters=[Chapter(id="c1", topic=topic, template=template)]),
                slides=[Slide(chapter_id="c1", slots={"template": template, **slots}, direct_edits=edits or {}, **slide)])


def _plan(deck: Deck, **kw):
    return build_render_plan(deck, PRESET, METRICS, **kw)


def _frames(plan) -> dict:
    return {f.name.split(":", 1)[1]: f for f in plan.slides[0].frames}


BULLETS = {"bullets": [{"text": "첫 항목"}, {"text": "둘째 항목"}], "conclusion": "결론 문장", "footnote": "출처: 사내 자료"}
CARDS = {"cards": [{"heading": "A", "badge": "1", "tail": "끝", "emphasis": True, "bullets": [{"text": "가"}]},
                   {"heading": "B", "bullets": [{"text": "나"}]}]}


# -- 위치 ---------------------------------------------------------------------------------

def test_move_adds_the_offset_records_the_engine_position_and_stays_on_the_page():
    plain = _frames(_plan(_deck("bullet_box", BULLETS)))
    moved = _frames(_plan(_deck("bullet_box", BULLETS, edits={"conclusion": {"dx_pt": 30, "dy_pt": -20},
                                                                  "title": {"dx_pt": 5000, "dy_pt": -5000}})))
    c, base = moved["conclusion"], plain["conclusion"]
    assert (c.x, c.y, c.w, c.h) == (base.x + 30, base.y - 20, base.w, base.h)
    assert (c.base_x, c.base_y) == (base.x, base.y)
    t = moved["title"]
    assert (t.x, t.y) == (PRESET.page_width_pt - t.w, 0.0)  # 페이지 안으로 자른다
    assert moved["bullets"].base_x is None  # 수정값이 없는 프레임에는 기본 자리 칸을 싣지 않는다


def test_table_group_moves_chart_and_conditions_together_and_clips_as_one():
    from test_comparison_charts_spans import chart_sample

    from slidecaptain.models.expression import ChartSpec

    deck, sources = chart_sample()
    deck.slides[0].chart = ChartSpec(rule_version="comparison-chart-v1",
                                     comparison_id=deck.structure.story_plan.comparisons[0].id, kind="column")
    plain = _frames(build_render_plan(deck, PRESET, METRICS, sources=sources))
    deck.slides[0].direct_edits = {"table": {"dx_pt": 0, "dy_pt": 10000}}
    deck = Deck.model_validate(deck.model_dump(mode="json"))
    moved = _frames(build_render_plan(deck, PRESET, METRICS, sources=sources))
    dy = moved["chart"].y - plain["chart"].y
    assert dy > 0 and moved["chart_conditions"].y - plain["chart_conditions"].y == pytest.approx(dy)
    bottom = max(f.y + f.h for k, f in moved.items() if k in ("chart", "chart_conditions"))
    assert bottom == pytest.approx(PRESET.page_height_pt)


# -- 글자 크기 ------------------------------------------------------------------------------

@pytest.mark.parametrize("template,slots,key", [
    ("bullet_box", BULLETS, "bullets"), ("bullet_box", BULLETS, "conclusion"), ("bullet_box", BULLETS, "footnote"),
    ("bullet_box", BULLETS, "title"), ("cards", CARDS, "card0"), ("callout", {"text": "핵심"}, "text"),
    ("process", {"steps": [{"heading": f"단계{i}", "subtitle": "부", "notes": ["라벨"]} for i in range(3)]}, "step1"),
    ("process", {"steps": [{"heading": f"단계{i}", "notes": ["라벨"]} for i in range(3)]}, "step2_labels"),
    ("matrix", {"rows": [{"category": f"분류{i}", "primary": "대표", "items": ["가"]} for i in range(3)]}, "row0_items"),
    ("cover", {"title": "제목", "subtitle": "부제", "date": "2026"}, "date"),
    ("divider", {"section_no": "1", "section_title": "구분"}, "section_title"),
])
def test_font_scale_scales_every_paragraph_of_the_element_but_not_its_box(template, slots, key):
    """배율은 문단 크기와 줄바꿈과 경고에만 쓰고 상자 크기와 자리는 바꾸지 않는다 (재리뷰 RR2)."""
    plain = _frames(_plan(_deck(template, slots, eyebrow="" if template in ("cover", "divider") else "")))
    scaled_plan = _plan(_deck(template, slots, edits={key: {"font_scale": 1.25}}))
    scaled = _frames(scaled_plan)
    names = [n for n in plain if n == key]
    assert names
    for name in names:
        a, b = plain[name], scaled[name]
        assert (a.x, a.y, a.w, a.h) == (b.x, b.y, b.w, b.h)
        assert [p.font_pt for p in b.paras] == [round(p.font_pt * 1.25, 2) for p in a.paras]
    # 다른 요소는 그대로다
    for name, frame in plain.items():
        if name != key:
            assert [p.font_pt for p in frame.paras] == [p.font_pt for p in scaled[name].paras]


def test_paragraphs_and_warnings_use_the_same_scale():
    """문단만 키우고 경고는 기본 크기로 계산하면 넘친 상자에 경고가 없다 (재리뷰 RR26)."""
    long_title = "아주 긴 장 제목이 한 줄을 넘어 두 줄로 넘어가는지 확인한다"
    deck = _deck("bullet_box", BULLETS, topic=long_title)
    assert not [w for w in _plan(deck).slides[0].warnings if w.slot == "title"]
    big = _deck("bullet_box", BULLETS, topic=long_title, edits={"title": {"font_scale": 1.6}})
    assert [w for w in _plan(big).slides[0].warnings if w.slot == "title"]
    card = _deck("cards", CARDS, edits={"card0": {"font_scale": 1.3}})
    slots = {w.slot for w in _plan(card).slides[0].warnings}
    assert "card0_badge" in slots  # 배지 고정 높이를 넘는다(빌더의 구역 경고가 새 크기로 계산됨)


def test_font_scale_is_clamped_to_powerpoint_limits_with_a_warning():
    deck = _deck("bullet_box", BULLETS, edits={"conclusion": {"font_scale": 500}, "footnote": {"font_scale": 0.01}})
    plan = _plan(deck)
    frames = _frames(plan)
    upper = int(1584 / PRESET.spacing.line_spacing)
    assert max(p.font_pt for p in frames["conclusion"].paras) == pytest.approx(upper)
    assert min(p.font_pt for p in frames["footnote"].paras) == pytest.approx(1.0)
    messages = {w.slot: w.message for w in plan.slides[0].warnings if "맞췄습니다" in w.message}
    assert set(messages) == {"conclusion", "footnote"}


def test_shrinking_below_the_reading_floor_warns_but_is_allowed():
    """막으면 기본 크기가 하한과 같은 본문을 줄일 수 없다 (재리뷰 RR18)."""
    plan = _plan(_deck("bullet_box", BULLETS, edits={"bullets": {"font_scale": 0.9}}))
    assert min(p.font_pt for p in _frames(plan)["bullets"].paras) < 12
    [warning] = [w for w in plan.slides[0].warnings if "읽기 하한" in w.message]
    assert warning.slot == "bullets"


# -- 색 -------------------------------------------------------------------------------------

def test_text_color_paints_every_paragraph_and_fill_keeps_designed_text_color():
    plan = _plan(_deck("bullet_box", BULLETS, edits={"bullets": {"text_color": "danger"}, "conclusion": {"fill": "surface2"}}))
    frames = _frames(plan)
    assert {p.color for p in frames["bullets"].paras} == {PRESET.colors.danger}
    assert frames["conclusion"].fill == PRESET.colors.surface2
    assert {p.color for p in frames["conclusion"].paras} == {PRESET.colors.accent}  # 결론의 강조색은 그대로 (리뷰 저장 S16)


def test_fill_on_luminance_elements_recomputes_text_color_unless_text_color_is_set():
    from slidecaptain.metrics.color import readable_text_color

    c = PRESET.colors
    frames = _frames(_plan(_deck("cards", CARDS, edits={"card0": {"fill": "surface1"}})))
    expected = readable_text_color(c.surface1, light=c.background, dark=c.text)
    assert frames["card0"].fill == c.surface1 and {p.color for p in frames["card0"].paras} == {expected}
    frames = _frames(_plan(_deck("cards", CARDS, edits={"card0": {"fill": "surface1", "text_color": "accent1"}})))
    assert {p.color for p in frames["card0"].paras} == {c.accent1}


# -- 숨김 -----------------------------------------------------------------------------------

def test_hidden_frame_stays_in_the_plan_flagged_and_its_warnings_are_dropped():
    long = {**BULLETS, "conclusion": "넘치는 결론 " * 40}
    plain = _plan(_deck("bullet_box", long))
    assert any(w.slot == "conclusion" for w in plain.slides[0].warnings)
    plan = _plan(_deck("bullet_box", long, edits={"conclusion": {"hidden": True}}))
    assert _frames(plan)["conclusion"].hidden is True
    assert not any(warning_key(w.slot, frame_keys(_deck("bullet_box", long).slides[0])) == "conclusion"
                   for w in plan.slides[0].warnings)


def test_hiding_an_element_with_a_text_span_does_not_break_the_plan():
    """1판대로면 부분 강조가 숨긴 프레임을 찾지 못해 덱 전체의 렌더가 실패했다 (계획 리뷰 저장 S9)."""
    fixture = json.loads((FIXTURES / "q2d-numeric-review.json").read_text(encoding="utf-8"))
    deck = Deck.model_validate(fixture["deck"])
    slide = deck.slides[0]
    text = slide.slots.bullets[0].text
    payload = deck.model_dump(mode="json")
    payload["slides"][0]["text_spans"] = [{"slot": "bullets", "index": 0, "start": 0, "end": min(2, len(text)),
                                           "role": "bold", "text_sha256": __import__("hashlib").sha256(text.encode()).hexdigest()}]
    payload["slides"][0]["direct_edits"] = {"bullets": {"hidden": True}}
    hidden = Deck.model_validate(payload)
    plan = build_render_plan(hidden, PRESET, METRICS, sources=fixture["sources"])
    assert _frames(plan)["bullets"].hidden is True
    payload["slides"][0]["direct_edits"] = {}
    shown = build_render_plan(Deck.model_validate(payload), PRESET, METRICS, sources=fixture["sources"])
    assert _frames(shown)["bullets"].paras[0].runs  # 다시 보이면 강조가 돌아온다


def test_hidden_table_skips_chart_construction_even_when_the_chart_cannot_be_built():
    from test_comparison_charts_spans import chart_sample

    from slidecaptain.models.expression import ChartSpec

    deck, sources = chart_sample()
    deck.slides[0].chart = ChartSpec(rule_version="comparison-chart-v1",
                                     comparison_id=deck.structure.story_plan.comparisons[0].id, kind="column")
    with pytest.raises(Exception):
        build_render_plan(deck, PRESET, METRICS, sources={})  # 자료가 없으면 차트를 만들 수 없다
    deck.slides[0].direct_edits = {"table": {"hidden": True}}
    deck = Deck.model_validate(deck.model_dump(mode="json"))
    plan = build_render_plan(deck, PRESET, METRICS, sources={})
    frames = _frames(plan)
    assert frames["table"].hidden is True and "chart" not in frames


# -- 직렬화와 PPTX ---------------------------------------------------------------------------

def _sample_decks():
    for path in sorted(FIXTURES.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        deck = payload.get("deck") if isinstance(payload, dict) else None
        if isinstance(deck, dict) and deck.get("slides"):
            try:
                yield path.name, Deck.model_validate(deck), payload.get("sources") or {}
            except Exception:
                continue


def test_plans_without_edits_have_no_new_fields():
    for name, deck, sources in _sample_decks():
        try:
            plan = build_render_plan(deck, PRESET, METRICS, sources=sources)
        except Exception:
            continue
        text = plan.model_dump_json()
        assert '"base_x"' not in text and '"hidden"' not in text, name


def test_pptx_bytes_are_unchanged_for_decks_without_edits(tmp_path, monkeypatch):
    """글자 크기는 1/100pt 반올림으로 바꿨지만 지금 프리셋 크기에서는 버림과 같아 바이트가 그대로다 (재리뷰 RR1)."""
    original = pptx_writer._style_run

    def floor_style_run(run, para, style):
        original(run, para, style)
        run.font.size = Pt(para.font_pt)

    checked = 0
    for name, deck, sources in _sample_decks():
        try:
            plan = build_render_plan(deck, PRESET, METRICS, sources=sources)
        except Exception:
            continue
        new = tmp_path / f"{name}.new.pptx"
        write_pptx(plan, new)
        monkeypatch.setattr(pptx_writer, "_style_run", floor_style_run)
        old = tmp_path / f"{name}.old.pptx"
        write_pptx(plan, old)
        monkeypatch.setattr(pptx_writer, "_style_run", original)
        assert new.read_bytes() == old.read_bytes(), name
        checked += 1
    assert checked >= 2


def test_pptx_matches_the_plan_for_edited_elements(tmp_path):
    deck = _deck("bullet_box", BULLETS, edits={
        # 12pt x 0.8575 = 10.29pt. Pt의 버림은 1028(10.28pt)로 기록한다 (계획 리뷰 저장 S8의 실측 값)
        "conclusion": {"dx_pt": 33.3, "dy_pt": -12.7, "font_scale": 0.8575, "text_color": "danger", "fill": "surface3"},
        "footnote": {"hidden": True},
    })
    plan = _plan(deck)
    path = tmp_path / "edited.pptx"
    write_pptx(plan, path)
    slide = Presentation(path).slides[0]
    shapes = {s.name: s for s in slide.shapes}
    assert "c1:footnote" not in shapes  # 숨긴 도형은 쓰지 않는다
    frame = _frames(plan)["conclusion"]
    shape = shapes["c1:conclusion"]
    assert (shape.left, shape.top) == (Emu(round(frame.x * 12700)), Emu(round(frame.y * 12700)))
    runs = [r for p in shape.text_frame.paragraphs for r in p.runs]
    assert frame.paras[0].font_pt == 10.29
    assert {r.font.size.centipoints for r in runs} == {1029}
    assert {str(r.font.color.rgb) for r in runs} == {PRESET.colors.danger.upper()}
    assert str(shape.fill.fore_color.rgb) == PRESET.colors.surface3.upper()


# -- 지문과 검토 ------------------------------------------------------------------------------

def test_moving_an_element_changes_the_export_fingerprint_only_when_edited():
    deck = _deck("bullet_box", BULLETS)
    plain = assess_quality(deck, PRESET, _plan(deck))
    again = assess_quality(deck, PRESET, _plan(deck))
    moved_deck = _deck("bullet_box", BULLETS, edits={"title": {"dx_pt": 1, "dy_pt": 0}})
    moved = assess_quality(moved_deck, PRESET, _plan(moved_deck))
    assert plain.input_fingerprint == again.input_fingerprint != moved.input_fingerprint


def test_hidden_evidence_check_appears_only_when_evidence_is_hidden():
    deck = _deck("bullet_box", BULLETS, eyebrow="분류", edits={"eyebrow": {"hidden": True}})
    names = [c.name for c in assess_quality(deck, PRESET, _plan(deck)).checks]
    assert "hidden_evidence" not in names  # 근거가 아닌 요소의 숨김은 검사를 넣지 않는다
    deck = _deck("bullet_box", BULLETS, edits={"footnote": {"hidden": True}})
    report = assess_quality(deck, PRESET, _plan(deck))
    [check] = [c for c in report.checks if c.name == "hidden_evidence"]
    assert (check.status, check.failed, check.chapter_ids) == ("failed", 1, ["c1"])
    assert report.status == "needs_revision"


def test_numeric_paths_map_to_element_keys():
    cover = Slide(chapter_id="c1", slots={"template": "cover", "title": "t", "subtitle": "s"}, eyebrow="e")
    assert numeric_path_key(cover, "/slots/title") == "cover_title"
    assert numeric_path_key(cover, "/slots/subtitle") == "subtitle"
    assert numeric_path_key(cover, "/subtitle") is None and numeric_path_key(cover, "/eyebrow") is None
    table = Slide(chapter_id="c1", slots={"template": "table", "columns": ["a", "b"], "rows": [["1", "2"]], "footnote": "f"})
    assert numeric_path_key(table, "/slots/rows/0/1") == "table" and numeric_path_key(table, "/slots/footnote") == "footnote"
    process = _deck("process", {"steps": [{"heading": "h", "subtitle": "s", "notes": ["n"]} for _ in range(3)]}).slides[0]
    assert numeric_path_key(process, "/slots/steps/1/notes/0") == "step1_labels"
    assert numeric_path_key(process, "/slots/steps/1/subtitle") == "step1"
    matrix = _deck("matrix", {"rows": [{"category": "c", "primary": "p", "items": ["i"]} for _ in range(3)]}).slides[0]
    assert numeric_path_key(matrix, "/slots/rows/2/items/0") == "row2_items"
    assert numeric_path_key(matrix, "/slots/rows/2/primary") == "row2_primary"
    assert numeric_path_key(_deck("bullet_box", BULLETS).slides[0], "/topic") == "title"


def test_warning_slots_map_to_element_keys():
    keys = frame_keys(_deck("process", {"steps": [{"heading": "h", "notes": ["n"]} for _ in range(3)]}).slides[0])
    assert warning_key("step0_labels_1", keys) == "step0_labels"
    assert warning_key("step0_heading", keys) == "step0"
    assert warning_key("step0_badge", keys) == "step0_badge"
    cards = frame_keys(_deck("cards", CARDS).slides[0])
    assert warning_key("card0_badge", cards) == "card0" and warning_key("card0_tail", cards) == "card0"
    assert warning_key("bullets_span", frame_keys(_deck("bullet_box", BULLETS).slides[0])) == "bullets"
    assert warning_key("chart", {"table"}) == "table"


# -- 최대 크기 라우트 ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    store = FileProjectStore(tmp_path / "projects")
    store.create_project("p1")
    with TestClient(create_app(store), headers={"X-Requested-With": "SlideCaptain"}) as c:
        yield c


def test_font_limit_reports_the_largest_size_that_does_not_overflow(client):
    deck = _deck("bullet_box", BULLETS, eyebrow="분류")
    body = {"deck": deck.model_dump(mode="json"), "chapter_id": "c1", "key": "eyebrow"}
    limit = client.post("/api/projects/p1/direct-edits/font-limit", json=body).json()
    assert limit["current_pt"] == limit["base_pt"] == PRESET.font_roles.eyebrow_pt
    # 아이브로우는 높이가 한 줄에 딱 맞아 키울 여유가 없다 (재리뷰 RR2 실측: 최대 배율 1.000)
    assert limit["fits_up_to_pt"] == pytest.approx(PRESET.font_roles.eyebrow_pt, abs=0.05)
    assert limit["min_pt"] == 1.0 and limit["max_pt"] > 100
    body["key"] = "title"
    title = client.post("/api/projects/p1/direct-edits/font-limit", json=body).json()
    assert title["fits_up_to_pt"] > PRESET.font_roles.title_pt


def test_font_limit_rejects_elements_without_font_and_unknown_chapters(client):
    deck = _deck("table", {"columns": ["a"], "rows": [["1"]]})
    body = {"deck": deck.model_dump(mode="json"), "chapter_id": "c1", "key": "table"}
    assert client.post("/api/projects/p1/direct-edits/font-limit", json=body).status_code == 422
    body["chapter_id"] = "없음"
    assert client.post("/api/projects/p1/direct-edits/font-limit", json=body).status_code == 404


def test_warning_keys_fixture_matches_the_engine():
    """화면의 warningKey(D3c-3)가 같은 결과를 내는지 지키는 고정 파일. 모든 템플릿의 실제 경고 slot을 담는다."""
    cases = json.loads((FIXTURES / "warning-keys.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) > 100
    for case in cases:
        assert warning_key(case["slot"], set(case["keys"])) == case["key"], case
    assert [c["slot"] for c in cases if c["key"] is None] == ["unknown_slot"]
