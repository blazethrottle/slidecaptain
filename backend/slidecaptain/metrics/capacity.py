"""용량 계약 (설계서 5.1): 프리셋이 확정한 규격에서 슬롯별 최대 분량을 역산한다.

이 한도는 AI 생성의 계약 조건으로 걸리고(단계 3), 편집 중 분량 검증에도 쓰인다.
`face` 인자는 `width_pt(text, font_pt)`를 가진 폭 데이터 한 벌이다 (FaceMetrics).

계약은 실측(5.2)과 같은 규칙으로 계산한다 (2026-09-02 Critical 묶음 태스크 A): 실측이 더하는 항목 간격과
셀 여백, 카드 안쪽 여백을 계약도 똑같이 뺀다. 종전에는 계약이 행간 높이로만 나눠 실측보다 22~35% 많이
약속했고, AI 가 계약을 지켜도 분량 게이트가 초과 경고를 냈다. 기하 수식의 진본은 이 모듈 한 곳이며,
레이아웃 엔진(layout/templates.py)도 같은 함수를 호출한다.
"""

import math

from pydantic import BaseModel

from slidecaptain.metrics.line_breaker import break_paragraph
from slidecaptain.models.deck import Bullet
from slidecaptain.models.preset import Preset, Spacing, content_box


def line_height_pt(font_pt: float, line_spacing: float) -> float:
    return font_pt * line_spacing


def max_lines(area_height_pt: float, font_pt: float, line_spacing: float) -> int:
    return max(0, math.floor(area_height_pt / line_height_pt(font_pt, line_spacing)))


def items_that_fit(area_height_pt: float, font_pt: float, line_spacing: float, gap_pt: float) -> int:
    """한 줄짜리 항목이 전부일 때 영역에 들어가는 최대 항목 수 (항목 사이 간격 포함).

    여러 줄짜리 항목이 섞이면 간격이 줄어 여유가 생기므로, 이 값은 계약의 안전한 하한이다.
    """
    lh = line_height_pt(font_pt, line_spacing)
    return max(0, math.floor((area_height_pt + gap_pt) / (lh + gap_pt)))


def rows_that_fit(area_height_pt: float, font_pt: float, line_spacing: float, pad_y_pt: float) -> int:
    """한 줄짜리 표 행이 전부일 때 들어가는 최대 행 수 (행마다 위아래 셀 여백 포함)."""
    lh = line_height_pt(font_pt, line_spacing)
    return max(0, math.floor(area_height_pt / (lh + 2 * pad_y_pt)))


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
    """레이아웃 엔진(Task 6)과 공유하는 파생 좌표. 수식의 진본은 `models/preset.py`의 `content_box`다

    (2026-09-04 태스크 A3: Preset의 안전 검증이 같은 산식으로 내용 높이를 확인해야 둘이 어긋나지 않는다).
    """
    return content_box(preset)


def common_slot_offset(preset: Preset, eyebrow: str = "", subtitle: str = "") -> float:
    """공통 슬롯이 본문 상단을 밀어내는 양 (2026-09-07 DA-4 재작업).

    이 계산의 진본은 여기 하나다. 레이아웃(`slide_geometry`)과 계약(`capacity_contract`,
    `card_geometry`, `hangul_chars_per_line`)이 같은 값을 써야 한다. 종전에는 레이아웃만 알고
    계약은 몰라서, compare2 카드가 내려간 위치에서 옛 높이로 그려져 결론 상자를 36pt 침범했다.
    """

    s, r = preset.spacing, preset.font_roles
    offset = 0.0
    if eyebrow:
        offset += r.eyebrow_pt * s.line_spacing + s.eyebrow_gap
    if subtitle:
        offset += r.subtitle_pt * s.line_spacing + s.subtitle_gap
    return offset


def content_geometry(preset: Preset, eyebrow: str = "", subtitle: str = "") -> dict[str, float]:
    """공통 슬롯을 반영한 내용 영역. `_content_geometry` 를 직접 부르는 곳은 이 함수뿐이어야 한다."""

    g = dict(_content_geometry(preset))
    g["content_top"] = g["content_top"] + common_slot_offset(preset, eyebrow, subtitle)
    return g


