"""일반 슬라이드와 도식이 공유하는 렌더 스타일."""

from slidecaptain.models.preset import Preset
from slidecaptain.models.render import RenderStyle


def style_from_preset(preset: Preset) -> RenderStyle:
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
