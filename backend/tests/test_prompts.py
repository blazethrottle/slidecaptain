from slidecaptain.models.deck import (
    CalloutSlots, CardsSlots, Chapter, Deck, DeckMeta, ProcessSlots, Structure,
)
from slidecaptain.models.render import CapacityWarning
from slidecaptain.pipeline.prompts import (
    TEMPLATE_GUIDE,
    _CONTRACT_LABELS,
    _SLOTS_BY_TEMPLATE,
    build_chapter_prompt,
    build_condense_prompt,
    build_format_retry_prompt,
    build_structure_prompt,
    chapter_response_schema,
    structure_response_schema,
)

META = DeckMeta(title="일본 시장 검토", report_type="strategy", audience="경영진", presenter="사업개발팀")
SOURCES = {"리서치.md": "시장 규모는 500억 원이다", "메모.txt": "경쟁사는 3곳"}


def test_structure_prompt_contains_context_and_sources():
    prompt = build_structure_prompt(META, SOURCES, target_chapters=8, instructions="표를 적극 활용")
    assert "일본 시장 검토" in prompt
    assert "경영진" in prompt
    assert "8장" in prompt
    assert "표를 적극 활용" in prompt
    assert "=== 자료: 리서치.md ===" in prompt
    assert "시장 규모는 500억 원이다" in prompt
    assert "전략기획형" in prompt  # report_type=strategy의 유형 지침


def test_structure_prompt_without_target_count():
    prompt = build_structure_prompt(META, SOURCES)
    assert "자료 분량에 맞게" in prompt


def test_structure_schema_shape():
    schema = structure_response_schema()
    item = schema["properties"]["chapters"]["items"]
    assert set(item["required"]) == {"topic", "conclusion", "template", "source_refs"}
    assert "cover" in item["properties"]["template"]["enum"]


def _deck_two_chapters() -> Deck:
    return Deck(meta=META, structure=Structure(chapters=[
        Chapter(id="c1", topic="시장 현황", conclusion="성장 중", template="bullet_box",
                source_refs=["리서치.md"]),
        Chapter(id="c2", topic="경쟁 구도", template="table"),
    ]))


def test_chapter_prompt_contains_structure_contract_and_report_info():
    deck = _deck_two_chapters()
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], {"리서치.md": SOURCES["리서치.md"]},
        {"bullets_max_lines": 11, "conclusion_max_lines": 2}, today="2026-08-28",
        instructions="숫자 근거 강조", char_hints={"본문 한 줄": 73},
    )
    assert "[c1] 시장 현황" in prompt
    assert "[c2] 경쟁 구도" in prompt  # 덱 전체 구조가 맥락으로 들어간다
    assert "최대 11줄 (한 줄짜리 항목 11개 기준)" in prompt  # 줄 수와 항목 수를 같은 것으로 읽게 한다 (2026-09-02 태스크 A)
    assert "본문 한 줄 약 73자" in prompt  # 줄당 자수 환산 안내는 칸별 힌트 맵에서 온다
    assert "그 절반" not in prompt  # 종전의 어림 안내는 실측값으로 대체됐다
    assert "숫자 근거 강조" in prompt
    assert "2026-08-28" in prompt  # 보고 정보 블록의 오늘 날짜 (결정 12)
    assert "경영진" in prompt
    assert "메모.txt" not in prompt  # 근거로 매핑되지 않은 자료는 넣지 않는다


def test_cover_prompt_omits_sources_block():
    # cover는 자료가 필요 없다: 자료 전문을 넣으면 호출마다 사용량이 낭비된다 (결정 11)
    deck = Deck(meta=META, structure=Structure(chapters=[
        Chapter(id="c1", topic="표지", template="cover"),
    ]))
    prompt = build_chapter_prompt(deck, deck.structure.chapters[0], SOURCES, {}, today="2026-08-28")
    assert "=== 자료:" not in prompt
    assert "일본 시장 검토" in prompt  # 보고 정보(덱 제목)는 들어간다


def test_chapter_schema_is_slot_model_schema():
    schema = chapter_response_schema("bullet_box")
    assert "conclusion" in schema["properties"]
    schema_table = chapter_response_schema("table")
    assert "columns" in schema_table["properties"]


def test_retry_prompt_carries_failed_raw_text():
    base = "기본 프롬프트"
    retry = build_format_retry_prompt(base, raw_text="깨진 응답 원문")
    assert base in retry
    assert "깨진 응답 원문" in retry  # 매 호출이 새 세션이라 직전 응답을 동봉해야 한다 (결정 12)


def test_condense_prompt_carries_draft_and_warnings():
    base = "기본 프롬프트"
    warning = CapacityWarning(chapter_id="c1", slot="bullets", message="bullets 분량이 영역을 30pt 넘습니다",
                              needed_pt=130.0, available_pt=100.0)
    condense = build_condense_prompt(base, [warning], draft_json='{"bullets": ["초안"]}')
    assert base in condense
    assert "bullets" in condense
    assert '{"bullets": ["초안"]}' in condense  # 직전 초안 동봉 (결정 12)
    assert "축약" in condense


