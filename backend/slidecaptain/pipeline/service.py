"""생성 서비스: 프롬프트 조립 → 프로바이더 호출 → 검증 게이트 (설계서 4).

게이트는 코드가 수행하며 호출마다 자동이다 (설계서 4.2):
1. 형식: 응답을 스키마로 검증. 실패 시 1회 재시도, 재실패 시 원문을 담아 반환 (수동 처리 경로)
2. 분량: 레이아웃 실측 경고 확인. 초과 시 1회 축약 재생성 (해소 사다리 1단계, 장별 생성만)
3. 수치: 생성 문장의 숫자를 자료 원문 전체와 대조. 없는 숫자는 경고 목록 (차단 아님)
"""

import logging
from datetime import date, datetime
from typing import Any, Callable, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError

from slidecaptain.layout.templates import build_slide
from slidecaptain.metrics.capacity import capacity_contract, char_hints
from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Chapter, Deck, DeckMeta, Slots, Structure
from slidecaptain.models.preset import Preset
from slidecaptain.models.render import CapacityWarning
from slidecaptain.pipeline.normalize import collect_strings, normalize_payload
from slidecaptain.pipeline.numbers import find_unverified_numbers
from slidecaptain.pipeline.prompts import (
    build_chapter_prompt,
    build_condense_prompt,
    build_format_retry_prompt,
    build_structure_prompt,
    chapter_response_schema,
    structure_response_schema,
)
from slidecaptain.pipeline.provider import AIProvider, CallUsage, ProviderError, ProviderResponse

_LOG = logging.getLogger("slidecaptain.pipeline.service")

_SLOTS_ADAPTER: TypeAdapter = TypeAdapter(Slots)

# 원시 호출 1건의 목적 (단계 5A 묶음 C 가정 2). 형식 게이트의 재시도는 항상 format_retry다
_CallPurpose = Literal["generate", "format_retry", "condense"]

# 합계 대상 수치 필드 이름 (GenerationUsage와 CallUsage에 공통. 가정 3)
_USAGE_NUMERIC_FIELDS: tuple[str, ...] = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
    "duration_ms", "duration_api_ms", "cost_usd",
)

# 자료에 있을 이유가 없는 메타성 필드: 수치 대조 수집에서 제외한다 (설계 결정 6)
_NUMBER_EXEMPT_FIELDS: dict[str, set[str]] = {
    "cover": {"date"},
    "divider": {"section_no"},
}


def _fixable(warnings: list[CapacityWarning]) -> list[CapacityWarning]:
    """축약 재생성으로 고칠 수 있는 경고만 남긴다 (설계 결정 5).

    title 경고는 구조안의 topic에서 오므로 슬롯 재생성으로는 해소되지 않는다.
    """
    return [w for w in warnings if w.slot != "title"]


class CallUsageRecord(BaseModel):
    """원시 호출 1건의 목적과 성패, 사용량 (단계 5A 묶음 C 태스크 C2, 가정 2와 3)."""

    purpose: _CallPurpose
    ok: bool
    usage: CallUsage | None


class GenerationUsage(BaseModel):
    """생성 작업 1건(서비스 공개 메서드 1회 호출) 안의 모든 호출을 합산한 값 (가정 3).

    없는 값은 만들지 않는다: 합산에 참여한 호출 중 하나라도 어떤 필드가 없으면
    그 필드의 합계는 None이고 missing에 이름이 실린다(부분 합계는 과소 집계라 더 해롭다).
    사용량 자체가 없는 호출(usage=None. 결과 메시지 없이 끊긴 실패)은 unmeasured_calls로
    따로 세고 합산에서는 제외한다(있는 필드까지 None으로 만들지 않는다).
    """

    calls: int
    failed_calls: int
    unmeasured_calls: int
    models: list[str]
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    duration_ms: int | None
    duration_api_ms: int | None
    cost_usd: float | None
    missing: list[str]
    records: list[CallUsageRecord]


class UsageRecord(BaseModel):
    """로컬 기록 1줄에 실릴 값 (태스크 C3에서 ai-usage.jsonl에 append). 내용은 담지 않는다(가정 4)."""

    ts: str
    kind: Literal["structure", "chapter", "condense"]
    chapter_id: str | None
    outcome: Literal["ok", "format_error", "failed"]
    requested_model: str | None
    summary: GenerationUsage


