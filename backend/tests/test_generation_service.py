import asyncio
import inspect

import pytest

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import BulletBoxSlots, Chapter, Deck, DeckMeta, Structure, TableSlots
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.provider import CallUsage, ProviderCallFailed, ProviderResponse
from slidecaptain.pipeline.service import GenerationService, UsageRecord

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


def _usage(**overrides) -> CallUsage:
    """단계 5A 묶음 C 태스크 C2 테스트용 CallUsage. 기본값은 전부 채워져 있다."""
    base = dict(
        model="claude-sonnet-4-5-20250929",
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        duration_ms=1000,
        duration_api_ms=900,
        num_turns=2,
        cost_usd=0.01,
        stop_reason="end_turn",
        terminal_reason="completed",
        api_error_status=None,
        token_source="model_usage",
    )
    base.update(overrides)
    return CallUsage(**base)


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


# -- 태스크 C2: 서비스 합산 (단계 5A 묶음 C) ---------------------------------

def test_usage_summary_ok_single_call():
    usage = _usage(input_tokens=10, output_tokens=5, cost_usd=0.01)
    service, _ = _service([ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r", usage=usage)])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.usage.calls == 1
    assert result.usage.failed_calls == 0
    assert result.usage.unmeasured_calls == 0
    assert result.usage.models == ["claude-sonnet-4-5-20250929"]
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.cost_usd == 0.01
    assert len(result.usage.records) == result.usage.calls
    assert result.usage.records[0].purpose == "generate"


def test_usage_format_retry_sums_both_calls():
    service, _ = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad", usage=_usage(input_tokens=10)),
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="good", usage=_usage(input_tokens=20)),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "ok"
    assert result.usage.calls == 2
    assert [r.purpose for r in result.usage.records] == ["generate", "format_retry"]
    assert result.usage.input_tokens == 30


def test_usage_format_retry_failure_still_counts_calls():
    service, _ = _service([
        ProviderResponse(structured=None, raw_text="원문1", usage=_usage()),
        ProviderResponse(structured=None, raw_text="원문2", usage=_usage()),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.status == "format_error"
    assert result.usage.calls == 2


def test_usage_chapter_auto_condense_purposes():
    long_bullets = [{"text": f"근거 없는 장문 불릿 문장 {i}번이며 자료 원문의 맥락 설명이 길게 이어진다", "level": 0}
                    for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets, "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1", usage=_usage()),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r2", usage=_usage()),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert [r.purpose for r in result.usage.records] == ["generate", "condense"]


def test_usage_chapter_format_retry_then_condense_purposes():
    long_bullets = [{"text": f"근거 없는 장문 불릿 문장 {i}번이며 자료 원문의 맥락 설명이 길게 이어진다", "level": 0}
                    for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets, "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad", usage=_usage()),
        ProviderResponse(structured=over_payload, raw_text="r1", usage=_usage()),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="r2", usage=_usage()),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert [r.purpose for r in result.usage.records] == ["generate", "format_retry", "condense"]


def test_usage_condense_call_failure_with_usage_counts_as_failed_not_unmeasured():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets, "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1", usage=_usage(input_tokens=100)),
        ProviderCallFailed("한도", usage=_usage(input_tokens=50)),
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"  # 축약 호출 실패로 유효한 초안을 잃지 않는다
    assert result.usage.calls == 2
    assert result.usage.failed_calls == 1
    assert result.usage.unmeasured_calls == 0
    assert result.usage.records[-1].ok is False
    assert result.usage.input_tokens == 150  # 실패 호출의 토큰도 합계에 포함된다


def test_usage_condense_call_failure_without_usage_counts_as_unmeasured():
    long_bullets = [{"text": f"장문 불릿 {i}번이며 설명이 길게 이어진다", "level": 0} for i in range(30)]
    over_payload = {"template": "bullet_box", "bullets": long_bullets, "conclusion": "성장", "footnote": ""}
    service, _ = _service([
        ProviderResponse(structured=over_payload, raw_text="r1", usage=_usage(input_tokens=100)),
        ProviderCallFailed("한도"),  # usage 없음: 결과 메시지 없이 끊긴 실패(ⓑ 유형)
    ])
    result = asyncio.run(service.generate_chapter(_deck(), "c1", SOURCES, Preset()))
    assert result.status == "ok"
    assert result.usage.calls == 2
    assert result.usage.unmeasured_calls == 1
    assert result.usage.failed_calls == 1
    assert result.usage.input_tokens == 100  # 나머지 호출 값만


def test_usage_manual_condense_format_retry_purposes():
    current = BulletBoxSlots(bullets=[{"text": "시장 규모 500억과 부연 설명", "level": 0}], conclusion="성장 지속")
    service, _ = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad", usage=_usage()),
        ProviderResponse(structured=SLOTS_PAYLOAD, raw_text="good", usage=_usage()),
    ])
    result = asyncio.run(service.condense_chapter(_deck(), "c1", current, SOURCES, Preset()))
    assert result.status == "ok"
    assert [r.purpose for r in result.usage.records] == ["condense", "format_retry"]


