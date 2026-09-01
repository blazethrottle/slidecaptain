import asyncio

import pytest

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import BulletBoxSlots, Chapter, Deck, DeckMeta, Structure, TableSlots
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.provider import ProviderCallFailed, ProviderResponse
from slidecaptain.pipeline.service import GenerationService

METRICS = FontMetrics.load_default()
SOURCES = {"리서치.md": "시장 규모는 500억 원이다. 2026년 기준."}


class StubProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _service(responses) -> tuple[GenerationService, StubProvider]:
    stub = StubProvider(responses)
    return GenerationService(stub, METRICS), stub


def _deck() -> Deck:
    return Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c1", topic="시장 현황", conclusion="성장", template="bullet_box",
                source_refs=["리서치.md"]),
    ]))


STRUCTURE_PAYLOAD = {"chapters": [
    {"topic": "표지", "conclusion": "", "template": "cover", "source_refs": []},
    {"topic": "시장 현황", "conclusion": "규모 500억", "template": "bullet_box",
     "source_refs": ["리서치.md", "없는파일.md"]},
]}

SLOTS_PAYLOAD = {"template": "bullet_box",
                 "bullets": [{"text": "시장 규모 500억", "level": 0}],
                 "conclusion": "성장 지속", "footnote": ""}


def test_generate_structure_ok_assigns_ids_and_filters_refs():
    service, stub = _service([ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r")])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "ok"
    ids = [ch.id for ch in result.structure.chapters]
    assert ids == ["c1", "c2"]
    assert result.structure.chapters[1].source_refs == ["리서치.md"]  # 실존 파일만
    assert result.format_retried is False
    assert len(stub.calls) == 1


def test_generate_structure_format_retry_then_success():
    service, stub = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad"),
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="good"),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "ok"
    assert result.format_retried is True
    assert "형식" in stub.calls[1][0]  # 재시도 프롬프트에 형식 오류 안내가 붙는다


def test_generate_structure_format_failure_returns_raw():
    service, _ = _service([
        ProviderResponse(structured=None, raw_text="원문1"),
        ProviderResponse(structured={"chapters": "문자열이면 안 됨"}, raw_text="원문2"),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "format_error"
    assert result.structure is None
    assert result.raw_text == "원문2"


def test_generate_structure_flags_unverified_numbers():
    payload = {"chapters": [{"topic": "시장", "conclusion": "규모 700억으로 성장",
                             "template": "bullet_box", "source_refs": []}]}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.unverified_numbers == ["700"]


def test_generate_chapter_ok_normalizes_and_verifies():
    payload = {"template": "bullet_box",
               "bullets": [{"text": "시장  규모\n500억", "level": 0}],
               "conclusion": "성장 지속", "footnote": ""}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.slots.bullets[0].text == "시장 규모 500억"  # 정규화 적용
    assert result.unverified_numbers == []
    assert result.warnings == []
    assert result.condensed is False


def test_generate_chapter_condenses_once_on_overflow():
    long_bullets = [{"text": f"근거 없는 장문 불릿 문장 {i}번이며 자료 원문의 맥락 설명이 길게 이어진다", "level": 0}
                    for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, stub = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r2"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is True
    assert result.warnings == []
    assert "축약" in stub.calls[1][0]


def test_generate_chapter_keeps_warnings_if_condense_still_over():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=over_payload, raw_text="r2"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is True
    assert any(w.slot == "bullets" for w in result.warnings)


def test_generate_chapter_condense_format_failure_keeps_first_draft():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=None, raw_text="깨진 축약"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is False  # 축약 실패: 초안 유지
    assert any(w.slot == "bullets" for w in result.warnings)
    assert len(result.slots.bullets) == 30


def test_generate_chapter_template_field_is_forced():
    wrong_template = dict(SLOTS_PAYLOAD, template="table")
    service, _ = _service([ProviderResponse(structured=wrong_template, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    # AI가 template을 잘못 채워도 장의 템플릿으로 강제되어 형식 오류가 아니다
    assert result.status == "ok"
    assert result.slots.template == "bullet_box"


def test_generate_chapter_unknown_chapter_raises():
    service, _ = _service([])
    with pytest.raises(ValueError):
        asyncio.run(service.generate_chapter(_deck(), "없는장", SOURCES, Preset()))


def test_provider_error_propagates():
    service, _ = _service([ProviderCallFailed("한도 소진")])
    with pytest.raises(ProviderCallFailed):
        asyncio.run(service.generate_structure(_deck().meta, SOURCES))


SOURCES_TWO = {"리서치.md": "시장 규모는 500억 원이다", "별도.md": "점유율은 37%다"}


def _deck_refs_one() -> Deck:
    return Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c1", topic="시장 현황", conclusion="성장", template="bullet_box",
                source_refs=["리서치.md"]),
    ]))


def test_chapter_numbers_checked_against_all_sources_not_only_refs():
    # 결정 6: 대조는 자료 전체 상대. 37은 refs 밖 자료(별도.md)에 있으므로 경고가 아니다
    payload = {"template": "bullet_box",
               "bullets": [{"text": "점유율 37%", "level": 0}],
               "conclusion": "성장", "footnote": ""}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck_refs_one(), "c1", SOURCES_TWO, Preset()))
    assert result.unverified_numbers == []


def test_chapter_unverified_number_reported():
    payload = {"template": "bullet_box",
               "bullets": [{"text": "점유율 89%", "level": 0}],
               "conclusion": "성장", "footnote": ""}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(_deck_refs_one(), "c1", SOURCES_TWO, Preset()))
    assert result.unverified_numbers == ["89"]