def card_geometry(preset: Preset, eyebrow: str = "", subtitle: str = "") -> dict[str, float]:
    """compare2 카드 기하. 계약과 레이아웃 엔진이 함께 쓴다 (2026-09-02: 종전에는 두 모듈이 다른 값을 계산했다).

    bullets_h 는 카드 소제목 영역과 그 아래 간격, 카드 안쪽 여백(위아래)을 뺀 불릿 가용 높이다.
    """
    s = preset.spacing
    g = content_geometry(preset, eyebrow, subtitle)
    card_h = g["content_bottom"] - g["content_top"] - s.box_height - s.box_gap
    card_w = (g["content_width"] - s.card_gap) / 2
    inner_w = card_w - 2 * s.box_padding
    bullets_h = card_h - s.card_heading_height - s.card_heading_gap - 2 * s.box_padding
    return {"card_w": card_w, "card_h": card_h, "inner_w": inner_w, "bullets_h": bullets_h}


def callout_geometry(preset: Preset, eyebrow: str = "", subtitle: str = "") -> dict[str, float]:
    """강조 밴드(callout) 기하. 계약과 레이아웃 엔진이 함께 쓴다 (2026-09-07 DB-1).

    밴드는 고정 높이이고 본문 영역 안에서 세로 가운데에 둔다: 전폭이지만 내용은 1~3줄이라
    본문 전체를 채우면 시각적으로 헐렁해진다(벤치마크 원형 2: "전폭 둥근 사각형 ... 안에 한 문장").
    """
    s = preset.spacing
    g = content_geometry(preset, eyebrow, subtitle)
    band_h = s.callout_height
    band_y = g["content_top"] + (g["content_bottom"] - g["content_top"] - band_h) / 2
    return {
        "band_y": band_y,
        "band_h": band_h,
        "inner_w": g["content_width"] - 2 * s.box_padding,
        "inner_h": band_h - 2 * s.box_padding,
    }


def cards_geometry(
    preset: Preset, card_count: int = 2, eyebrow: str = "", subtitle: str = ""
) -> dict[str, float]:
    """cards 템플릿 카드 기하 (2026-09-07 DB-2). compare2의 card_geometry와 달리 결론
    상자가 없어 카드 높이가 본문 영역 전체다: 카드 수가 늘어도 높이는 바뀌지 않고 폭만
    좁아진다. bullets_h는 배지와 꼬리 라벨이 항상 있다고 가정한 안전한 하한이다(계약 용도):
    실제 렌더(layout.templates._build_cards)는 카드마다 실제로 있는 만큼만 뺀다.
    """
    s = preset.spacing
    g = content_geometry(preset, eyebrow, subtitle)
    card_h = g["content_bottom"] - g["content_top"]
    card_w = (g["content_width"] - s.card_gap * (card_count - 1)) / card_count
    inner_w = card_w - 2 * s.box_padding
    reserved = (
        s.card_heading_height + s.card_heading_gap
        + s.card_badge_height + s.card_badge_gap
        + s.card_tail_height + s.card_tail_gap
    )
    bullets_h = card_h - 2 * s.box_padding - reserved
    return {"card_w": card_w, "card_h": card_h, "inner_w": inner_w, "bullets_h": bullets_h}


def process_geometry(
    preset: Preset, step_count: int = 3, eyebrow: str = "", subtitle: str = ""
) -> dict[str, float]:
    """process 템플릿의 행 기하 (2026-09-07 DB-3). cards가 카드 수에 따라 폭을 좁히는 것과 같은
    원리를 세로 축에 적용한다: cards는 카드가 가로로 늘어서 폭이 좁아지지만, process는 단계가
    세로로 쌓이므로 단계가 늘수록 행 "높이"(row_h)가 낮아진다. badge_x/text_x/text_w/label_x/
    label_w는 가로 좌표라 단계 수와 무관하다(cards의 card_w가 카드 수에 따라 변하는 것과 대비된다).

    subtitle_h는 그 행에서 부제에 남는 세로 여유다: 제목(process_heading_height)과 그 아래
    간격을 뺀 나머지이므로, 행이 낮아지면(단계가 늘면) 함께 줄어든다.
    """
    s = preset.spacing
    g = content_geometry(preset, eyebrow, subtitle)
    row_h = (g["content_bottom"] - g["content_top"] - s.process_row_gap * (step_count - 1)) / step_count
    text_x = s.margin_left + s.process_badge_size + s.process_badge_gap
    label_x = s.margin_left + g["content_width"] - s.process_label_width
    text_w = label_x - s.process_label_gap - text_x
    subtitle_h = row_h - s.process_heading_height - s.process_subtitle_gap
    return {
        "content_top": g["content_top"],
        "row_h": row_h,
        "row_gap": s.process_row_gap,
        "badge_x": s.margin_left,
        "text_x": text_x,
        "text_w": text_w,
        "label_x": label_x,
        "label_w": s.process_label_width,
        "subtitle_h": subtitle_h,
    }


