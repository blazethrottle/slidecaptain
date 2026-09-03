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


def test_default_preset_passes_safety_validation():
    # 하한과 상한이 추가된 뒤에도 기본 프리셋은 그대로 유효하다 (회귀)
    Preset()


def test_rejects_nan_page_width():
    with pytest.raises(ValidationError):
        Preset.model_validate({"page_width_pt": float("nan")})


def test_rejects_inf_page_width():
    with pytest.raises(ValidationError):
        Preset.model_validate({"page_width_pt": float("inf")})


def test_rejects_inf_safety_ratio():
    with pytest.raises(ValidationError):
        Preset.model_validate({"spacing": {"safety_ratio": float("inf")}})


def test_rejects_negative_page_width_pt():
    with pytest.raises(ValidationError):
        Preset.model_validate({"page_width_pt": -10.0})


def test_rejects_zero_safety_ratio():
    # safety_ratio 0은 모든 줄바꿈을 무한히 쪼갠다
    with pytest.raises(ValidationError):
        Preset.model_validate({"spacing": {"safety_ratio": 0.0}})


def test_rejects_content_width_collapsing_margins():
    # 여백 합이 페이지 폭을 거의 다 먹으면 내용 폭이 100pt 아래로 무너진다
    with pytest.raises(ValidationError) as exc:
        Preset.model_validate({"spacing": {"margin_left": 460.0, "margin_right": 460.0}})
    assert "내용 폭" in str(exc.value)


def test_rejects_content_height_collapsing_title_height():
    # title_height=1000은 필드 하한(>0)은 통과하지만 내용 높이를 음수로 만든다 (실측)
    with pytest.raises(ValidationError) as exc:
        Preset.model_validate({"spacing": {"title_height": 1000.0}})
    assert "내용 높이" in str(exc.value)


def test_rejects_content_height_collapsing_footnote_height():
    with pytest.raises(ValidationError) as exc:
        Preset.model_validate({"spacing": {"footnote_height": 500.0}})
    assert "내용 높이" in str(exc.value)