class _UsageCollector:
    """생성 작업 1건 동안의 호출을 쌓는 요청별 지역 변수 (가정 5, 우회 방지: self에 두지 않는다)."""

    def __init__(self) -> None:
        self._records: list[CallUsageRecord] = []

    def record(self, purpose: _CallPurpose, usage: CallUsage | None, ok: bool) -> None:
        self._records.append(CallUsageRecord(purpose=purpose, ok=ok, usage=usage))

    def summary(self) -> GenerationUsage:
        records = self._records
        measured = [r.usage for r in records if r.usage is not None]
        failed_calls = sum(1 for r in records if not r.ok)
        unmeasured_calls = len(records) - len(measured)
        models = list(dict.fromkeys(u.model for u in measured if u.model))

        missing: list[str] = []

        def _sum(name: str) -> int | float | None:
            values = [getattr(u, name) for u in measured]
            # 전부 미측정이면 missing은 비고 unmeasured_calls가 그것을 나타낸다 (C-4)
            if not values or any(v is None for v in values):
                if values:  # 값이 있는 호출이 하나라도 있는데 다른 하나는 없을 때만 missing이다
                    missing.append(name)
                return None
            return sum(values)

        sums = {name: _sum(name) for name in _USAGE_NUMERIC_FIELDS}

        return GenerationUsage(
            calls=len(records),
            failed_calls=failed_calls,
            unmeasured_calls=unmeasured_calls,
            models=models,
            input_tokens=sums["input_tokens"],
            output_tokens=sums["output_tokens"],
            cache_read_tokens=sums["cache_read_tokens"],
            cache_creation_tokens=sums["cache_creation_tokens"],
            duration_ms=sums["duration_ms"],
            duration_api_ms=sums["duration_api_ms"],
            cost_usd=sums["cost_usd"],
            missing=missing,
            records=records,
        )


class StructureResult(BaseModel):
    status: Literal["ok", "format_error"]
    structure: Structure | None = None
    raw_text: str = ""
    unverified_numbers: list[str] = []
    format_retried: bool = False
    usage: GenerationUsage


class ChapterResult(BaseModel):
    status: Literal["ok", "format_error"]
    slots: Slots | None = None
    raw_text: str = ""
    warnings: list[CapacityWarning] = []
    unverified_numbers: list[str] = []
    format_retried: bool = False
    condensed: bool = False
    usage: GenerationUsage


def _try_parse(parse: Callable[[Any], Any], response: ProviderResponse) -> Any | None:
    if response.structured is None:
        return None
    try:
        return parse(normalize_payload(response.structured))
    except (ValidationError, KeyError, TypeError, ValueError):
        return None


