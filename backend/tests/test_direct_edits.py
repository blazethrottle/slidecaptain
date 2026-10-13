"""직접 수정의 저장 계약과 형식 등급 (개정판 D3c-1, 계획 4.2, 4.3).

기존 덱의 바이트 불변, 정규화 다섯 규칙, 요소 열쇠와 빌더의 프레임 이름 일치, 등급 4와 schema_version 3,
연속 저장의 기록 불변, 보존본의 schema_version, 0.2.0 되돌림 표시를 지킨다. 0.2.0과 D3b 빌드의 별도 프로세스
왕복은 test_legacy_compat에 있다.
"""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from slidecaptain.layout.templates import build_slide
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Chapter, Deck, DeckMeta, Slide, Structure
from slidecaptain.models.direct_edit import ElementEdit, frame_keys, normalize_edits
from slidecaptain.models.preset import Preset
from slidecaptain.storage import project_format
from slidecaptain.storage.file_store import FileProjectStore

FIXTURES = Path(__file__).parent / "fixtures"
KEYS_FIXTURE = FIXTURES / "frame-keys.json"
METRICS = FontMetrics.load_default()

# 템플릿별 표본. "full"은 선택 칸을 모두 채우고, "bare"는 선택 칸을 비운다(프레임이 생기고 사라지는 조건을 함께 본다)
SAMPLES: dict[str, dict[str, dict]] = {
    "cover": {"full": {"title": "제목", "subtitle": "부제", "date": "2026-10-13"}, "bare": {"title": "제목"},
              "blank": {"title": "제목", "subtitle": " ", "date": "\u3000"}},
    "divider": {"full": {"section_no": "1", "section_title": "구분"}, "bare": {"section_title": "구분"},
                "blank": {"section_no": " ", "section_title": "구분"}},
    "summary": {"full": {"conclusion": "결론", "points": [{"text": "요점"}]}, "bare": {"conclusion": "결론"},
                "blank": {"conclusion": "결론", "points": [{"text": " "}]}},
    "bullet_box": {"full": {"bullets": [{"text": "항목"}], "conclusion": "결론", "footnote": "출처"},
                   "bare": {"conclusion": "결론"}, "blank": {"conclusion": "결론", "footnote": " "}},
    "table": {"full": {"columns": ["구분", "값"], "rows": [["A", "1"]], "footnote": "출처"},
              "bare": {"columns": ["구분"], "rows": []}, "blank": {"columns": ["구분"], "rows": [], "footnote": "\t"}},
    "compare2": {"full": {"conclusion": "결론", "left": {"heading": "A", "bullets": [{"text": "왼쪽"}]},
                          "right": {"heading": "B", "bullets": [{"text": "오른쪽"}]}},
                 "bare": {"conclusion": "결론", "left": {"heading": "A"}, "right": {"heading": "B"}},
                 "blank": {"conclusion": "결론", "left": {"heading": " "}, "right": {"heading": "B"}}},
    "callout": {"full": {"text": "핵심", "tone": "accent1"}, "bare": {"text": "핵심"}, "blank": {"text": " "}},
    "cards": {"full": {"cards": [{"heading": "A", "badge": "1", "tail": "끝", "emphasis": True},
                                 {"heading": "B", "bullets": [{"text": "항목"}]}, {"heading": "C"}, {"heading": "D"}]},
              "bare": {"cards": [{"heading": "A"}, {"heading": "B"}]},
              "blank": {"cards": [{"heading": "A", "badge": " ", "tail": "\n"}, {"heading": "B"}]}},
    "process": {"full": {"steps": [{"heading": f"단계{i}", "subtitle": "부", "notes": ["라벨"]} for i in range(6)]},
                "bare": {"steps": [{"heading": f"단계{i}"} for i in range(3)]},
                "blank": {"steps": [{"heading": f"단계{i}", "subtitle": " ", "notes": [" "]} for i in range(3)]}},
    "matrix": {"full": {"rows": [{"category": f"분류{i}", "primary": "대표", "items": ["가", "나"]} for i in range(6)]},
               "bare": {"rows": [{"category": f"분류{i}"} for i in range(3)]},
               "blank": {"rows": [{"category": f"분류{i}", "primary": " ", "items": [" "]} for i in range(3)]}},
}