def test_condense_prompt_without_warnings_gives_general_instruction():
    # 수동 축약(결정 13): 초과가 아니어도 사용자가 축약을 요청할 수 있다
    condense = build_condense_prompt("기본", [], draft_json="{}")
    assert "간결" in condense
    assert "초과" not in condense


def test_prompts_forbid_copying_audience_into_document_and_omit_presenter():
    # 피보고자는 문체 기준으로만 전달하고 문서에 옮겨 적지 않게 한다. 보고자는 AI에 주지 않는다(메타에서 렌더). 파일럿 관찰 6, 2026-09-01
    structure_prompt = build_structure_prompt(META, SOURCES)
    deck = _deck_two_chapters()
    chapter_prompt = build_chapter_prompt(deck, deck.structure.chapters[0], SOURCES, {}, today="2026-09-01")
    for prompt in (structure_prompt, chapter_prompt):
        assert "피보고자: 경영진" in prompt
        assert "피보고자 항목 값을 표지, 제목, 호칭, 인사말에 옮겨 적지 않는다" in prompt
        assert "사업개발팀" not in prompt
        assert "보고 대상" not in prompt  # 종전 템플릿 안내 "표지 (제목, 부제, 날짜, 보고 대상)"의 흔적이 없어야 한다


def test_contract_block_uses_korean_labels_for_cover_and_divider_keys():
    # 표지와 간지 계약 키에 한글 라벨이 없으면 영문 키가 그대로 프롬프트에 노출된다 (계획서 적대 리뷰 F2, 2026-09-03)
    deck = Deck(meta=META, structure=Structure(chapters=[Chapter(id="c1", topic="표지", template="cover")]))
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], SOURCES,
        {"cover_title_max_lines": 1, "subtitle_max_lines": 1, "date_max_lines": 1},
        today="2026-09-02", char_hints={"표지 제목": 30, "부제": 60},
    )
    assert "_max_lines" not in prompt
    assert "- 표지 제목: 최대 1줄" in prompt
    assert "- 부제: 최대 1줄" in prompt
    assert "표지 제목 약 30자" in prompt and "부제 약 60자" in prompt
    deck = Deck(meta=META, structure=Structure(chapters=[Chapter(id="c1", topic="간지", template="divider")]))
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], SOURCES,
        {"section_no_max_lines": 1, "section_title_max_lines": 1}, today="2026-09-02",
    )
    assert "- 섹션 제목: 최대 1줄" in prompt and "_max_lines" not in prompt


# ---- 강조 밴드(callout) 등록 (2026-09-07 DB-1) ----
# 10종 전면 재작성은 DB-5 소관이므로 여기서는 한 줄만 늘었는지, 등록이 빠짐없이 됐는지만 본다.


def test_template_guide_gains_exactly_one_line_for_callout():
    lines = TEMPLATE_GUIDE.splitlines()
    callout_lines = [ln for ln in lines if "callout" in ln]
    assert len(callout_lines) == 1
    # 기존 6종 문구는 손대지 않는다 (DB-5 전면 재작성 전까지)
    assert "- bullet_box: 가장 흔한 본문 장 (불릿 + 결론 박스 + 선택 각주)" in lines


def test_callout_registered_in_slot_map_and_contract_labels():
    assert _SLOTS_BY_TEMPLATE["callout"] is CalloutSlots
    assert "text_max_lines" in _CONTRACT_LABELS


def test_callout_structure_schema_enum_includes_new_template():
    schema = structure_response_schema()
    assert "callout" in schema["properties"]["chapters"]["items"]["properties"]["template"]["enum"]


def test_callout_contract_block_uses_korean_label_and_char_hint():
    deck = Deck(meta=META, structure=Structure(chapters=[Chapter(id="c1", topic="강조", template="callout")]))
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], SOURCES,
        {"text_max_lines": 3}, today="2026-09-07", char_hints={"밴드 안 한 줄": 40},
    )
    assert "_max_lines" not in prompt
    assert "최대 3줄" in prompt
    assert "밴드 안 한 줄 약 40자" in prompt


def test_callout_chapter_schema_matches_slot_model():
    schema = chapter_response_schema("callout")
    assert "text" in schema["properties"]
    assert "tone" in schema["properties"]


# ---- 카드(cards) 등록 (2026-09-07 DB-2) ----
# 10종 전면 재작성은 DB-5 소관이므로 여기서는 한 줄만 늘었는지, 등록이 빠짐없이 됐는지,
# 개수 제약(2~4)이 계약 블록에 드러나는지만 본다.


def test_template_guide_gains_exactly_one_line_for_cards():
    lines = TEMPLATE_GUIDE.splitlines()
    cards_lines = [ln for ln in lines if "cards" in ln]
    assert len(cards_lines) == 1
    # 기존 문구는 손대지 않는다 (DB-5 전면 재작성 전까지)
    assert "- bullet_box: 가장 흔한 본문 장 (불릿 + 결론 박스 + 선택 각주)" in lines
    assert "- callout: 전폭 강조 밴드. 짧은 핵심 문장 하나만 크게 강조할 때 쓴다 (1~3줄)" in lines