class GenerationService:
    def __init__(
        self,
        provider: AIProvider,
        metrics: FontMetrics,
        requested_model: str | None = None,
    ) -> None:
        self._provider = provider
        self.metrics = metrics
        self._requested_model = requested_model

    async def _complete(
        self, prompt: str, schema: dict, purpose: _CallPurpose, collector: _UsageCollector
    ) -> ProviderResponse:
        """프로바이더 호출의 유일한 경유지 (가정 5, 우회 방지).

        성공은 response.usage를, ProviderError는 e.usage를 ok=False로 기록한 뒤 재발생한다.
        """
        try:
            response = await self._provider.complete(prompt, schema)
        except ProviderError as e:
            collector.record(purpose, e.usage, ok=False)
            raise
        collector.record(purpose, response.usage, ok=True)
        return response

    async def _call_with_format_gate(
        self,
        prompt: str,
        schema: dict,
        parse: Callable[[Any], Any],
        purpose: _CallPurpose,
        collector: _UsageCollector,
    ) -> tuple[Any | None, str, bool]:
        """게이트 1 (형식): 실패 시 1회 재시도. (parsed, raw_text, retried)를 돌려준다."""
        response = await self._complete(prompt, schema, purpose, collector)
        parsed = _try_parse(parse, response)
        if parsed is not None:
            return parsed, response.raw_text, False
        retry = await self._complete(
            build_format_retry_prompt(prompt, response.raw_text), schema, "format_retry", collector
        )
        return _try_parse(parse, retry), retry.raw_text, True

    def _emit_usage(
        self,
        on_usage: Callable[[UsageRecord], None] | None,
        kind: Literal["structure", "chapter", "condense"],
        chapter_id: str | None,
        outcome: Literal["ok", "format_error", "failed"],
        summary: GenerationUsage,
    ) -> None:
        """호출자가 이미 계산한 summary를 그대로 싣는다 (C-3: 반환값과 같은 객체를 재사용해 중복 계산을 없앤다)."""
        if on_usage is None:
            return
        record = UsageRecord(
            ts=datetime.now().astimezone().isoformat(timespec="seconds"),
            kind=kind,
            chapter_id=chapter_id,
            outcome=outcome,
            requested_model=self._requested_model,
            summary=summary,
        )
        try:
            on_usage(record)
        except Exception:
            _LOG.warning("사용량 콜백(on_usage) 실행 중 오류", exc_info=True)

    async def generate_structure(
        self,
        meta: DeckMeta,
        sources: dict[str, str],
        target_chapters: int | None = None,
        instructions: str = "",
        on_usage: Callable[[UsageRecord], None] | None = None,
    ) -> StructureResult:
        prompt = build_structure_prompt(meta, sources, target_chapters, instructions)

        def parse(payload: Any) -> Structure:
            chapters = [
                Chapter(
                    id=f"c{i}",  # id는 서버가 부여한다 (설계 결정 10)
                    topic=ch["topic"],
                    conclusion=ch["conclusion"],
                    template=ch["template"],
                    source_refs=[r for r in ch["source_refs"] if r in sources],
                )
                for i, ch in enumerate(payload["chapters"], start=1)
            ]
            return Structure(chapters=chapters)

        collector = _UsageCollector()
        outcome: Literal["ok", "format_error", "failed"] = "failed"
        summary: GenerationUsage | None = None
        try:
            structure, raw, retried = await self._call_with_format_gate(
                prompt, structure_response_schema(), parse, "generate", collector
            )
            summary = collector.summary()  # C-3: 한 번만 계산해 반환값과 _emit_usage에 같은 객체를 넘긴다
            if structure is None:
                outcome = "format_error"
                return StructureResult(
                    status="format_error", raw_text=raw, format_retried=retried,
                    usage=summary,
                )
            texts = [t for ch in structure.chapters for t in (ch.topic, ch.conclusion)]
            outcome = "ok"
            return StructureResult(
                status="ok",
                structure=structure,
                raw_text=raw,
                unverified_numbers=find_unverified_numbers(
                    texts, list(sources.values()) + [meta.title]
                ),
                format_retried=retried,
                usage=summary,
            )
        finally:
            self._emit_usage(
                on_usage, "structure", None, outcome, summary if summary is not None else collector.summary()
            )

    async def generate_chapter(
        self,
        deck: Deck,
        chapter_id: str,
        sources: dict[str, str],
        preset: Preset,
        instructions: str = "",
        on_usage: Callable[[UsageRecord], None] | None = None,
    ) -> ChapterResult:
        chapter = self._find_chapter(deck, chapter_id)
        prompt = self._chapter_prompt(deck, chapter, sources, preset, instructions)
        schema = chapter_response_schema(chapter.template)
        parse = self._slots_parser(chapter)

        collector = _UsageCollector()
        outcome: Literal["ok", "format_error", "failed"] = "failed"
        summary: GenerationUsage | None = None
        try:
            slots, raw, retried = await self._call_with_format_gate(
                prompt, schema, parse, "generate", collector
            )
            if slots is None:
                outcome = "format_error"
                summary = collector.summary()
                return ChapterResult(
                    status="format_error", raw_text=raw, format_retried=retried,
                    usage=summary,
                )

            warnings = self._measure(chapter, slots, preset)
            condensed = False
            fixable = _fixable(warnings)
            if fixable:  # 게이트 2 (분량): 1회 축약 재생성. 직전 초안을 동봉한다 (설계 결정 12)
                try:
                    condense_response = await self._complete(
                        build_condense_prompt(prompt, fixable, slots.model_dump_json()),
                        schema, "condense", collector,
                    )
                except ProviderError:
                    condense_response = None  # 축약 호출 실패로 유효한 초안을 잃지 않는다
                if condense_response is not None:
                    condensed_slots = _try_parse(parse, condense_response)
                    if condensed_slots is not None:
                        slots = condensed_slots
                        raw = condense_response.raw_text
                        warnings = self._measure(chapter, slots, preset)
                        condensed = True

            outcome = "ok"
            summary = collector.summary()  # C-3: 한 번만 계산해 반환값과 _emit_usage에 같은 객체를 넘긴다
            return self._chapter_result(
                deck, chapter, slots, raw, warnings, sources, retried, condensed, summary
            )
        finally:
            self._emit_usage(
                on_usage, "chapter", chapter_id, outcome, summary if summary is not None else collector.summary()
            )

    async def condense_chapter(
        self,
        deck: Deck,
        chapter_id: str,
        current_slots: Any,
        sources: dict[str, str],
        preset: Preset,
        instructions: str = "",
        on_usage: Callable[[UsageRecord], None] | None = None,
    ) -> ChapterResult:
        """수동 축약 (설계 결정 13): 현재 슬롯을 초안으로 받아 1회 축약한다.

        이 호출 자체가 축약이므로 추가 축약 재시도는 없다. 형식과 수치 게이트는 동일하게 걸린다.
        """
        chapter = self._find_chapter(deck, chapter_id)
        if current_slots.template != chapter.template:
            raise ValueError(
                f"장 {chapter_id}의 템플릿({chapter.template})과 보낸 슬롯의 "
                f"템플릿({current_slots.template})이 다릅니다"
            )
        base = self._chapter_prompt(deck, chapter, sources, preset, instructions)
        warnings_now = _fixable(self._measure(chapter, current_slots, preset))
        prompt = build_condense_prompt(base, warnings_now, current_slots.model_dump_json())

        collector = _UsageCollector()
        outcome: Literal["ok", "format_error", "failed"] = "failed"
        summary: GenerationUsage | None = None
        try:
            slots, raw, retried = await self._call_with_format_gate(
                prompt, chapter_response_schema(chapter.template), self._slots_parser(chapter),
                "condense", collector,
            )
            if slots is None:
                outcome = "format_error"
                summary = collector.summary()
                return ChapterResult(
                    status="format_error", raw_text=raw, format_retried=retried,
                    usage=summary,
                )
            warnings = self._measure(chapter, slots, preset)
            outcome = "ok"
            summary = collector.summary()  # C-3: 한 번만 계산해 반환값과 _emit_usage에 같은 객체를 넘긴다
            return self._chapter_result(
                deck, chapter, slots, raw, warnings, sources, retried, condensed=True,
                usage=summary,
            )
        finally:
            self._emit_usage(
                on_usage, "condense", chapter_id, outcome, summary if summary is not None else collector.summary()
            )

    # -- 내부 공통 ---------------------------------------------------------

    def _find_chapter(self, deck: Deck, chapter_id: str) -> Chapter:
        chapter = next((ch for ch in deck.structure.chapters if ch.id == chapter_id), None)
        if chapter is None:
            raise ValueError(f"구조안에 없는 장입니다: {chapter_id}")
        return chapter

    def _chapter_prompt(
        self, deck: Deck, chapter: Chapter, sources: dict[str, str], preset: Preset, instructions: str
    ) -> str:
        # 프롬프트에는 근거로 매핑된 자료만 넣되, 매핑이 비면 전체로 폴백한다 (설계 결정 11).
        # cover와 divider의 자료 생략은 build_chapter_prompt가 처리한다
        chapter_sources = {n: sources[n] for n in chapter.source_refs if n in sources} or sources
        return build_chapter_prompt(
            deck,
            chapter,
            chapter_sources,
            capacity_contract(chapter.template, preset),
            today=date.today().isoformat(),
            instructions=instructions,
            char_hints=char_hints(chapter.template, preset, self.metrics),
        )

    def _slots_parser(self, chapter: Chapter) -> Callable[[Any], Any]:
        def parse(payload: Any) -> Any:
            # AI가 template 판별자를 잘못 채워도 장의 템플릿으로 강제한다
            return _SLOTS_ADAPTER.validate_python({**payload, "template": chapter.template})

        return parse

    def _chapter_result(
        self,
        deck: Deck,
        chapter: Chapter,
        slots: Any,
        raw: str,
        warnings: list[CapacityWarning],
        sources: dict[str, str],
        retried: bool,
        condensed: bool,
        usage: GenerationUsage,
    ) -> ChapterResult:
        exempt = _NUMBER_EXEMPT_FIELDS.get(chapter.template, set())
        texts = collect_strings(slots.model_dump(exclude=exempt))
        return ChapterResult(
            status="ok",
            slots=slots,
            raw_text=raw,
            warnings=warnings,
            unverified_numbers=find_unverified_numbers(
                texts, list(sources.values()) + [deck.meta.title]
            ),
            format_retried=retried,
            condensed=condensed,
            usage=usage,
        )

    def _measure(self, chapter: Chapter, slots: Any, preset: Preset) -> list[CapacityWarning]:
        return build_slide(chapter, slots, 1, preset, self.metrics).warnings
