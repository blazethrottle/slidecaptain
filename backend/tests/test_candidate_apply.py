"""장 후보 합치기 규칙 (개정판 D3c-5, 계획 4.8).

반영 단위 표가 템플릿 10종의 모든 슬롯 칸을 한 번씩 덮는지, keep_current 치환, "직접 고친 문구" 판정, 길이가 바뀐 목록의
순번 요소 수정 기본 지우기, 부분 강조와 비교 차트와 요소 수정의 정리를 지킨다. 서버 라우트의 판정과 원자성은
test_candidate_apply_api에 있다. 반영 단위 표는 고정 파일 merge-units.json으로 화면(D3c-6)과 묶는다.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from slidecaptain.models.deck import GeneratedSlots, Slide
from slidecaptain.models.expression import ChartSpec, TextSpan
from slidecaptain.pipeline.candidate_apply import (
    INDEXED_KEYS, MERGE_UNITS, default_drops, edited_units, length_changed_units, merge_slide, merge_slots, same_slide,
)
from tests.test_direct_edits import SAMPLES

UNITS_FIXTURE = Path(__file__).parent / "fixtures" / "merge-units.json"
_GENERATED = TypeAdapter(GeneratedSlots)


def slots(template: str, **values):
    return _GENERATED.validate_python({"template": template, **values})


def sample(template: str, variant: str = "full"):
    return slots(template, **SAMPLES[template][variant])


def span(slot: str, text: str, start: int = 0, end: int = 2, index: int | None = None) -> TextSpan:
    return TextSpan(slot=slot, index=index, start=start, end=end, role="bold",
                    text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


@pytest.mark.parametrize("template", sorted(MERGE_UNITS))
def test_units_cover_every_slot_field_exactly_once(template):
    """단위 표에 빠진 칸이 있으면 합치기가 그 칸을 늘 새 문구로 덮고, 겹치면 두 단위가 같은 칸을 다툰다."""
    model = type(sample(template))
    fields = [name for name in model.model_fields if name != "template"]
    covered = [name for unit_fields in MERGE_UNITS[template].values() for name in unit_fields]
    assert sorted(covered) == sorted(fields)


def test_unit_table_fixture_is_current():
    """화면(D3c-6)이 단위 이름을 보이고 고르는 표. 바뀌면 화면도 함께 고친다. 다시 쓰기: SLIDECAPTAIN_UPDATE_FIXTURES=1."""
    actual = {"units": {t: {u: list(f) for u, f in units.items()} for t, units in MERGE_UNITS.items()},
              "indexed": {f"{t}:{u}": p.pattern for (t, u), p in INDEXED_KEYS.items()}}
    text = json.dumps(actual, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("SLIDECAPTAIN_UPDATE_FIXTURES") == "1":
        UNITS_FIXTURE.write_text(text, encoding="utf-8")
    assert UNITS_FIXTURE.read_text(encoding="utf-8") == text


def test_keep_current_replaces_only_the_chosen_units():
    current = slots("bullet_box", bullets=[{"text": "지금 불릿"}], conclusion="지금 결론", footnote="지금 각주")
    candidate = slots("bullet_box", bullets=[{"text": "새 불릿"}, {"text": "둘"}], conclusion="새 결론", footnote="새 각주")
    merged = merge_slots(current, candidate, ["conclusion"])
    assert merged.conclusion == "지금 결론"
    assert [b.text for b in merged.bullets] == ["새 불릿", "둘"] and merged.footnote == "새 각주"
    assert merge_slots(current, candidate, []) is candidate


def test_table_unit_takes_columns_and_rows_together_and_callout_tone_follows_the_text():
    current = slots("table", columns=["가", "나"], rows=[["1", "2"]], footnote="지금")
    candidate = slots("table", columns=["다"], rows=[["3"], ["4"]], footnote="새")
    merged = merge_slots(current, candidate, ["table"])
    assert (merged.columns, merged.rows, merged.footnote) == (["가", "나"], [["1", "2"]], "새")
    callout = merge_slots(slots("callout", text="지금", tone="danger"), slots("callout", text="새", tone="accent1"), ["text"])
    assert (callout.text, callout.tone) == ("지금", "danger")


def test_unknown_unit_and_keeping_without_a_current_slide_are_rejected():
    candidate = sample("cards")
    with pytest.raises(ValueError, match="반영 단위"):
        merge_slots(sample("cards"), candidate, ["card0"])  # 목록 안의 항목은 단위가 아니다
    with pytest.raises(ValueError, match="지금 문구가 없어"):
        merge_slots(None, candidate, ["cards"])


def test_edited_units_compare_with_every_applied_result_since_the_last_reset():
    baseline = slots("bullet_box", bullets=[{"text": "가"}], conclusion="결론", footnote="")
    current = slots("bullet_box", bullets=[{"text": "가"}], conclusion="고친 결론", footnote="")
    assert edited_units(current, [baseline]) == ["conclusion"]
    assert edited_units(current, []) is None  # 기준 없음: 표시 없이 모두 새 문구
    assert edited_units(current, [slots("summary", conclusion="결론")]) is None  # 템플릿이 다르면 기준이 아니다
    # 어느 반영 결과와 같은 단위는 고친 문구가 아니다: 되돌리기로 이전 결과에 돌아간 단위 (β 묶음 리뷰 S2, S3)
    later = slots("bullet_box", bullets=[{"text": "나"}], conclusion="나중 결론", footnote="")
    assert edited_units(current, [later, baseline]) == ["conclusion"]
    assert edited_units(baseline, [baseline, later]) == []
    # 템플릿을 바꿨다가 돌아온 장: 중간의 다른 템플릿 반영 앞의 기록은 기준이 아니다 (β 재리뷰 T1)
    cards = slots("cards", cards=[{"heading": "카드1"}, {"heading": "카드2"}])
    assert edited_units(current, [baseline, cards]) is None
    assert edited_units(current, [later, cards, baseline]) == ["conclusion"]
    assert edited_units(baseline, [baseline, cards, later]) == ["bullets", "conclusion"]


def test_list_units_whose_length_changed_drop_their_indexed_edits_by_default():
    current = Slide(chapter_id="c1", slots=sample("cards"), direct_edits={
        "card0": {"dx_pt": 10, "dy_pt": 0}, "card3": {"hidden": True}, "title": {"font_scale": 1.2}})
    three = slots("cards", cards=[{"heading": "A"}, {"heading": "B"}, {"heading": "C"}])
    assert length_changed_units(current.slots, three) == ["cards"]
    assert default_drops(current, three) == ["card0", "card3"]  # 제목은 목록 요소가 아니라 남는다
    assert default_drops(current, sample("cards")) == []  # 길이가 같으면 남긴다
    assert default_drops(current, merge_slots(current.slots, three, ["cards"])) == []  # 지금 목록을 지키면 남긴다


def test_bullets_points_and_table_have_no_indexed_keys_but_report_the_length_change():
    current = Slide(chapter_id="c1", slots=sample("bullet_box"), direct_edits={"bullets": {"dx_pt": 5, "dy_pt": 5}})
    longer = slots("bullet_box", bullets=[{"text": "가"}, {"text": "나"}], conclusion="결론")
    assert length_changed_units(current.slots, longer) == ["bullets"]
    assert default_drops(current, longer) == []


def test_merge_keeps_edits_whose_keys_remain_and_applies_drops_and_unhides():
    current = Slide(chapter_id="c1", slots=sample("bullet_box"), direct_edits={
        "bullets": {"dx_pt": 5, "dy_pt": 5, "hidden": True}, "conclusion": {"fill": "surface2"},
        "footnote": {"text_color": "danger"}})
    candidate = slots("bullet_box", bullets=[{"text": "새"}], conclusion="새 결론")  # 각주가 없어 그 요소가 사라진다
    result = merge_slide(current, "c1", candidate, keep_current=[], drop_edits=["conclusion"], unhide=["bullets"])
    assert result.slide.direct_edits["bullets"].model_dump() == {"dx_pt": 5, "dy_pt": 5}
    assert set(result.slide.direct_edits) == {"bullets"}
    assert result.removed_edits == ["conclusion", "footnote"] and result.unhidden == ["bullets"]


def test_merge_rejects_drops_of_edits_the_slide_does_not_have():
    current = Slide(chapter_id="c1", slots=sample("bullet_box"))
    with pytest.raises(ValueError, match="없는 요소 수정"):
        merge_slide(current, "c1", sample("bullet_box"), keep_current=[], drop_edits=["title"], unhide=[])


def test_spans_survive_only_where_the_merged_text_is_unchanged():
    base = slots("bullet_box", bullets=[{"text": "첫 항목"}, {"text": "둘째"}], conclusion="지금 결론")
    current = Slide(chapter_id="c1", slots=base, eyebrow="분류 라벨", text_spans=[
        span("conclusion", "지금 결론"), span("bullets", "첫 항목", index=0), span("bullets", "둘째", index=1),
        span("eyebrow", "분류 라벨")])
    candidate = slots("bullet_box", bullets=[{"text": "첫 항목"}], conclusion="새 결론")
    result = merge_slide(current, "c1", candidate, keep_current=[], drop_edits=[], unhide=[])
    kept = {(s.slot, s.index) for s in result.slide.text_spans}
    # 결론은 바뀌었고 둘째 불릿은 사라졌다. 첫 불릿과 제목 위 분류(생성이 만들지 않음)는 그대로다
    assert kept == {("bullets", 0), ("eyebrow", None)} and result.removed_spans == 2
    kept_current = merge_slide(current, "c1", candidate, keep_current=["conclusion"], drop_edits=[], unhide=[])
    assert ("conclusion", None) in {(s.slot, s.index) for s in kept_current.slide.text_spans}


def test_chart_stays_on_a_table_unless_the_caller_drops_it():
    chart = ChartSpec(rule_version="comparison-chart-v1", comparison_id="cmp1", kind="column")
    current = Slide(chapter_id="c1", slots=sample("table"), chart=chart)
    assert merge_slide(current, "c1", sample("table"), keep_current=[], drop_edits=[], unhide=[]).slide.chart == chart
    dropped = merge_slide(current, "c1", sample("table"), keep_current=[], drop_edits=[], unhide=[], keep_chart=False)
    assert dropped.slide.chart is None and dropped.removed_chart


def test_new_slide_for_an_empty_chapter_and_the_idempotency_check():
    result = merge_slide(None, "c1", sample("summary"), keep_current=[], drop_edits=[], unhide=[])
    assert (result.slide.eyebrow, result.slide.subtitle, result.slide.direct_edits) == ("", "", {})
    assert same_slide(result.slide, merge_slide(result.slide, "c1", sample("summary"), keep_current=[], drop_edits=[],
                                                unhide=[]).slide)
    assert not same_slide(None, result.slide)