def _slide(template: str, variant: str, common: bool, **extra) -> Slide:
    # 공백만 있는 공통 슬롯도 빌더는 프레임을 만든다. 화면이 trim()으로 판정하는 실수를 막는다 (D3c-1 리뷰 F6)
    eyebrow, subtitle = (" ", "\u3000") if variant == "blank" else ("분류", "한 문장 부제")
    return Slide(chapter_id="c1", slots={"template": template, **SAMPLES[template][variant]},
                 eyebrow=eyebrow if common else "", subtitle=subtitle if common else "", **extra)


def _configs():
    for template in SAMPLES:
        for variant in ("full", "bare", "blank"):
            for common in (False, True):
                yield template, variant, common


def _built_keys(slide: Slide) -> set[str]:
    chapter = Chapter(id="c1", topic="장 제목", template=slide.slots.template)
    plan = build_slide(chapter, slide.slots, 1, Preset(), METRICS, presenter="보고자",
                       eyebrow=slide.eyebrow, subtitle=slide.subtitle)
    names = {f.name.split(":", 1)[1] for f in plan.frames}
    names.discard("page_number")
    return {"table" if n in ("chart", "chart_conditions") else n for n in names}


@pytest.mark.parametrize("template,variant,common", list(_configs()))
def test_frame_keys_match_the_frames_the_builders_draw(template, variant, common):
    """frame_keys는 빌더의 프레임 생성 조건을 옮긴 것이다. 두 쪽이 어긋나면 수정값이 다른 요소에 붙거나 버려진다."""
    slide = _slide(template, variant, common)
    assert set(frame_keys(slide)) == _built_keys(slide)


def test_frame_keys_do_not_depend_on_the_chapter_title_or_meta():
    """장 제목과 메타는 이름 집합을 바꾸지 않는다. 그래서 정규화를 Slide 검증에서 할 수 있다 (재리뷰 RR6)."""
    slide = _slide("cover", "bare", False)
    for topic, presenter in (("", ""), ("아주 " * 30, "보고자")):
        chapter = Chapter(id="c1", topic=topic, template="cover")
        plan = build_slide(chapter, slide.slots, 1, Preset(), METRICS, presenter=presenter)
        assert {f.name.split(":", 1)[1] for f in plan.frames} - {"page_number"} == set(frame_keys(slide))


def test_comparison_chart_frames_share_the_table_key():
    from test_comparison_charts_spans import chart_sample

    from slidecaptain.layout.engine import build_render_plan
    from slidecaptain.models.expression import ChartSpec

    deck, sources = chart_sample()
    comparison = deck.structure.story_plan.comparisons[0]
    deck.slides[0].chart = ChartSpec(rule_version="comparison-chart-v1", comparison_id=comparison.id, kind="column")
    plan = build_render_plan(deck, Preset(), METRICS, sources=sources)
    names = {f.name.split(":", 1)[1] for f in plan.slides[0].frames} - {"page_number"}
    assert {"chart", "chart_conditions"} <= names
    assert {"table" if n in ("chart", "chart_conditions") else n for n in names} == set(frame_keys(deck.slides[0]))


def test_frame_keys_fixture_is_current():
    """화면의 열쇠 함수(D3c-3)와 같은 결과를 지키는 고정 파일. 바뀌면 화면도 함께 고친다."""
    expected = json.loads(KEYS_FIXTURE.read_text(encoding="utf-8"))
    actual = [
        {"template": t, "variant": v, "common": c,
         "keys": {k: {"kinds": sorted(spec.kinds), "drag": spec.drag} for k, spec in frame_keys(_slide(t, v, c)).items()}}
        for t, v, c in _configs()
    ]
    assert actual == expected["cases"]
    assert expected["samples"] == SAMPLES


# -- 정규화 ---------------------------------------------------------------------------