def test_cards_registered_in_slot_map_and_contract_labels():
    assert _SLOTS_BY_TEMPLATE["cards"] is CardsSlots
    assert "card_badge_max_lines" in _CONTRACT_LABELS
    assert "card_heading_max_lines" in _CONTRACT_LABELS  # compare2와 공유하는 기존 라벨
    assert "card_bullets_max_lines" in _CONTRACT_LABELS
    assert "card_tail_max_lines" in _CONTRACT_LABELS


def test_cards_structure_schema_enum_includes_new_template():
    schema = structure_response_schema()
    assert "cards" in schema["properties"]["chapters"]["items"]["properties"]["template"]["enum"]


def test_cards_contract_block_states_the_card_count_constraint():
    deck = Deck(meta=META, structure=Structure(chapters=[Chapter(id="c1", topic="카드", template="cards")]))
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], SOURCES,
        {"card_badge_max_lines": 1, "card_heading_max_lines": 1, "card_bullets_max_lines": 5,
         "card_tail_max_lines": 1},
        today="2026-09-07", char_hints={"카드 안 한 줄": 20},
    )
    assert "_max_lines" not in prompt
    assert "- 카드 개수: 2개 이상 4개 이하" in prompt
    assert "- 카드 배지: 최대 1줄" in prompt
    assert "- 카드 꼬리 라벨: 최대 1줄" in prompt
    assert "카드 안 한 줄 약 20자" in prompt


def test_other_templates_contract_block_has_no_card_count_line():
    # 카드 개수 문구는 cards 전용이다: 다른 템플릿의 프롬프트를 오염시키면 안 된다
    deck = Deck(meta=META, structure=Structure(chapters=[Chapter(id="c1", topic="주제", template="bullet_box")]))
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], SOURCES,
        {"bullets_max_lines": 11, "conclusion_max_lines": 2}, today="2026-09-07",
    )
    assert "카드 개수" not in prompt


def test_cards_chapter_schema_matches_slot_model():
    schema = chapter_response_schema("cards")
    assert "cards" in schema["properties"]
    cards_field = schema["properties"]["cards"]
    assert cards_field.get("minItems") == 2
    assert cards_field.get("maxItems") == 4


# ---- 번호 단계(process) 등록 (2026-09-07 DB-3) ----
# 10종 전면 재작성은 DB-5 소관이므로 여기서는 한 줄만 늘었는지, 등록이 빠짐없이 됐는지,
# 개수 제약(3~6)이 계약 블록에 드러나는지만 본다.


def test_template_guide_gains_exactly_one_line_for_process():
    lines = TEMPLATE_GUIDE.splitlines()
    process_lines = [ln for ln in lines if "process" in ln]
    assert len(process_lines) == 1
    # 기존 문구는 손대지 않는다 (DB-5 전면 재작성 전까지)
    assert "- bullet_box: 가장 흔한 본문 장 (불릿 + 결론 박스 + 선택 각주)" in lines
    assert "- cards: 카드 2~4개로 항목을 나란히 비교하거나 소개할 때 쓴다 (배지와 꼬리 라벨은 선택)" in lines


def test_process_registered_in_slot_map_and_contract_labels():
    assert _SLOTS_BY_TEMPLATE["process"] is ProcessSlots
    assert "step_heading_max_lines" in _CONTRACT_LABELS
    assert "step_subtitle_max_lines" in _CONTRACT_LABELS
    assert "step_label_max_lines" in _CONTRACT_LABELS


def test_process_structure_schema_enum_includes_new_template():
    schema = structure_response_schema()
    assert "process" in schema["properties"]["chapters"]["items"]["properties"]["template"]["enum"]


def test_process_contract_block_states_the_step_count_constraint():
    deck = Deck(meta=META, structure=Structure(chapters=[Chapter(id="c1", topic="절차", template="process")]))
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], SOURCES,
        {"step_heading_max_lines": 1, "step_subtitle_max_lines": 3, "step_label_max_lines": 1},
        today="2026-09-07", char_hints={"단계 제목": 20},
    )
    assert "_max_lines" not in prompt
    assert "- 단계 개수: 3개 이상 6개 이하" in prompt
    assert "- 단계 제목: 최대 1줄" in prompt
    assert "단계 제목 약 20자" in prompt


def test_other_templates_contract_block_has_no_step_count_line():
    # 단계 개수 문구는 process 전용이다: 다른 템플릿의 프롬프트를 오염시키면 안 된다
    deck = Deck(meta=META, structure=Structure(chapters=[Chapter(id="c1", topic="주제", template="bullet_box")]))
    prompt = build_chapter_prompt(
        deck, deck.structure.chapters[0], SOURCES,
        {"bullets_max_lines": 11, "conclusion_max_lines": 2}, today="2026-09-07",
    )
    assert "단계 개수" not in prompt


def test_process_chapter_schema_matches_slot_model():
    schema = chapter_response_schema("process")
    assert "steps" in schema["properties"]
    steps_field = schema["properties"]["steps"]
    assert steps_field.get("minItems") == 3
    assert steps_field.get("maxItems") == 6
