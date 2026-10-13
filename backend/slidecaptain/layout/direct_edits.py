"""직접 수정의 렌더 적용 (개정판 D3c-2, 계획 4.4).

글자 배율은 빌더 안에서 적용한다(templates.build_slide의 font_scales). 여기서는 그 배율을 OOXML 한계로 자르고,
빌더 뒤에 위치, 글자 색, 채움 색, 숨김을 적용한다. 줄바꿈과 경고에 영향이 없는 수정만 빌더 뒤에 둔다.
"""

import math
import re

from slidecaptain.metrics.color import readable_text_color
from slidecaptain.models.direct_edit import ElementEdit
from slidecaptain.models.preset import BODY_MIN_PT, FOOTNOTE_MIN_PT, Preset
from slidecaptain.models.render import CapacityWarning, Frame, SlidePlan

# 비교 차트의 두 프레임은 표의 열쇠 `table`로 묶는다(계획 4.3)
_GROUPED = {"chart": "table", "chart_conditions": "table"}
# 원래 글자색을 채움의 휘도로 정하는 요소. 채움을 바꾸면 글자색도 다시 정한다(계획 리뷰 저장 S16).
# 강조 밴드는 슬롯의 tone이 채움을 정하므로 직접 수정의 채움을 받지 않는다
_LUMINANCE_KEYS = re.compile(r"^(card\d+|step\d+_badge|row\d+_category)$")
# 경고 slot에 붙는 접미어. 요소 열쇠에 이 접미어를 붙인 경고는 그 요소의 것이다
_WARNING_SUFFIXES = ("_heading", "_badge", "_tail", "_subtitle", "_span")
_LABEL_WARNING = re.compile(r"^(step\d+_labels)_\d+$")
# OOXML 행간 상한(ST_TextSpacingPoint, 158400 = 1584pt)과 글자 크기 하한(ST_TextFontSize, 100 = 1pt)
SPACING_MAX_PT = 1584.0
FONT_MIN_PT = 1.0


def frame_key(frame: Frame) -> str:
    name = frame.name.split(":", 1)[1]
    return _GROUPED.get(name, name)


def warning_key(slot: str, keys) -> str | None:
    """용량 경고의 slot이 가리키는 요소 열쇠. 미리보기도 같은 규칙을 쓴다(재리뷰 RR22, 고정 파일 시험)."""
    if slot in keys:
        return slot
    if slot in _GROUPED:
        return _GROUPED[slot]
    if (m := _LABEL_WARNING.match(slot)) and m.group(1) in keys:
        return m.group(1)
    for suffix in _WARNING_SUFFIXES:
        if slot.endswith(suffix) and (base := slot[: -len(suffix)]) in keys:
            return base
        if slot.endswith(suffix) and (base := slot[: -len(suffix)]) in _GROUPED:
            return _GROUPED[base]
    return None


def _sizes_by_key(page: SlidePlan) -> dict[str, list[float]]:
    sizes: dict[str, list[float]] = {}
    for frame in page.frames:
        sizes.setdefault(frame_key(frame), []).extend(p.font_pt for p in frame.paras)
    return sizes


def _text_keys(page: SlidePlan) -> set[str]:
    """글이 있는 요소. 빈 표지 부제처럼 빈 문단만 있는 요소는 글자 크기를 바꿀 것이 없다 (D3c-2 리뷰 F10).

    크기 한계는 빈 문단까지 넣어 계산한다. 라이터가 빈 문단에도 글자 크기를 기록하므로 빼면 1pt 아래로 갈 수 있다."""
    return {frame_key(frame) for frame in page.frames if any(p.text.strip() for p in frame.paras)}


def scale_limits(base_sizes: list[float], preset: Preset) -> tuple[float, float]:
    """한 요소의 글자 배율 범위. 가장 작은 문단이 1pt 아래로, 가장 큰 문단의 행간이 1,584pt 위로 가지 않는다."""
    upper_pt = math.floor(SPACING_MAX_PT / preset.spacing.line_spacing)
    return FONT_MIN_PT / min(base_sizes), upper_pt / max(base_sizes)