def _deck(**slide_kwargs) -> Deck:
    template = slide_kwargs.pop("template", "cards")
    variant = slide_kwargs.pop("variant", "full")
    slide = _slide(template, variant, False, **slide_kwargs)
    return Deck(meta=DeckMeta(title="보고"),
                structure=Structure(chapters=[Chapter(id="c1", topic="장 제목", template=template)]),
                slides=[slide])


def test_normalization_drops_unknown_unsupported_and_ineffective_values_and_sorts_keys():
    deck = _deck(direct_edits={
        "nope": {"hidden": True},                       # ① 없는 요소
        "card1": {"fill": "ink", "text_color": "accent1"},  # ② 강조가 아닌 카드는 채움이 없다
        "card0": {"hidden": False, "dx_pt": 0, "dy_pt": 0, "font_scale": 1},  # ③ 효과 없음 → ④ 빈 객체
        "title": {"dx_pt": 10, "dy_pt": -5},
    })
    edits = deck.slides[0].direct_edits
    assert list(edits) == ["card1", "title"]  # ⑤ 이름 순
    assert edits["card1"] == ElementEdit(text_color="accent1")
    assert edits["title"] == ElementEdit(dx_pt=10, dy_pt=-5)


def test_same_edits_in_a_different_order_give_the_same_bytes():
    """열쇠 순서가 다르면 같은 내용이 다른 ETag가 된다 (계획 리뷰 저장 S24)."""
    forward = _deck(direct_edits={"card1": {"hidden": True}, "title": {"dx_pt": 1, "dy_pt": 2}})
    backward = _deck(direct_edits={"title": {"dx_pt": 1, "dy_pt": 2}, "card1": {"hidden": True}})
    assert forward.model_dump_json() == backward.model_dump_json()


def test_emphasis_card_accepts_fill_and_loses_it_when_emphasis_is_turned_off():
    edited = _deck(direct_edits={"card0": {"fill": "accent2"}})
    assert edited.slides[0].direct_edits["card0"].fill == "accent2"
    payload = edited.model_dump(mode="json")
    payload["slides"][0]["slots"]["cards"][0]["emphasis"] = False
    assert Deck.model_validate(payload).slides[0].direct_edits == {}


def test_removed_list_item_drops_its_edit_and_the_deck_level_falls_back():
    deck = _deck(direct_edits={"card3": {"hidden": True}})
    assert deck.schema_version == 3
    payload = deck.model_dump(mode="json")
    payload["slides"][0]["slots"]["cards"].pop()
    again = Deck.model_validate(payload)
    assert again.slides[0].direct_edits == {}
    assert again.schema_version == 1


def test_table_and_badge_reject_font_and_callout_rejects_fill():
    table = _deck(template="table", direct_edits={"table": {"font_scale": 2, "text_color": "accent", "hidden": True}})
    assert table.slides[0].direct_edits["table"] == ElementEdit(hidden=True)
    process = _deck(template="process", direct_edits={"step0_badge": {"font_scale": 2, "fill": "accent1"}})
    assert process.slides[0].direct_edits["step0_badge"] == ElementEdit(fill="accent1")
    callout = _deck(template="callout", direct_edits={"text": {"fill": "accent1", "font_scale": 1.2}})
    assert callout.slides[0].direct_edits["text"] == ElementEdit(font_scale=1.2)


def test_empty_bullet_box_does_not_take_a_font_scale():
    deck = _deck(template="bullet_box", variant="bare", direct_edits={"bullets": {"font_scale": 1.5}})
    assert deck.slides[0].direct_edits == {}


@pytest.mark.parametrize("bad", [
    {"dx_pt": 1},                      # 한쪽만
    {"dx_pt": float("nan"), "dy_pt": 0},
    {"dx_pt": float("inf"), "dy_pt": 0},
    {"font_scale": 0},
    {"font_scale": -1},
    {"text_color": "surface1"},        # 글자용 역할이 아니다
    {"fill": "background"},            # 채움용 역할이 아니다
    {"unknown": 1},
    {"dx_pt": "12", "dy_pt": 0},       # 문자열 숫자 (D3c-1 리뷰 F4)
    {"dx_pt": True, "dy_pt": 0},
    {"hidden": 1},
    {"hidden": "yes"},
])
def test_invalid_edits_are_rejected(bad):
    with pytest.raises(ValidationError):
        _deck(direct_edits={"title": bad})