def matrix_geometry(
    preset: Preset, row_count: int = 3, eyebrow: str = "", subtitle: str = ""
) -> dict[str, float]:
    """matrix 템플릿의 행 기하 (2026-09-07 DB-4). process_geometry와 같은 세로 원리(행이 늘수록
    행 높이가 줄어든다)를 쓰되, 가로 3칸(분류/대표/나열)의 폭 배분이 다르다: 분류 셀과 나열은
    고정 폭 좌우 블록이고, 대표 항목이 그 사이 남는 폭을 쓴다(process의 text_w가 badge_x와
    label_x 사이 나머지를 쓰는 것과 같은 산식).
    """
    s = preset.spacing
    g = content_geometry(preset, eyebrow, subtitle)
    row_h = (g["content_bottom"] - g["content_top"] - s.matrix_row_gap * (row_count - 1)) / row_count
    category_x = s.margin_left
    primary_x = category_x + s.matrix_category_width + s.matrix_category_gap
    items_x = s.margin_left + g["content_width"] - s.matrix_items_width
    primary_w = items_x - s.matrix_items_gap - primary_x
    return {
        "content_top": g["content_top"],
        "row_h": row_h,
        "row_gap": s.matrix_row_gap,
        "category_x": category_x,
        "primary_x": primary_x,
        "primary_w": primary_w,
        "items_x": items_x,
        "items_w": s.matrix_items_width,
    }


def cover_geometry(preset: Preset) -> dict:
    """표지 프레임 기하 (x, w 와 칸별 (y, h)). y 리터럴의 프리셋 승격은 단계 5B 이월 항목이라 값은 그대로 둔다."""
    s = preset.spacing
    return {
        "x": s.margin_left + s.cover_indent,
        "w": preset.page_width_pt - 2 * (s.margin_left + s.cover_indent),
        "fields": {
            "cover_title": (200.0, 48.0),
            "subtitle": (260.0, 24.0),
            "date": (430.0, 18.0),
            "presenter": (452.0, 18.0),
        },
    }


def divider_geometry(preset: Preset) -> dict:
    """간지 프레임 기하 (표지와 같은 형식)."""
    s = preset.spacing
    return {
        "x": s.margin_left + s.cover_indent,
        "w": preset.page_width_pt - 2 * (s.margin_left + s.cover_indent),
        "fields": {
            "section_no": (218.0, 20.0),
            "section_title": (246.0, 44.0),
        },
    }


