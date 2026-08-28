from slidecaptain.models.deck import Chapter, Deck, DeckMeta, Structure
from slidecaptain.models.render import CapacityWarning
from slidecaptain.pipeline.prompts import (
    build_chapter_prompt,
    build_condense_prompt,
    build_format_retry_prompt,
    build_structure_prompt,
    chapter_response_schema,
    structure_response_schema,
)

META = DeckMeta(title="일본 시장 검토", report_type="strategy", audience="경영진")
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
        instructions="숫자 근거 강조", chars_per_line=75,
    )
    assert "[c1] 시장 현황" in prompt
    assert "[c2] 경쟁 구도" in prompt  # 덱 전체 구조가 맥락으로 들어간다
    assert "최대 11줄" in prompt
    assert "약 75자" in prompt  # 줄당 자수 환산 안내 (적대 리뷰 반영)
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
