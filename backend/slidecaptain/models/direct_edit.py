"""직접 수정의 저장 계약 (개정판 D3c-1, 계획 4.2, 4.3).

슬라이드의 요소(렌더 계획의 프레임)마다 위치 거리, 글자 배율, 글자 색, 채움 색, 숨김을 기록한다. 문구 수정은 지금처럼
슬롯에 저장하고 여기에 기록하지 않는다(계획 4.1 해석). 요소 열쇠는 프레임 이름에서 장 ID를 뺀 부분이고, 열쇠의 집합과
열쇠마다 받는 수정 종류는 `frame_keys`가 슬라이드만 보고 정한다(장 제목과 메타는 이름 집합을 바꾸지 않는다).
`frame_keys`는 layout/templates.py의 프레임 생성 조건을 옮긴 것이고, test_direct_edits가 빌더 결과와 같은지 지킨다.

이 모듈은 모델 모듈(deck.py)이 가져다 쓰므로 슬롯 클래스를 가져오지 않고 `template` 값과 속성으로 판정한다.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, model_serializer, model_validator

# 글자 색과 채움 색은 프리셋 색 역할 이름으로 받는다. 프리셋이 바뀌면 색이 따라 바뀐다(CalloutSlots.tone과 같은 원칙).
# 글자 색에는 글자용 역할을, 채움 색에는 채움용 역할을 둔다 (계획 리뷰 저장 S15)
TextColorRole = Literal["text", "accent", "accent1", "accent2", "danger", "ok", "ink", "ink_soft", "background"]
FillRole = Literal[
    "box_fill", "ink", "ink_soft", "accent1", "accent2", "danger", "ok",
    "surface1", "surface2", "surface3", "surface_danger",
]

EditKind = Literal["move", "font", "text_color", "fill", "hide"]
ALL_KINDS: frozenset[str] = frozenset({"move", "font", "text_color", "fill", "hide"})


def omittable(schema: dict) -> None:
    """기본값이면 직렬화하지 않는 칸의 스키마에서 기본값 표기를 뺀다. 기본값이 적혀 있으면 화면 타입 생성기
    (openapi-typescript)가 "항상 있음"으로 만든다 (D3b-1 구현 기록). 덱, 렌더 계획, 프로젝트 정보가 이 함수 하나를 쓴다
    (D3c-1 리뷰 F13)."""
    schema.pop("default", None)


_omittable = omittable
# 손 편집이나 다른 클라이언트가 보낸 "12"나 true를 숫자로 바꿔 받지 않는다. 도식 슬롯의 strict와 같은 원칙 (D3c-1 리뷰 F4)
_Number = StrictFloat | StrictInt


class ElementEdit(BaseModel):
    """요소 하나의 수정. 칸은 모두 선택이다. 효과가 없는 값은 슬라이드 검증이 버린다(normalize_edits)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # 엔진이 정한 자리에서 옮긴 거리(pt). 절대 좌표가 아니라 거리라서 템플릿 자리가 바뀌면 함께 움직인다(계획 리뷰 저장 S21)
    dx_pt: _Number | None = Field(default=None, json_schema_extra=_omittable)
    dy_pt: _Number | None = Field(default=None, json_schema_extra=_omittable)
    # 요소 글자의 배율. 가장 큰 문단의 절대 크기로 저장하면 내용에 따라 기준 문단이 바뀐다(재리뷰 RR17)
    font_scale: _Number | None = Field(default=None, gt=0, json_schema_extra=_omittable)
    text_color: TextColorRole | None = Field(default=None, json_schema_extra=_omittable)
    fill: FillRole | None = Field(default=None, json_schema_extra=_omittable)
    hidden: StrictBool | None = Field(default=None, json_schema_extra=_omittable)

    @model_validator(mode="after")
    def _paired_offsets(self) -> "ElementEdit":
        if (self.dx_pt is None) != (self.dy_pt is None):
            raise ValueError("위치 수정은 가로와 세로 거리를 함께 적어야 합니다")
        return self

    @model_serializer(mode="wrap")
    def _omit_unset(self, handler):
        # 없는 칸은 쓰지 않는다. 같은 수정이 늘 같은 바이트가 되게 한다
        return {k: v for k, v in handler(self).items() if v is not None}


class KeySpec(BaseModel):
    """요소 열쇠 하나가 받는 수정 종류와 끄는 방식(화면용)."""

    model_config = ConfigDict(frozen=True)

    kinds: frozenset[str]
    # 글상자는 손잡이로만 끌고, 표 묶음과 단계 번호는 본체로 끈다(계획 4.3, 화면 시안)
    drag: Literal["handle", "body"] = "handle"