def capacity_contract(
    template: str, preset: Preset, eyebrow: str = "", subtitle: str = "",
    card_count: int = 2, step_count: int = 3, row_count: int = 3,
) -> dict[str, int]:
    s = preset.spacing
    r = preset.font_roles
    g = content_geometry(preset, eyebrow, subtitle)
    content_h = g["content_bottom"] - g["content_top"]
    box_inner_h = s.box_height - 2 * s.box_padding
    ls = s.line_spacing
    cover = cover_geometry(preset)["fields"]
    divider = divider_geometry(preset)["fields"]
    card = card_geometry(preset, eyebrow, subtitle)
    callout = callout_geometry(preset, eyebrow, subtitle)
    # card_count는 cards 템플릿에만 쓰인다. 기본값 2는 기존 7종 호출(card_count 인자를 주지
    # 않는 모든 호출부)의 결과를 그대로 유지한다 (2026-09-07 DB-2)
    cards = cards_geometry(preset, card_count, eyebrow, subtitle)
    # step_count는 process 템플릿에만 쓰인다. 기본값 3은 이 인자를 주지 않는 기존 호출부의
    # 결과를 그대로 유지한다 (2026-09-07 DB-3, card_count와 같은 이유)
    process = process_geometry(preset, step_count, eyebrow, subtitle)
    # row_count는 matrix 템플릿에만 쓰인다. 기본값 3은 이 인자를 주지 않는 기존 호출부의
    # 결과를 그대로 유지한다 (2026-09-07 DB-4, card_count/step_count와 같은 이유)
    matrix = matrix_geometry(preset, row_count, eyebrow, subtitle)
    matrix_category_inner_h = matrix["row_h"] - 2 * s.box_padding

    contracts: dict[str, dict[str, int]] = {
        "cover": {
            "cover_title_max_lines": max_lines(cover["cover_title"][1], r.cover_title_pt, ls),
            "subtitle_max_lines": max_lines(cover["subtitle"][1], r.subtitle_pt, ls),
            "date_max_lines": max_lines(cover["date"][1], r.body_pt, ls),
        },
        "divider": {
            "section_no_max_lines": max_lines(divider["section_no"][1], r.subtitle_pt, ls),
            "section_title_max_lines": max_lines(divider["section_title"][1], r.section_title_pt, ls),
        },
        "summary": {
            "points_max_lines": items_that_fit(
                content_h - s.box_height - s.summary_box_gap, r.body_pt, ls, s.bullet_gap
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, ls),
        },
        "bullet_box": {
            "bullets_max_lines": items_that_fit(
                content_h - s.box_height - s.box_gap, r.body_pt, ls, s.bullet_gap
            ),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, ls),
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, ls),
        },
        "table": {
            # 한 줄짜리 행 기준 상한 (머리글 포함). 행 높이 = 행간 + 위아래 셀 여백
            "rows_max_single_line": rows_that_fit(content_h, r.table_pt, ls, s.table_cell_pad_y),
            "footnote_max_lines": max_lines(s.footnote_height, r.footnote_pt, ls),
        },
        "compare2": {
            "card_heading_max_lines": max_lines(s.card_heading_height, r.body_pt, ls),
            "card_bullets_max_lines": items_that_fit(card["bullets_h"], r.body_pt, ls, s.bullet_gap),
            "conclusion_max_lines": max_lines(box_inner_h, r.box_pt, ls),
        },
        "callout": {
            "text_max_lines": max_lines(callout["inner_h"], r.box_pt, ls),
        },
        "cards": {
            "card_badge_max_lines": max_lines(s.card_badge_height, r.footnote_pt, ls),
            "card_heading_max_lines": max_lines(s.card_heading_height, r.body_pt, ls),
            "card_bullets_max_lines": items_that_fit(cards["bullets_h"], r.body_pt, ls, s.bullet_gap),
            "card_tail_max_lines": max_lines(s.card_tail_height, r.footnote_pt, ls),
        },
        "process": {
            "step_heading_max_lines": max_lines(s.process_heading_height, r.body_pt, ls),
            "step_subtitle_max_lines": max_lines(process["subtitle_h"], r.subtitle_pt, ls),
            "step_label_max_lines": max_lines(s.process_label_height, r.footnote_pt, ls),
        },
        "matrix": {
            "row_category_max_lines": max_lines(matrix_category_inner_h, r.body_pt, ls),
            "row_primary_max_lines": max_lines(matrix["row_h"], r.body_pt, ls),
            "row_items_max_lines": items_that_fit(matrix["row_h"], r.body_pt, ls, s.bullet_gap),
        },
    }
    return contracts[template]


def hangul_chars_for_width(width_pt: float, font_pt: float, face, safety_ratio: float) -> int:
    """주어진 폭의 한 줄에 한글이 약 몇 자 들어가는지 어림한다."""
    return max(0, math.floor(width_pt * safety_ratio / face.width_pt("가", font_pt)))


def hangul_chars_per_line(preset: Preset, face) -> int:
    """본문 불릿 한 줄에 한글이 약 몇 자 들어가는지 어림한다 (AI 프롬프트의 분량 환산 안내용).

    불릿 들여쓰기(level 0)를 뺀 폭 기준이다 (2026-09-02: 종전에는 들여쓰기를 빼지 않아 안내대로 쓴 한 어절이 두 줄로 꺾였다).
    """
    g = content_geometry(preset)  # 폭은 세로 슬롯에 영향받지 않지만 진입점을 하나로 둔다
    width = g["content_width"] - preset.spacing.bullet_indent
    return hangul_chars_for_width(width, preset.font_roles.body_pt, face, preset.spacing.safety_ratio)


