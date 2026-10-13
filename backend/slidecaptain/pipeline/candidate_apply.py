"""장 후보를 현재 슬라이드에 합치는 규칙 (개정판 D3c-5, 계획 4.8).

AI가 만든 장 후보(장 생성, 장 축약, 묶음 하위 행의 결과 슬롯)를 지금 슬라이드에 합친다. 사용자는 반영 단위마다
"지금 문구"와 "새 문구"를 고르고, 위치, 글자 크기, 색, 숨김 같은 직접 수정은 새 내용에 같은 열쇠의 요소가 있으면 남는다.
이 모듈은 덱이나 원장을 읽지 않는 순수 함수만 둔다. 판정, 원자성, 상태 코드는 서버(server/app.py)가 맡는다.

반영 단위: 문구 칸 하나가 한 단위이고, 목록은 목록 전체가 한 단위다. 표는 열과 행을 함께 한 단위로 본다. 목록 안의 항목마다
고르게 하지 않는 이유는 후보의 목록 길이와 순서가 다를 때 항목 순번이 다른 내용을 가리키기 때문이다(계획 리뷰 서버 S10).
"""

import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from pydantic import TypeAdapter

from slidecaptain.models.deck import GeneratedSlots, Slide, Slots
from slidecaptain.models.expression import span_text

# 템플릿마다 반영 단위와 그 단위가 담는 슬롯 칸 (계획 4.8의 merge_fields). 색 역할(tone), 항목 단계(level), 강조 여부
# (emphasis)는 그 칸이 든 단위를 따라간다. 표지의 보고자는 메타에서 오므로 단위가 아니다
MERGE_UNITS: dict[str, dict[str, tuple[str, ...]]] = {
    "cover": {"title": ("title",), "subtitle": ("subtitle",), "date": ("date",)},
    "summary": {"conclusion": ("conclusion",), "points": ("points",)},
    "bullet_box": {"bullets": ("bullets",), "conclusion": ("conclusion",), "footnote": ("footnote",)},
    "table": {"table": ("columns", "rows"), "footnote": ("footnote",)},
    "compare2": {"left": ("left",), "right": ("right",), "conclusion": ("conclusion",)},
    "divider": {"section_no": ("section_no",), "section_title": ("section_title",)},
    "callout": {"text": ("text", "tone")},
    "cards": {"cards": ("cards",)},
    "process": {"steps": ("steps",)},
    "matrix": {"rows": ("rows",)},
}

# 목록 단위의 항목마다 생기는 요소 열쇠. 목록 길이가 바뀌면 같은 순번이 다른 항목을 가리키므로 이 열쇠의 수정은 기본으로
# 지운다(계획 4.8 비교 화면). 불릿, 요점, 표는 상자 하나가 요소 하나라 순번 열쇠가 없다
INDEXED_KEYS: dict[tuple[str, str], re.Pattern] = {
    ("cards", "cards"): re.compile(r"card\d+"),
    ("process", "steps"): re.compile(r"step\d+(?:_badge|_labels)?"),
    ("matrix", "rows"): re.compile(r"row\d+_(?:category|primary|items)"),
}

_SLOTS = TypeAdapter(Slots)


def merge_fields(template: str) -> dict[str, tuple[str, ...]]:
    """템플릿의 반영 단위. 도식과 모르는 템플릿은 빈 사전이다(도식은 이 경로의 대상이 아니다)."""
    return MERGE_UNITS.get(template, {})


def _dump(slots) -> dict:
    return slots.model_dump(mode="json")


def _unit_value(dumped: dict, fields: tuple[str, ...]) -> list:
    return [dumped.get(name) for name in fields]


def _list_length(dumped: dict, fields: tuple[str, ...]) -> tuple | None:
    """목록 단위의 길이. 표는 열 수와 행 수를 함께 본다. 목록이 아니면 None."""
    lengths = tuple(len(dumped[name]) for name in fields if isinstance(dumped.get(name), list))
    return lengths or None


def edited_units(current: Slots, baselines: list[Slots]) -> list[str] | None:
    """"직접 고친 문구" 표시: 그 장의 마지막 기준 무효화 뒤에 반영된 AI 결과(baselines) 어느 것과도 지금 슬롯이 다른 단위.
    반영 뒤 되돌리기로 이전 AI 결과에 돌아간 단위와 반영 때 지금 문구로 남긴 이전 AI 문구는 고친 문구가 아니다(β 묶음 리뷰
    S2, S3). 같은 템플릿의 기준이 없으면 None(화면은 표시 없이 모두 "새 문구"로 두고 그 사실을 적는다, 계획 4.1)."""
    bases = [_dump(b) for b in baselines if b.template == current.template]
    if not bases:
        return None
    now = _dump(current)
    return [unit for unit, fields in merge_fields(current.template).items()
            if all(_unit_value(now, fields) != _unit_value(base, fields) for base in bases)]


def merge_slots(current: Slots | None, candidate: Slots, keep_current: list[str]) -> Slots:
    """후보 슬롯에서 keep_current의 단위만 지금 슬롯 값으로 바꾼다. 모르는 단위는 ValueError."""
    units = merge_fields(candidate.template)
    unknown = [u for u in keep_current if u not in units]
    if unknown:
        raise ValueError(f"이 템플릿에 없는 반영 단위입니다: {', '.join(unknown)}")
    if not keep_current:
        return candidate
    if current is None or current.template != candidate.template:
        raise ValueError("지금 문구가 없어 지금 문구로 둘 단위를 고를 수 없습니다")
    merged, now = _dump(candidate), _dump(current)
    for unit in keep_current:
        for name in units[unit]:
            merged[name] = now[name]
    return _SLOTS.validate_python(merged)


