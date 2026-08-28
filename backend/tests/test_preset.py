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
    assert p.fonts.korean == "Noto Sans KR"
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


def test_apply_overrides_rejects_typo_key():
    with pytest.raises(ValidationError):
        apply_overrides(Preset(), {"font_rolez": {"body_pt": 13.0}})


def test_assignment_after_creation_revalidates_floor():
    p = Preset()
    with pytest.raises(ValidationError):
        p.font_roles.body_pt = 5.0


def test_colors_reject_non_hex_value():
    with pytest.raises(ValidationError):
        Preset.model_validate({"colors": {"accent": "#1F4E79"}})


def test_border_width_and_bullet_marker_promoted():
    p = Preset()
    assert p.spacing.border_width_pt == 0.75
    assert p.bullet_marker.char == "•"
    assert p.bullet_marker.font == "Arial"


def test_bullet_marker_override():
    p = apply_overrides(Preset(), {"bullet_marker": {"char": "-"}})
    assert p.bullet_marker.char == "-"
    assert p.bullet_marker.font == "Arial"