def char_hints(
    template: str, preset: Preset, metrics, card_count: int = 2, step_count: int = 3, row_count: int = 3
) -> dict[str, int]:
    """템플릿별 환산 안내 (칸 이름 → 한 줄 한글 글자 수). 프롬프트 계약 블록이 그대로 이어 붙인다.

    card_count는 cards 템플릿에만 쓰인다: 카드 폭이 카드 수에 따라 달라지므로 한 줄 글자
    수도 함께 달라진다. 기본값 2는 이 인자를 주지 않는 기존 7종 호출의 결과를 그대로 유지한다.

    step_count는 process 템플릿에만 쓰인다(2026-09-07 DB-3). cards와 달리 단계는 세로로
    쌓이므로 배지/제목/라벨 칸의 가로 너비는 단계 수와 무관하다: 이 함수의 결과값은
    step_count가 몇이든 항상 같다(그래도 시그니처를 맞춰 둔다: capacity_contract와 같은
    이유로, 나중에 가로 배치가 바뀌어도 호출부를 다시 고칠 필요가 없다).

    row_count는 matrix 템플릿에만 쓰인다(2026-09-07 DB-4). process의 step_count와 정확히
    같은 이유로 이 함수의 결과값은 row_count가 몇이든 항상 같다: 행은 세로로 쌓이므로
    분류/대표/나열 세 칸의 가로 너비는 행 수와 무관하다.
    """
    s, r = preset.spacing, preset.font_roles
    regular, bold = metrics.face(False), metrics.face(True)
    if template in ("bullet_box", "summary", "table"):
        return {"본문 한 줄": hangul_chars_per_line(preset, regular)}
    if template == "compare2":
        card = card_geometry(preset)
        return {
            "카드 안 한 줄": hangul_chars_for_width(
                card["inner_w"] - s.bullet_indent, r.body_pt, regular, s.safety_ratio
            ),
            "카드 소제목": hangul_chars_for_width(card["inner_w"], r.body_pt, bold, s.safety_ratio),
        }
    if template == "cover":
        w = cover_geometry(preset)["w"]
        return {
            "표지 제목": hangul_chars_for_width(w, r.cover_title_pt, bold, s.safety_ratio),
            "부제": hangul_chars_for_width(w, r.subtitle_pt, regular, s.safety_ratio),
        }
    if template == "divider":
        w = divider_geometry(preset)["w"]
        return {"섹션 제목": hangul_chars_for_width(w, r.section_title_pt, bold, s.safety_ratio)}
    if template == "callout":
        band = callout_geometry(preset)
        return {"밴드 안 한 줄": hangul_chars_for_width(band["inner_w"], r.box_pt, bold, s.safety_ratio)}
    if template == "cards":
        cg = cards_geometry(preset, card_count)
        return {
            "카드 배지": hangul_chars_for_width(cg["inner_w"], r.footnote_pt, bold, s.safety_ratio),
            "카드 소제목": hangul_chars_for_width(cg["inner_w"], r.body_pt, bold, s.safety_ratio),
            "카드 안 한 줄": hangul_chars_for_width(
                cg["inner_w"] - s.bullet_indent, r.body_pt, regular, s.safety_ratio
            ),
            "카드 꼬리 라벨": hangul_chars_for_width(cg["inner_w"], r.footnote_pt, regular, s.safety_ratio),
        }
    if template == "process":
        pg = process_geometry(preset, step_count)
        return {
            "단계 제목": hangul_chars_for_width(pg["text_w"], r.body_pt, bold, s.safety_ratio),
            "단계 부제": hangul_chars_for_width(pg["text_w"], r.subtitle_pt, regular, s.safety_ratio),
            "보조 라벨": hangul_chars_for_width(pg["label_w"], r.footnote_pt, regular, s.safety_ratio),
        }
    if template == "matrix":
        mg = matrix_geometry(preset, row_count)
        category_inner_w = s.matrix_category_width - 2 * s.box_padding
        return {
            "분류 셀 한 줄": hangul_chars_for_width(category_inner_w, r.body_pt, bold, s.safety_ratio),
            "대표 항목 한 줄": hangul_chars_for_width(mg["primary_w"], r.body_pt, bold, s.safety_ratio),
            "나열 항목 한 줄": hangul_chars_for_width(
                mg["items_w"] - s.bullet_indent, r.body_pt, regular, s.safety_ratio
            ),
        }
    raise KeyError(template)