_TEXT = frozenset({"move", "font", "text_color", "hide"})
_TEXT_FILLED = _TEXT | {"fill"}
_TABLE = frozenset({"move", "hide"})
_BADGE = frozenset({"move", "text_color", "fill", "hide"})


def _text(has_paras: bool = True, filled: bool = False) -> KeySpec:
    kinds = _TEXT_FILLED if filled else _TEXT
    if not has_paras:  # 문단이 없는 요소(빈 불릿 상자)는 글자 크기를 받지 않는다 (재리뷰 RR17)
        kinds = kinds - {"font"}
    return KeySpec(kinds=kinds)


def frame_keys(slide) -> dict[str, KeySpec]:
    """슬라이드의 요소 열쇠와 받는 수정 종류. 쪽 번호는 수정 대상이 아니라 넣지 않는다. 도식은 빈 사전이다.

    비교 차트의 `chart`와 `chart_conditions`, 표의 `table`은 한 열쇠 `table`로 묶는다(계획 4.3).
    강조 밴드의 채움은 슬롯의 `tone`이 정하므로 `fill`을 받지 않는다(재리뷰 RR25).
    """
    slots = slide.slots
    template = slots.template
    if template == "diagram":
        return {}
    if template == "cover":
        return {key: _text() for key in ("cover_title", "subtitle", "date", "presenter")}
    if template == "divider":
        return {key: _text() for key in ("section_no", "section_title")}
    keys: dict[str, KeySpec] = {"title": _text()}
    # 표지와 간지 밖에서만 공통 슬롯을 그린다(layout/templates.py의 build_slide)
    if slide.eyebrow:
        keys["eyebrow"] = _text()
    if slide.subtitle:
        keys["subtitle"] = _text()
    if template == "bullet_box":
        keys["bullets"] = _text(has_paras=bool(slots.bullets))
        keys["conclusion"] = _text(filled=True)
        if slots.footnote:
            keys["footnote"] = _text()
    elif template == "summary":
        keys["conclusion"] = _text(filled=True)
        keys["points"] = _text(has_paras=bool(slots.points))
    elif template == "table":
        keys["table"] = KeySpec(kinds=_TABLE, drag="body")
        if slots.footnote:
            keys["footnote"] = _text()
    elif template == "compare2":
        keys["left_card"] = _text()
        keys["right_card"] = _text()
        keys["conclusion"] = _text(filled=True)
    elif template == "callout":
        keys["text"] = _text()
    elif template == "cards":
        for i, card in enumerate(slots.cards):
            keys[f"card{i}"] = _text(filled=card.emphasis)  # 강조 카드만 채움이 있다
    elif template == "process":
        for i, step in enumerate(slots.steps):
            keys[f"step{i}_badge"] = KeySpec(kinds=_BADGE, drag="body")
            keys[f"step{i}"] = _text()
            if step.notes:
                keys[f"step{i}_labels"] = _text()
    elif template == "matrix":
        for i, row in enumerate(slots.rows):
            keys[f"row{i}_category"] = _text(filled=True)
            if row.primary:
                keys[f"row{i}_primary"] = _text()
            if row.items:
                keys[f"row{i}_items"] = _text()
    else:
        raise ValueError(f"알 수 없는 템플릿입니다: {template}")
    return keys


def normalize_edits(edits: dict[str, ElementEdit], keys: dict[str, KeySpec]) -> dict[str, ElementEdit]:
    """계획 4.2의 정규화 다섯 규칙. 화면(useDeckEditor.apply)도 같은 규칙을 쓴다.

    ① 지금 열쇠에 없는 요소를 버린다 ② 그 요소가 받지 않는 수정 종류를 버린다 ③ 효과가 없는 값(숨김 아님, 거리 0,
    배율 1)을 버린다 ④ 빈 객체가 된 요소를 버린다 ⑤ 열쇠를 이름 순으로 둔다. 그래서 화면에 차이가 없는 수정이
    덱을 새 형식 등급에 묶어 두지 않는다 (계획 리뷰 저장 S19, 재리뷰 RR23).
    """
    result: dict[str, ElementEdit] = {}
    for key in sorted(edits):
        spec = keys.get(key)
        if spec is None:
            continue
        edit = edits[key]
        values: dict = {}
        if "move" in spec.kinds and edit.dx_pt is not None and (edit.dx_pt != 0 or edit.dy_pt != 0):
            values["dx_pt"], values["dy_pt"] = edit.dx_pt, edit.dy_pt
        if "font" in spec.kinds and edit.font_scale is not None and edit.font_scale != 1:
            values["font_scale"] = edit.font_scale
        if "text_color" in spec.kinds and edit.text_color is not None:
            values["text_color"] = edit.text_color
        if "fill" in spec.kinds and edit.fill is not None:
            values["fill"] = edit.fill
        if "hide" in spec.kinds and edit.hidden:
            values["hidden"] = True
        if values:
            result[key] = ElementEdit(**values)
    return result


