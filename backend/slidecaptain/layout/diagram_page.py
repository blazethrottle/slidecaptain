"""원래 의미 입력에서 계산한 한 페이지를 두 렌더 소비자에게 전달한다."""

from collections.abc import Sequence
import hashlib
import json
import math

from slidecaptain.layout.diagram import build_diagram_layout, _metrics_snapshot, _supported_text
from slidecaptain.layout.style import style_from_preset
from slidecaptain.layout.templates import (
    _common_slot_frames, _footnote_frame, _page_number_frame, _title_frame, slide_geometry,
)
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Chapter
from slidecaptain.models.diagram import DiagramSpec, _evidence_input
from slidecaptain.models.diagram_render import DiagramLayoutIssue
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import DiagramPagePlan, RenderPlan, SlidePlan
from slidecaptain.models.story import Evidence


class DiagramRenderBlocked(ValueError):
    def __init__(self, issues: list[DiagramLayoutIssue]):
        self.issues = issues
        super().__init__("도식 페이지를 배치할 수 없습니다: " + "; ".join(i.message for i in issues))


def build_diagram_render_plan(
    payload: dict | str | DiagramSpec, preset: Preset, metrics: FontMetrics,
    *, evidence: Sequence[Evidence], title: str, eyebrow: str = "", subtitle: str = "",
    footnote: str = "", page_no: int = 1,
) -> RenderPlan:
    """파일/AI/저장 부작용 없이 계산한다. 배치 JSON은 입력으로 받지 않는다.

    이 출력은 내부 writer/preview 경계다. 저장하거나 외부에서 받은 RenderPlan을
    제출본 승인으로 신뢰하지 않으며, 모든 실제 검수 상태는 not_run이다.
    """
    texts = dict(title=title, eyebrow=eyebrow, subtitle=subtitle, footnote=footnote)
    if any(type(text) is not str for text in texts.values()) or not title.strip():
        raise ValueError("제목은 비어 있지 않아야 하고 공통 문구는 문자열이어야 합니다")
    if type(page_no) is not int or page_no <= 0:
        raise ValueError("페이지 번호는 양의 정수여야 합니다")
    if not isinstance(preset, Preset):
        raise ValueError("Preset 입력이 필요합니다")
    preset = Preset.model_validate(_evidence_input(preset))
    metrics = _metrics_snapshot(metrics)
    stroke_emu = preset.spacing.border_width_pt * 12700
    if (not all(72 <= size <= 4032 for size in (preset.page_width_pt, preset.page_height_pt)) or
            not math.isfinite(stroke_emu) or round(stroke_emu) < 1):
        raise DiagramRenderBlocked([DiagramLayoutIssue(
            code='invalid_geometry', target_id='page',
            message='PPTX 페이지 크기는 72~4032pt이고 선 굵기는 최소 1EMU로 표현할 수 있어야 합니다.',
        )])
    used_fonts = [preset.font_roles.title_pt, preset.font_roles.body_pt, preset.font_roles.box_pt,
                  preset.font_roles.page_number_pt]
    used_fonts += [getattr(preset.font_roles, name + '_pt')
                   for name in ('eyebrow', 'subtitle', 'footnote') if texts[name]]
    if any(not 1 <= font <= 4000 or not 0 < font * preset.spacing.line_spacing <= 1584
           for font in used_fonts) or any(
           not math.isfinite(v) or abs(v - round(v, 2)) > 1e-8
           for font in used_fonts for v in (font, font * preset.spacing.line_spacing)):
        raise DiagramRenderBlocked([DiagramLayoutIssue(
            code='unsupported_spacing', target_id='page',
            message='현재 PPTX 라이터는 글자 1~4000pt, 행간 1584pt 이하와 0.01pt 단위를 지원합니다.',
        )])
    layout = build_diagram_layout(
        payload, preset, metrics, evidence=evidence, eyebrow=eyebrow, subtitle=subtitle,
    )
    if layout.status == "blocked":
        raise DiagramRenderBlocked(layout.issues)
    chapter = Chapter(id=layout.diagram_id, topic=title, template="bullet_box")
    g = slide_geometry(preset, eyebrow, subtitle)
    headers = []
    issues = []

    def issue(code, name, message):
        issues.append(DiagramLayoutIssue(code=code, target_id=name, message=message))

    # 공통 프레임 생성 자체가 줄바꿈을 계산한다. 아래 사후 용량 검사보다 먼저
    # 수치가 넘칠 수 있으므로 각 슬롯의 생성도 같은 typed 경계에 둔다.
    for slot, builder in (
        ('eyebrow', lambda: _common_slot_frames(chapter, g, eyebrow, '', preset, metrics)),
        ('subtitle', lambda: _common_slot_frames(chapter, g, '', subtitle, preset, metrics)),
        ('title', lambda: [_title_frame(chapter, preset, metrics, g)]),
        ('footnote', lambda: [_footnote_frame(chapter, footnote, preset, metrics)] if footnote else []),
        ('page_number', lambda: [_page_number_frame(chapter, page_no, preset)]),
    ):
        try:
            headers.extend(builder())
        except OverflowError:
            issue('invalid_geometry', f'{chapter.id}:{slot}', '공통 문구의 줄바꿈 수치를 계산할 수 없습니다.')

    for frame in headers:
        if (not all(math.isfinite(v) for v in (frame.x, frame.y, frame.w, frame.h)) or
            min(frame.x, frame.y) < 0 or min(frame.w, frame.h) <= 0 or
            frame.x + frame.w > preset.page_width_pt or frame.y + frame.h > preset.page_height_pt):
            issue("invalid_geometry", frame.name, "공통 텍스트 영역이 페이지 경계를 벗어납니다.")
        for para in frame.paras:
            face = metrics.face(para.bold)
            if not _supported_text(para.text, face):
                issue("unsupported_text", frame.name, "공백이 축약되거나 폭이 확인되지 않은 공통 문구입니다.")
                continue
            try:
                width = max(face.width_pt(line, para.font_pt) for line in para.lines)
                height = len(para.lines) * para.font_pt * preset.spacing.line_spacing
            except OverflowError:
                issue("invalid_geometry", frame.name, "공통 문구의 폭과 높이를 계산할 수 없습니다.")
                continue
            if not math.isfinite(width) or not math.isfinite(height):
                issue("invalid_geometry", frame.name, "공통 문구의 폭과 높이가 유한하지 않습니다.")
            elif width > frame.w * preset.spacing.safety_ratio + 1e-8:
                issue("width_overflow", frame.name, "공통 문구의 글자 폭이 예약 영역을 초과합니다.")
            if height > frame.h + 1e-8:
                issue("height_overflow", frame.name, "공통 문구의 줄 수가 예약 영역을 초과합니다.")

    def overlaps(a, b):
        return (a.x < b.x + b.w - 1e-8 and b.x < a.x + a.w - 1e-8 and
                a.y < b.y + b.h - 1e-8 and b.y < a.y + a.h - 1e-8)

    for i, frame in enumerate(headers):
        if overlaps(frame, layout.plan.content_bounds) or any(overlaps(frame, other) for other in headers[i + 1:]):
            issue("invalid_geometry", frame.name, "공통 문구의 예약 영역이 다른 내용 영역과 겹칩니다.")
    if issues:
        raise DiagramRenderBlocked(issues)
    fingerprint = hashlib.sha256(json.dumps({
        "rule_version": "q3b-render-v1", "layout_fingerprint": layout.input_fingerprint,
        "headers": texts, "page_no": page_no,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode('utf-8')).hexdigest()
    page = DiagramPagePlan(
        input_fingerprint=fingerprint, layout=layout.plan, headers=headers, background=preset.colors.background,
    )
    return RenderPlan(
        page_width_pt=preset.page_width_pt, page_height_pt=preset.page_height_pt,
        style=style_from_preset(preset),
        slides=[SlidePlan(chapter_id=layout.diagram_id, template="diagram", frames=[], diagram=page)],
    )