def clamp_scales(
    scales: dict[str, float], base: SlidePlan, preset: Preset,
) -> tuple[dict[str, float], list[CapacityWarning]]:
    """배율을 OOXML 한계로 자르고, 자른 요소와 읽기 하한 아래로 줄인 요소에 경고를 단다 (계획 리뷰 저장 S6, S7,
    재리뷰 RR18). 문단이 없거나 글이 없는 요소의 배율은 버린다."""
    sizes = _sizes_by_key(base)
    texts = _text_keys(base)
    result: dict[str, float] = {}
    warnings: list[CapacityWarning] = []
    for key, scale in scales.items():
        base_sizes = sizes.get(key)
        if not base_sizes or key not in texts:
            continue
        low, high = scale_limits(base_sizes, preset)
        clamped = min(max(scale, low), high)
        result[key] = clamped
        largest = max(base_sizes)
        if clamped != scale:
            # 하한은 가장 작은 문단, 상한은 가장 큰 문단에 걸린다. 걸린 쪽의 크기를 말한다 (D3c-2 리뷰 F11)
            smallest = min(base_sizes)
            message, needed, available = (
                (f"가장 작은 글자를 {FONT_MIN_PT:g}pt로 맞췄습니다. PowerPoint가 받는 가장 작은 크기보다 작았습니다",
                 round(smallest * scale, 2), round(smallest * clamped, 2))
                if clamped == low else
                (f"가장 큰 글자를 {round(largest * clamped, 2):g}pt로 맞췄습니다. PowerPoint가 받는 범위를 넘었습니다",
                 round(largest * scale, 2), round(largest * clamped, 2)))
            warnings.append(CapacityWarning(chapter_id=base.chapter_id, slot=key, kind="font_size", message=message,
                                            needed_pt=needed, available_pt=available))
        below = [(b, round(b * clamped, 2)) for b in base_sizes]
        if any((b >= BODY_MIN_PT and s < BODY_MIN_PT) or (b >= FOOTNOTE_MIN_PT and s < FOOTNOTE_MIN_PT) for b, s in below):
            floor = BODY_MIN_PT if any(b >= BODY_MIN_PT and s < BODY_MIN_PT for b, s in below) else FOOTNOTE_MIN_PT
            warnings.append(CapacityWarning(
                chapter_id=base.chapter_id, slot=key, kind="font_size",
                message=f"읽기 하한({floor:g}pt) 아래로 줄였습니다. 인쇄나 화면에서 읽기 어려울 수 있습니다",
                needed_pt=floor, available_pt=min(s for _, s in below),
            ))
    return result, warnings


def _groups(page: SlidePlan) -> dict[str, list[Frame]]:
    groups: dict[str, list[Frame]] = {}
    for frame in page.frames:
        groups.setdefault(frame_key(frame), []).append(frame)
    return groups