# 근거 표시인 요소(계획 4.3): 각주와 표 묶음은 늘 근거이고, 그 밖의 요소는 수치 검토가 평가한 칸이 들어 있으면 근거다
EVIDENCE_KEYS = frozenset({"footnote", "table"})

# 요소의 우리말 역할 이름. 화면의 roleName(editor/directEdit.ts)과 같은 표이고 고정 파일 frame-keys.json으로 묶는다.
# 품질 보고 문구가 내부 열쇠 대신 쓴다 (D3c-2 리뷰 F6)
_FIXED_NAMES = {
    "title": "장 제목", "eyebrow": "제목 위 분류", "subtitle": "제목 아래 한 문장", "bullets": "본문 불릿", "points": "요점 목록",
    "conclusion": "결론 상자", "footnote": "각주", "table": "표", "text": "강조 밴드 문구", "left_card": "왼쪽 카드",
    "right_card": "오른쪽 카드", "cover_title": "표지 제목", "date": "날짜", "presenter": "보고자", "section_no": "구분 번호",
    "section_title": "구분 제목", "page_number": "쪽 번호",
}


def role_name(key: str, template: str | None = None) -> str:
    if template == "cover" and key == "subtitle":
        return "표지 부제"
    if key in _FIXED_NAMES:
        return _FIXED_NAMES[key]
    if m := re.fullmatch(r"card(\d+)", key):
        return f"{int(m[1]) + 1}번 카드"
    if m := re.fullmatch(r"step(\d+)(_badge|_labels)?", key):
        return f"{int(m[1]) + 1}단계 " + {"_badge": "번호", "_labels": "라벨"}.get(m[2] or "", "본문")
    if m := re.fullmatch(r"row(\d+)_(category|primary|items)", key):
        return f"{int(m[1]) + 1}번 행 " + {"category": "분류", "primary": "대표 항목", "items": "나열"}[m[2]]
    return key
_LIST_KEYS = {"cards": "card", "steps": "step", "rows": "row"}


def numeric_path_key(slide, path: str) -> str | None:
    """수치 검토 칸의 경로(pipeline/numeric_review.py)가 든 요소 열쇠. 그려지지 않는 칸은 None (재리뷰 RR11).

    예: `/topic`은 title, 표지의 `/slots/title`은 cover_title, `/slots/rows/0/1`(표)은 table, `/slots/steps/0/notes/0`은
    step0_labels, `/slots/rows/2/items/1`(분류)은 row2_items다. 표지와 간지의 `/eyebrow`, `/subtitle`은 그리지 않는다."""
    template = slide.slots.template
    keys = frame_keys(slide)
    parts = path.strip("/").split("/")
    if parts[0] != "slots":
        key = {"topic": "title", "eyebrow": "eyebrow", "subtitle": "subtitle"}.get(parts[0])
        if template in ("cover", "divider"):
            return None
        return key if key in keys else None
    field = parts[1] if len(parts) > 1 else ""
    if template == "cover":
        key = {"title": "cover_title"}.get(field, field)
    elif template == "divider" or template == "callout":
        key = field
    elif template == "table":
        key = "table" if field in ("columns", "rows") else field
    elif template == "compare2":
        key = {"left": "left_card", "right": "right_card"}.get(field, field)
    elif template in ("bullet_box", "summary"):
        key = field
    elif field in _LIST_KEYS and len(parts) > 2:
        index = parts[2]
        base = f"{_LIST_KEYS[field]}{index}"
        if template == "process":
            key = f"{base}_labels" if len(parts) > 3 and parts[3] == "notes" else base
        elif template == "matrix":
            sub = parts[3] if len(parts) > 3 else "category"
            key = f"{base}_{sub}"
        else:
            key = base
    else:
        key = None
    return key if key in keys else None