def length_changed_units(current: Slots | None, merged: Slots) -> list[str]:
    """지금과 합친 결과의 목록 길이가 다른 단위. 비교 화면의 "새 내용의 항목 수와 순서가 다릅니다" 안내와 기본 지우기에 쓴다."""
    if current is None or current.template != merged.template:
        return []
    now, after = _dump(current), _dump(merged)
    return [unit for unit, fields in merge_fields(merged.template).items()
            if _list_length(now, fields) is not None and _list_length(now, fields) != _list_length(after, fields)]


def default_drops(current: Slide | None, merged: Slots) -> list[str]:
    """기본으로 지울 요소 수정: 길이가 바뀐 목록의 순번 요소 수정이다. 그 요소의 숨김도 함께 풀린다(계획 4.8, 리뷰 서버 S11)."""
    if current is None or not current.direct_edits:
        return []
    patterns = [INDEXED_KEYS[(merged.template, unit)] for unit in length_changed_units(current.slots, merged)
                if (merged.template, unit) in INDEXED_KEYS]
    return [key for key in current.direct_edits if any(p.fullmatch(key) for p in patterns)]


def _span_text_or_none(holder, span) -> str | None:
    try:
        return span_text(holder, span)
    except (ValueError, TypeError, IndexError):
        return None


@dataclass
class MergeResult:
    slide: Slide
    keep_current: list[str]
    drop_edits: list[str]
    unhide: list[str]
    removed_edits: list[str] = field(default_factory=list)  # 수정이 모두 사라지는 요소
    unhidden: list[str] = field(default_factory=list)  # 숨김이 풀리는 요소
    removed_spans: int = 0
    removed_chart: bool = False


def merge_slide(current: Slide | None, chapter_id: str, candidate: GeneratedSlots, *, keep_current: list[str],
                drop_edits: list[str], unhide: list[str], keep_chart: bool = True) -> MergeResult:
    """후보를 지금 슬라이드에 합친다. 제목 위 분류와 제목 아래 한 문장은 생성이 만들지 않으므로 지금 값을 둔다.

    - 부분 강조는 합친 슬롯에서 문구가 그대로인 것만 남긴다(화면 pruneChangedSpans와 같은 규칙). Slide 검증이 해시가 다른
      강조를 예외로 거절하므로 Slide를 만들기 전에 거른다.
    - 비교 차트는 결과가 표이고 keep_chart일 때만 남긴다. 덱 수준의 비교 조건은 부르는 쪽이 덱 검증으로 본다.
    - 요소 수정은 drop_edits를 지우고 unhide의 숨김을 푼다. 합친 슬롯의 요소 열쇠에 없는 수정은 Slide 검증이 지운다.
    """
    merged_slots = merge_slots(current.slots if current else None, candidate, keep_current)
    edits = dict(current.direct_edits) if current else {}
    unknown = [k for k in [*drop_edits, *unhide] if k not in edits]
    if unknown:
        raise ValueError(f"지금 슬라이드에 없는 요소 수정입니다: {', '.join(sorted(set(unknown)))}")
    for key in drop_edits:
        edits.pop(key, None)
    for key in unhide:
        if key in edits:
            edits[key] = edits[key].model_copy(update={"hidden": None})
    eyebrow, subtitle = (current.eyebrow, current.subtitle) if current else ("", "")
    holder = SimpleNamespace(eyebrow=eyebrow, subtitle=subtitle, slots=merged_slots)
    spans = [s for s in (current.text_spans if current else [])
             if _span_text_or_none(current, s) is not None
             and _span_text_or_none(current, s) == _span_text_or_none(holder, s)]
    chart = current.chart if current and keep_chart and merged_slots.template == "table" else None
    slide = Slide.model_validate({
        "chapter_id": chapter_id, "eyebrow": eyebrow, "subtitle": subtitle, "slots": merged_slots.model_dump(mode="json"),
        "chart": chart.model_dump(mode="json") if chart else None,
        "text_spans": [s.model_dump(mode="json") for s in spans],
        "direct_edits": {k: v.model_dump(mode="json") for k, v in edits.items()}})
    before = current.direct_edits if current else {}
    after = slide.direct_edits
    return MergeResult(
        slide=slide, keep_current=list(keep_current), drop_edits=list(drop_edits), unhide=list(unhide),
        removed_edits=sorted(k for k in before if k not in after),
        unhidden=sorted(k for k in before if before[k].hidden and not (k in after and after[k].hidden)),
        removed_spans=len(current.text_spans) - len(spans) if current else 0,
        removed_chart=bool(current and current.chart is not None and slide.chart is None))


def same_slide(a: Slide | None, b: Slide) -> bool:
    """지금 슬라이드가 합친 결과와 같은가. 같으면 덱을 다시 쓰지 않고 처분만 정리한다(계획 4.8, 재리뷰 RR8)."""
    return a is not None and a.model_dump(mode="json") == b.model_dump(mode="json")


__all__ = ["MERGE_UNITS", "INDEXED_KEYS", "MergeResult", "merge_fields", "edited_units", "merge_slots",
           "length_changed_units", "default_drops", "merge_slide", "same_slide"]