def test_diagram_slides_reject_direct_edits():
    payload = json.loads((FIXTURES / "q3b-project.json").read_text(encoding="utf-8")) \
        if (FIXTURES / "q3b-project.json").exists() else None
    if payload is None:
        pytest.skip("도식 덱 표본이 없다")
    deck = payload.get("deck", payload)
    for slide in deck["slides"]:
        if slide["slots"]["template"] == "diagram":
            slide["direct_edits"] = {"title": {"hidden": True}}
            break
    with pytest.raises(ValidationError, match="도식 페이지는 직접 수정을 지원하지 않습니다"):
        Deck.model_validate(deck)


def test_empty_and_all_null_edits_are_dropped_by_normalization_not_rejected():
    """빈 객체는 거절하지 않고 정규화 ④가 버린다. 화면이 칸을 지우는 중간 상태를 422로 막지 않기 위해서다 (D3c-1 리뷰 F3)."""
    deck = _deck(direct_edits={"title": {}, "card0": {"hidden": None, "fill": None}})
    assert deck.slides[0].direct_edits == {}
    assert deck.schema_version == 1


def test_vertical_or_horizontal_only_moves_are_kept():
    """세로로만 옮긴 수정이 저장 때 사라지지 않는다 (D3c-1 리뷰 F7)."""
    deck = _deck(direct_edits={"title": {"dx_pt": 0, "dy_pt": 5}, "card0": {"dx_pt": 5, "dy_pt": 0}})
    assert deck.slides[0].direct_edits["title"] == ElementEdit(dx_pt=0, dy_pt=5)
    assert deck.slides[0].direct_edits["card0"] == ElementEdit(dx_pt=5, dy_pt=0)


NORMALIZE_FIXTURE = FIXTURES / "normalize-cases.json"


def test_normalization_fixture_matches_the_server_rule():
    """화면의 normalizeEdits(D3c-3)가 같은 결과를 내는지 지키는 고정 파일 (D3c-1 리뷰 F12)."""
    data = json.loads(NORMALIZE_FIXTURE.read_text(encoding="utf-8"))
    assert len(data["cases"]) >= 10
    for case in data["cases"]:
        slide = _slide(case["template"], case["variant"], case["common"])
        edits = {k: ElementEdit.model_validate(v) for k, v in case["input"].items()}
        result = normalize_edits(edits, frame_keys(slide))
        assert list(result) == list(case["expected"]), case["name"]
        assert {k: v.model_dump() for k, v in result.items()} == case["expected"], case["name"]


def test_normalize_edits_is_idempotent():
    keys = frame_keys(_slide("matrix", "full", True))
    edits = {"row0_items": ElementEdit(dx_pt=3, dy_pt=4), "eyebrow": ElementEdit(text_color="ink")}
    once = normalize_edits(edits, keys)
    assert normalize_edits(once, keys) == once


# -- 바이트와 지문 불변 ------------------------------------------------------------------------