def test_generate_chapter_format_retry_then_success():
    service, stub = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad"),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="good"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.format_retried is True
    assert "bad" in stub.calls[1][0]  # 재시도 프롬프트에 실패 원문이 동봉된다 (결정 12)


def test_generate_chapter_format_failure_returns_raw():
    service, _ = _service([
        ProviderResponse(structured=None, raw_text="원문1"),
        ProviderResponse(structured=None, raw_text="원문2"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "format_error"
    assert result.slots is None
    assert result.raw_text == "원문2"


def test_long_title_warning_does_not_trigger_condense():
    # title 경고는 슬롯 재생성으로 못 고친다: 축약을 발동하면 호출만 낭비된다 (결정 5)
    long_topic = "제목 영역 한 줄을 확실히 넘기기 위한 매우 길고 긴 장 제목 문장이며 계속 이어진다" * 2
    deck = Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c1", topic=long_topic, conclusion="성장", template="bullet_box",
                source_refs=["리서치.md"]),
    ]))
    service, stub = _service([ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    result = asyncio.run(service.generate_chapter(deck, "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert len(stub.calls) == 1  # 축약 호출이 발동하지 않는다
    assert result.condensed is False
    assert any(w.slot == "title" for w in result.warnings)  # 경고 자체는 결과에 남는다


def test_condense_call_carries_draft_json():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, stub = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r2"),
    ])
    asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert "장문 불릿 0번" in stub.calls[1][0]  # 축약 프롬프트에 직전 초안이 동봉된다 (결정 12)


def test_condense_provider_error_keeps_draft():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets,
                    "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1"),
        ProviderCallFailed("한도"),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"  # 축약 호출 실패로 유효한 초안을 잃지 않는다
    assert result.condensed is False
    assert any(w.slot == "bullets" for w in result.warnings)


def test_cover_metadata_fields_exempt_from_number_check():
    deck = Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c0", topic="표지", template="cover"),
    ]))
    payload = {"template": "cover", "title": "검토", "subtitle": "", "date": "2026-08-28"}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(deck, "c0", SOURCES, Preset()))
    assert result.unverified_numbers == []  # date는 대조 대상이 아니다 (결정 6)


def test_condense_chapter_manual():
    # 수동 축약 (결정 13): 현재 슬롯을 초안으로 받아 1회 축약한다
    current = BulletBoxSlots(bullets=[{"text": "시장 규모 500억과 부연 설명", "level": 0}],
                             conclusion="성장 지속")
    service, stub = _service([ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    result = asyncio.run(service.condense_chapter(_deck(), "c1", current, SOURCES, Preset()))
    assert result.status == "ok"
    assert result.condensed is True
    assert "축약" in stub.calls[0][0]
    assert "시장 규모 500억과 부연 설명" in stub.calls[0][0]  # 현재 슬롯이 초안으로 동봉된다


def test_condense_chapter_template_mismatch_raises():
    wrong = TableSlots(columns=["a"], rows=[["b"]])
    service, _ = _service([])
    with pytest.raises(ValueError):
        asyncio.run(service.condense_chapter(_deck(), "c1", wrong, SOURCES, Preset()))


def test_deck_title_numbers_count_as_verified():
    meta = DeckMeta(title="2026 사업 검토")
    payload = {"chapters": [
        {"topic": "2026 전략", "conclusion": "", "template": "bullet_box", "source_refs": []}
    ]}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_structure(meta, {"a.md": "자료에는 연도가 없다"}))
    assert result.status == "ok"
    assert "2026" not in result.unverified_numbers  # 덱 제목이 대조 말뭉치에 포함된다


def test_chapter_numbers_verified_against_deck_title():
    deck = Deck(
        meta=DeckMeta(title="2026 사업 검토"),
        structure=Structure(chapters=[Chapter(id="c1", topic="표지", template="cover")]),
    )
    payload = {"template": "cover", "title": "2026 사업 검토", "subtitle": "", "date": ""}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(deck, "c1", {"a.md": "연도 없음"}, Preset()))
    assert result.status == "ok"
    assert "2026" not in result.unverified_numbers


def test_empty_refs_fall_back_to_all_sources_in_prompt():
    # 결정 11: 근거 매핑이 비면 자료 전체로 폴백한다 (매핑 누락이 생성 불능으로 이어지지 않게)
    deck = Deck(meta=DeckMeta(title="검토"), structure=Structure(chapters=[
        Chapter(id="c1", topic="시장 현황", conclusion="성장", template="bullet_box"),
    ]))
    service, stub = _service([ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r")])
    asyncio.run(service.generate_chapter(deck, "c1", SOURCES_TWO, Preset()))
    prompt = stub.calls[0][0]
    assert "시장 규모는 500억 원이다" in prompt
    assert "점유율은 37%다" in prompt


def test_cover_slots_ignore_audience_and_presenter_from_ai():
    # 표지 슬롯에는 보고자도 피보고자도 없다: 보고자는 메타에서 렌더하고 피보고자는 문서에 적지 않는다 (파일럿 관찰 6, 2026-09-01)
    deck = Deck(meta=DeckMeta(title="검토", presenter="사업개발팀", audience="경영진"), structure=Structure(chapters=[
        Chapter(id="c0", topic="표지", template="cover"),
    ]))
    payload = {"template": "cover", "title": "검토", "subtitle": "", "date": "",
               "audience": "경영진", "presenter": "AI가 적은 값"}
    service, _ = _service([ProviderResponse(structured=payload, raw_text="r")])
    result = asyncio.run(service.generate_chapter(deck, "c0", SOURCES, Preset()))
    assert result.status == "ok"
    assert set(result.slots.model_dump()) == {"template", "title", "subtitle", "date"}