def test_usage_missing_field_when_one_call_lacks_it():
    service, _ = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad", usage=_usage(input_tokens=None)),
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="good", usage=_usage(input_tokens=20)),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.usage.input_tokens is None
    assert "input_tokens" in result.usage.missing


def test_usage_missing_cost_when_one_call_lacks_it():
    service, _ = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad", usage=_usage(cost_usd=None)),
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="good", usage=_usage(cost_usd=0.02)),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.usage.cost_usd is None
    assert "cost_usd" in result.usage.missing


def test_usage_sums_when_all_present():
    service, _ = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad",
                          usage=_usage(input_tokens=10, cost_usd=0.01)),
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="good",
                          usage=_usage(input_tokens=20, cost_usd=0.02)),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.usage.input_tokens == 30
    assert result.usage.cost_usd == pytest.approx(0.03)
    assert result.usage.missing == []


def test_usage_all_zero_cost_sums_to_zero_not_none():
    service, _ = _service([
        ProviderResponse(structured={"엉뚱": 1}, raw_text="bad", usage=_usage(cost_usd=0.0)),
        ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="good", usage=_usage(cost_usd=0.0)),
    ])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES))
    assert result.usage.cost_usd == 0.0
    assert "cost_usd" not in result.usage.missing


def test_on_usage_called_once_on_success():
    calls: list[UsageRecord] = []
    service, _ = _service([ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r", usage=_usage())])
    asyncio.run(service.generate_structure(_deck().meta, SOURCES, on_usage=calls.append))
    assert len(calls) == 1
    assert calls[0].outcome == "ok"
    assert calls[0].kind == "structure"
    assert calls[0].chapter_id is None


def test_on_usage_called_with_failed_outcome_on_exception():
    calls: list[UsageRecord] = []
    service, _ = _service([ProviderCallFailed("한도 소진")])
    with pytest.raises(ProviderCallFailed):
        asyncio.run(service.generate_structure(_deck().meta, SOURCES, on_usage=calls.append))
    assert len(calls) == 1
    assert calls[0].outcome == "failed"


def test_on_usage_callback_exception_does_not_break_result():
    def raising_cb(record):
        raise RuntimeError("콜백 실패")

    service, _ = _service([ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="r", usage=_usage())])
    result = asyncio.run(service.generate_structure(_deck().meta, SOURCES, on_usage=raising_cb))
    assert result.status == "ok"  # 콜백이 예외를 던져도 결과가 돌아온다


def test_on_usage_not_called_for_unknown_chapter():
    calls: list[UsageRecord] = []
    service, _ = _service([])
    with pytest.raises(ValueError):
        asyncio.run(service.generate_chapter(_deck(), "없는장", SOURCES, Preset(), on_usage=calls.append))
    assert calls == []  # 프로바이더 호출 전 ValueError는 on_usage를 부르지 않는다


def test_concurrent_generate_structure_isolates_usage():
    class TaggedProvider:
        async def complete(self, prompt, schema):
            await asyncio.sleep(0)  # 다른 코루틴에 양보해 인터리빙을 강제한다
            tokens = 111 if "TAG_A" in prompt else 222
            return ProviderResponse(
                structured=STRUCTURE_PAYLOAD, raw_text="r", usage=_usage(input_tokens=tokens)
            )

    service = GenerationService(TaggedProvider(), METRICS)
    records: dict[str, UsageRecord] = {}

    async def run():
        return await asyncio.gather(
            service.generate_structure(_deck().meta, SOURCES, instructions="TAG_A",
                                        on_usage=lambda r: records.__setitem__("A", r)),
            service.generate_structure(_deck().meta, SOURCES, instructions="TAG_B",
                                        on_usage=lambda r: records.__setitem__("B", r)),
        )

    result_a, result_b = asyncio.run(run())
    assert result_a.usage.calls == 1 and result_a.usage.input_tokens == 111
    assert result_b.usage.calls == 1 and result_b.usage.input_tokens == 222
    assert records["A"].summary.input_tokens == 111
    assert records["B"].summary.input_tokens == 222


def test_provider_complete_only_called_via_complete_helper():
    import slidecaptain.pipeline.service as service_module
    source = inspect.getsource(service_module)
    assert source.count("_provider.complete(") == 1  # 우회 방지: 유일한 경유지
    complete_source = inspect.getsource(GenerationService._complete)
    assert "_provider.complete(" in complete_source


def test_usage_record_json_has_no_prompt_or_slot_content():
    service, _ = _service(
        [ProviderResponse(structured=STRUCTURE_PAYLOAD, raw_text="원문 그대로", usage=_usage())]
    )
    captured: list[UsageRecord] = []
    asyncio.run(service.generate_structure(_deck().meta, SOURCES, on_usage=captured.append))
    dumped = captured[0].model_dump_json()
    assert "시장 규모는 500억 원이다" not in dumped  # 자료 문장
    assert "원문 그대로" not in dumped  # raw_text
    assert "표지" not in dumped  # 구조안 텍스트 조각