def _fixture_decks():
    for path in sorted(FIXTURES.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        deck = payload.get("deck") if isinstance(payload, dict) else None
        if isinstance(deck, dict) and deck.get("slides"):
            yield path.name, deck


def test_existing_decks_with_slides_serialize_without_the_new_field():
    """슬라이드가 있는 기존 덱에서 새 칸이 나타나지 않는다. 직렬화 함수를 하나 더 두는 실수를 이 표본이 잡는다(리뷰 저장 S5)."""
    samples = list(_fixture_decks())
    assert samples, "슬라이드가 있는 표본 덱이 없습니다"
    for name, raw in samples:
        try:
            deck = Deck.model_validate(raw)
        except ValidationError:
            continue
        dumped = deck.model_dump(mode="json")
        for slide in dumped["slides"]:
            assert "direct_edits" not in slide, name
            assert "chart" in slide or deck.slides[[s.chapter_id for s in deck.slides].index(slide["chapter_id"])].chart is None
        assert Deck.model_validate(dumped).model_dump_json() == deck.model_dump_json(), name


def test_output_dump_changes_only_when_edits_exist():
    from slidecaptain.models.report_purpose import output_dump

    plain = _deck()
    edited = _deck(direct_edits={"title": {"dx_pt": 4, "dy_pt": 0}})
    assert "direct_edits" not in json.dumps(output_dump(plain))
    assert output_dump(edited)["schema_version"] == 1  # 출력 지문은 버전을 1로 고정한다
    assert output_dump(edited) != output_dump(plain)


# -- 형식 등급과 기록 ----------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return FileProjectStore(tmp_path / "projects")


def test_edited_deck_is_level_four_with_schema_version_three_and_bytes_agree(store):
    deck = _deck(direct_edits={"title": {"hidden": True}})
    assert project_format.deck_format(deck) == 4
    assert deck.schema_version == 3
    assert project_format.deck_format_of_bytes(deck.model_dump_json().encode()) == 4
    # 바이트 판정은 schema_version이나 direct_edits 칸 어느 하나로도 등급 4를 안다
    payload = deck.model_dump(mode="json")
    payload["schema_version"] = 1
    assert project_format.deck_format_of_bytes(json.dumps(payload).encode()) == 4
    payload["schema_version"] = 3
    payload["slides"][0].pop("direct_edits")
    assert project_format.deck_format_of_bytes(json.dumps(payload).encode()) == 4


def test_repeated_saves_of_a_level_four_deck_do_not_grow_the_record(store):
    """1판대로면 저장마다 거짓 내림과 올림이 쌓였다 (계획 리뷰 저장 S3)."""
    store.create_project("p1")
    deck = _deck(direct_edits={"title": {"dx_pt": 5, "dy_pt": 5}})
    lengths = []
    for i in range(3):
        deck.slides[0].direct_edits["title"] = ElementEdit(dx_pt=5 + i, dy_pt=5)
        store.save_deck("p1", Deck.model_validate(deck.model_dump(mode="json")), snapshot=False)
        manifest = project_format.read_manifest(store.root / "p1")
        lengths.append(len(manifest.migrations))
        assert manifest.format_version == 4
        assert manifest.last_written_etag == store.deck_etag("p1")
    assert lengths == [lengths[0]] * 3
    assert [m.kind for m in manifest.migrations] == ["upgrade"]


def test_showing_a_hidden_element_again_lowers_the_level(store):
    """다시 보이기는 hidden: false를 남기지 않는다. 남으면 보이는 수정이 없는데도 이전 앱이 열지 못했다 (재리뷰 RR23)."""
    store.create_project("p1")
    store.save_deck("p1", _deck(direct_edits={"title": {"hidden": True}}), snapshot=False)
    store.save_deck("p1", _deck(direct_edits={"title": {"hidden": False}}), snapshot=False)
    raw = json.loads((store.root / "p1" / "deck.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert "direct_edits" not in raw["slides"][0]
    manifest = project_format.read_manifest(store.root / "p1")
    assert manifest.format_version == 1
    assert [m.kind for m in manifest.migrations] == ["upgrade", "downgrade"]


def test_level_three_to_four_records_an_upgrade_without_a_legacy_restore_point(store):
    store.create_project("p1")
    store.save_deck("p1", _deck(), snapshot=False)
    meta = {"title": "보고", "key_message": "핵심"}
    level3 = Deck.model_validate({**_deck().model_dump(mode="json"), "meta": meta})
    store.save_deck("p1", level3, snapshot=False)
    edited = Deck.model_validate({**_deck(direct_edits={"title": {"hidden": True}}).model_dump(mode="json"), "meta": meta})
    store.save_deck("p1", edited, snapshot=False)
    manifest = project_format.read_manifest(store.root / "p1")
    assert manifest.format_version == 4
    last = manifest.migrations[-1]
    assert (last.kind, last.from_format, last.to_format, last.snapshot_id) == ("upgrade", 3, 4, None)


def test_project_info_marks_a_revert_until_this_app_saves(store):
    """0.2.0이 등급 4 덱을 되돌린 뒤 이 앱의 저장 전까지만 알린다 (계획 4.2 E8, 재리뷰 RR19)."""
    store.create_project("p1")
    store.save_deck("p1", _deck(), snapshot=False)
    store.save_deck("p1", _deck(direct_edits={"title": {"hidden": True}}), snapshot=False)
    project = store.root / "p1"
    level4 = (project / "deck.json").read_bytes()
    # 0.2.0의 복원을 흉내 낸다: 지금 덱을 스냅샷으로 남기고 등급 1 복구 지점으로 덮는다
    pre = next(s.id for s in store.list_snapshots("p1") if s.kind == "pre_migration")
    (project / "snapshots" / "deck-29991231-235959-000000.json").write_bytes(level4)
    (project / "deck.json").write_bytes((project / "snapshots" / f"{pre}.json").read_bytes())
    [info] = store.list_projects()
    assert info.reverted_by_other_app is True
    assert info.model_dump()["reverted_by_other_app"] is True
    assert [s.id for s in store.list_snapshots("p1") if s.kind == "before_revert"] == ["deck-29991231-235959-000000"]
    store.save_deck("p1", store.load_deck("p1"), snapshot=False)
    [info] = store.list_projects()
    assert info.reverted_by_other_app is False
    assert "reverted_by_other_app" not in info.model_dump()  # 거짓이면 응답에서 빠진다
    assert [s.id for s in store.list_snapshots("p1") if s.kind == "before_revert"] == ["deck-29991231-235959-000000"]


# -- 보존본 ----------------------------------------------------------------------------------

def test_saved_draft_carries_the_schema_version_its_content_needs(store):
    """첫 저장 전에 보존한 덱의 옛 버전 값을 바로잡아 이전 빌드가 복원하며 수정값을 버리지 않게 한다 (리뷰 저장 S20)."""
    store.create_project("p1")
    raw = _deck(direct_edits={"title": {"hidden": True}}).model_dump(mode="json")
    raw["schema_version"] = 1
    info = store.save_draft("p1", deck=raw, reason="conflict", source="editor", base_etag=None)
    envelope = json.loads((store.root / "p1" / "drafts" / f"{info.id}.json").read_text(encoding="utf-8"))
    assert envelope["deck"]["schema_version"] == 3
    compact = json.dumps(envelope["deck"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert envelope["content_sha256"] == hashlib.sha256(compact).hexdigest()  # 바로잡은 뒤의 덱으로 계산한다
    # 같은 내용을 다시 보존하면 묶인다(버전 값만 다른 원문도 같은 보존본이다)
    raw["schema_version"] = 3
    assert store.save_draft("p1", deck=raw, reason="conflict", source="editor", base_etag=None).id == info.id


def test_invalid_draft_is_kept_verbatim(store):
    store.create_project("p1")
    raw = {"schema_version": 1, "meta": {"title": "x"}, "slides": [{"chapter_id": "없는 장"}]}
    info = store.save_draft("p1", deck=raw, reason="conflict", source="editor", base_etag=None)
    envelope = json.loads((store.root / "p1" / "drafts" / f"{info.id}.json").read_text(encoding="utf-8"))
    assert envelope["deck"] == raw


# -- 마지막 형식 기록이 실패한 경우 (D3c-1 리뷰 F1, F2, F5) ---------------------------------------

def _fail_after(monkeypatch, n: int = 2):
    """덱 교체 뒤의 마지막 형식 기록을 실패시킨다. 그 기록은 직전 덱의 지문을 지우는 쓰기다(먼저 쓰기와 pending 기록은
    직전 지문을 남긴다). 쓰기 횟수로 정하면 먼저 쓰기를 빼먹은 결함에서 실패 지점이 함께 밀려 결함을 놓친다."""
    original = project_format.write_manifest

    def flaky(project_dir, manifest, atomic_write):
        if manifest.prior_written_etag is None and not any(m.status == "pending" for m in manifest.migrations):
            raise OSError("디스크 오류 흉내")
        return original(project_dir, manifest, atomic_write)

    monkeypatch.setattr(project_format, "write_manifest", flaky)
    return lambda: monkeypatch.setattr(project_format, "write_manifest", original)


def _legacy_restore(store, snapshot_id):
    """0.2.0의 스냅샷 복원을 흉내 낸다: 지금 덱을 스냅샷으로 남기고 그 스냅샷으로 덮는다."""
    project = store.root / "p1"
    current = (project / "deck.json").read_bytes()
    (project / "snapshots" / "deck-29991231-235959-000000.json").write_bytes(current)
    (project / "deck.json").write_bytes((project / "snapshots" / f"{snapshot_id}.json").read_bytes())


def test_upgrade_with_failed_final_record_then_legacy_revert_is_still_marked(store, monkeypatch):
    store.create_project("p1")
    store.save_deck("p1", _deck(), snapshot=False)
    restore = _fail_after(monkeypatch, 2)  # 1: pending 기록과 함께 먼저 쓰기, 2: 마지막 기록
    store.save_deck("p1", _deck(direct_edits={"title": {"hidden": True}}), snapshot=False)
    restore()
    manifest = project_format.read_manifest(store.root / "p1")
    [record] = manifest.migrations
    assert (record.kind, record.status, manifest.format_version) == ("upgrade", "pending", 4)
    _legacy_restore(store, record.snapshot_id)
    [info] = store.list_projects()
    assert info.reverted_by_other_app is True
    kinds = {s.id: s.kind for s in store.list_snapshots("p1")}
    assert kinds["deck-29991231-235959-000000"] == "before_revert"
    assert kinds[record.snapshot_id] == "pre_migration"
    store.save_deck("p1", store.load_deck("p1"), snapshot=False)
    records = [(m.kind, m.status, m.snapshot_id) for m in project_format.read_manifest(store.root / "p1").migrations]
    assert records[0][:2] == ("upgrade", "done")
    assert records[1] == ("external_downgrade", "done", "deck-29991231-235959-000000")


def test_level_four_saves_write_the_manifest_number_first_even_if_the_final_record_fails(store, monkeypatch):
    """같은 등급 저장과 3에서 4로의 올림 모두 덱 교체 전에 manifest가 4다. 이전 빌드를 막는 장치다 (D3c-1 리뷰 F5)."""
    store.create_project("p1")
    meta = {"title": "보고", "key_message": "핵심"}
    store.save_deck("p1", Deck.model_validate({**_deck().model_dump(mode="json"), "meta": meta}), snapshot=False)
    restore = _fail_after(monkeypatch, 2)
    edited = Deck.model_validate({**_deck(direct_edits={"title": {"hidden": True}}).model_dump(mode="json"), "meta": meta})
    store.save_deck("p1", edited, snapshot=False)
    restore()
    assert project_format.read_manifest(store.root / "p1").format_version == 4
    restore = _fail_after(monkeypatch, 2)
    moved = Deck.model_validate({**_deck(direct_edits={"title": {"dx_pt": 3, "dy_pt": 0}}).model_dump(mode="json"), "meta": meta})
    store.save_deck("p1", moved, snapshot=False)
    restore()
    manifest = project_format.read_manifest(store.root / "p1")
    assert manifest.format_version == 4
    assert manifest.last_written_etag == store.deck_etag("p1")  # 먼저 쓰기가 새 덱의 지문을 남겼다


def test_writing_level_four_over_an_unreadable_deck_raises_the_manifest_first(store, monkeypatch):
    """디스크 덱을 읽지 못하는 상태에서도 번호를 먼저 올린다 (D3c-1 리뷰 F2)."""
    store.create_project("p1")
    (store.root / "p1" / "deck.json").write_text("{깨진", encoding="utf-8")
    restore = _fail_after(monkeypatch, 2)
    store.save_deck("p1", _deck(direct_edits={"title": {"hidden": True}}), snapshot=False)
    restore()
    assert project_format.read_manifest(store.root / "p1").format_version == 4