def apply_layout_edits(page: SlidePlan, edits: dict[str, ElementEdit], preset: Preset) -> None:
    """위치, 글자 색, 채움 색, 숨김을 적용한다. 수정값이 있는 프레임에 엔진의 자리(base_x, base_y)를 남긴다."""
    colors = preset.colors
    groups = _groups(page)
    for key, edit in edits.items():
        frames = groups.get(key)
        if not frames:
            continue
        for frame in frames:
            frame.base_x, frame.base_y = frame.x, frame.y
        if edit.dx_pt is not None:
            # 묶음은 한 번에 자른다. 따로 자르면 차트와 조건 문구가 어긋난다 (재리뷰 RR20)
            x0, y0 = min(f.x for f in frames), min(f.y for f in frames)
            width = max(f.x + f.w for f in frames) - x0
            height = max(f.y + f.h for f in frames) - y0
            dx = min(max(x0 + edit.dx_pt, 0.0), preset.page_width_pt - width) - x0
            dy = min(max(y0 + edit.dy_pt, 0.0), preset.page_height_pt - height) - y0
            for frame in frames:
                frame.x, frame.y = frame.x + dx, frame.y + dy
        if edit.text_color is not None:
            color = getattr(colors, edit.text_color)
            for frame in frames:
                for para in frame.paras:
                    para.color = color
        if edit.fill is not None:
            fill = getattr(colors, edit.fill)
            for frame in frames:
                if frame.fill is None:
                    continue
                frame.fill = fill
                if edit.text_color is None and _LUMINANCE_KEYS.match(key):
                    text_color = readable_text_color(fill, light=colors.background, dark=colors.text)
                    for para in frame.paras:
                        para.color = text_color
        if edit.hidden:
            for frame in frames:
                frame.hidden = True


def drop_hidden_warnings(page: SlidePlan, edits: dict[str, ElementEdit], keys) -> None:
    hidden = {key for key, edit in edits.items() if edit.hidden}
    if hidden:
        page.warnings = [w for w in page.warnings if warning_key(w.slot, keys) not in hidden]


def font_limit(chapter, slide, preset: Preset, metrics, presenter: str, key: str) -> dict | None:
    """고른 요소가 경고 없이 받는 최대 글자 크기 (D3c-2, 재리뷰 RR2). 화면이 글자 크기 칸 옆에 보인다.

    크기 조절이 없으므로 상자 높이는 그대로다. 그 요소에 붙는 용량 경고가 없는 가장 큰 배율을 엔진과 같은 판정식(빌더와
    부분 강조)으로 찾는다(이분 탐색). 다른 요소의 배율은 지금 값을 둔다. 문단이 없는 요소는 None이다.
    """
    from slidecaptain.layout.expression import apply_text_spans
    from slidecaptain.layout.templates import build_slide
    from slidecaptain.models.direct_edit import frame_keys

    def build(scales):
        return build_slide(chapter, slide.slots, 1, preset, metrics, presenter=presenter,
                           eyebrow=slide.eyebrow, subtitle=slide.subtitle, font_scales=scales)

    base = build(None)
    sizes = _sizes_by_key(base).get(key)
    if not sizes or key not in _text_keys(base):
        return None
    keys = frame_keys(slide)
    others = {k: e.font_scale for k, e in slide.direct_edits.items() if e.font_scale is not None and k != key}
    low, high = scale_limits(sizes, preset)

    def fits(scale: float) -> bool:
        page = build({**others, key: scale})
        if slide.text_spans:
            # 엔진처럼 부분 강조까지 적용한 뒤 본다. 굵은 글자의 실제 폭으로 다시 끊으면 넘칠 수 있다 (D3c-2 리뷰 F4).
            # 강조를 적용할 수 없는 덱은 엔진의 렌더도 실패하므로 여기서는 빌더 경고만 본다
            try:
                apply_text_spans(slide, page, preset, metrics)
            except ValueError:
                pass
        return not any(warning_key(w.slot, keys) == key for w in page.warnings)

    edit = slide.direct_edits.get(key)
    current = min(max(edit.font_scale if edit and edit.font_scale else 1.0, low), high)
    largest = max(sizes)
    best: float | None = None
    if fits(low):
        if fits(high):
            best = high
        else:
            ok, bad = low, high
            for _ in range(24):  # 배율 범위를 2^24로 나누면 1/100pt보다 촘촘하다
                mid = (ok + bad) / 2
                ok, bad = (mid, bad) if fits(mid) else (ok, mid)
            best = ok
    return {
        "base_pt": largest,
        "current_pt": round(largest * current, 2),
        "fits_up_to_pt": None if best is None else math.floor(largest * best * 100) / 100,
        "min_pt": round(largest * low, 2),
        "max_pt": round(largest * high, 2),
    }
