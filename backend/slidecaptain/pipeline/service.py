"""생성 서비스: 프롬프트 조립 → 프로바이더 호출 → 검증 게이트 (설계서 4).

게이트는 코드가 수행하며 호출마다 자동이다 (설계서 4.2):
1. 형식: 응답을 스키마로 검증. 실패 시 1회 재시도, 재실패 시 원문을 담아 반환 (수동 처리 경로)
2. 분량: 레이아웃 실측 경고 확인. 초과 시 1회 축약 재생성 (해소 사다리 1단계, 장별 생성만)
3. 수치: 생성 문장의 숫자를 자료 원문 전체와 대조. 없는 숫자는 경고 목록 (차단 아님)
"""

from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError

from slidecaptain.layout.templates import build_slide
from slidecaptain.metrics.capacity import capacity_contract, hangul_chars_per_line
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
from slidecaptain.pipeline.provider import AIProvider, ProviderError, ProviderResponse

_SLOTS_ADAPTER: TypeAdapter = TypeAdapter(Slots)

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


class StructureResult(BaseModel):
    status: Literal["ok", "format_error"]
    structure: Structure | None = None
    raw_text: str = ""
    unverified_numbers: list[str] = []
    format_retried: bool = False


class ChapterResult(BaseModel):
    status: Literal["ok", "format_error"]
    slots: Slots | None = None
    raw_text: str = ""
    warnings: list[CapacityWarning] = []
    unverified_numbers: list[str] = []
    format_retried: bool = False
    condensed: bool = False


def _try_parse(parse: Callable[[Any], Any], response: ProviderResponse) -> Any | None:
    if response.structured is None:
        return None
    try:
        return parse(normalize_payload(response.structured))
    except (ValidationError, KeyError, TypeError, ValueError):
        return None


class GenerationService:
    def __init__(self, provider: AIProvider, metrics: FontMetrics) -> None:
        self.provider = provider
        self.metrics = metrics

    async def _call_with_format_gate(
        self, prompt: str, schema: dict, parse: Callable[[Any], Any]
    ) -> tuple[Any | None, str, bool]:
        """게이트 1 (형식): 실패 시 1회 재시도. (parsed, raw_text, retried)를 돌려준다."""
        response = await self.provider.complete(prompt, schema)
        parsed = _try_parse(parse, response)
        if parsed is not None:
            return parsed, response.raw_text, False
        retry = await self.provider.complete(
            build_format_retry_prompt(prompt, response.raw_text), schema
        )
        return _try_parse(parse, retry), retry.raw_text, True

    async def generate_structure(
        self,
        meta: DeckMeta,
        sources: dict[str, str],
        target_chapters: int | None = None,
        instructions: str = "",
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

        structure, raw, retried = await self._call_with_format_gate(
            prompt, structure_response_schema(), parse
        )
        if structure is None:
            return StructureResult(status="format_error", raw_text=raw, format_retried=retried)
        texts = [t for ch in structure.chapters for t in (ch.topic, ch.conclusion)]
        return StructureResult(
            status="ok",
            structure=structure,
            raw_text=raw,
            unverified_numbers=find_unverified_numbers(texts, list(sources.values()) + [meta.title]),
            format_retried=retried,
        )

    async def generate_chapter(
        self,
        deck: Deck,
        chapter_id: str,
        sources: dict[str, str],
        preset: Preset,
        instructions: str = "",
    ) -> ChapterResult:
        chapter = self._find_chapter(deck, chapter_id)
        prompt = self._chapter_prompt(deck, chapter, sources, preset, instructions)
        schema = chapter_response_schema(chapter.template)
        parse = self._slots_parser(chapter)

        slots, raw, retried = await self._call_with_format_gate(prompt, schema, parse)
        if slots is None:
            return ChapterResult(status="format_error", raw_text=raw, format_retried=retried)

        warnings = self._measure(chapter, slots, preset)
        condensed = False
        fixable = _fixable(warnings)
        if fixable:  # 게이트 2 (분량): 1회 축약 재생성. 직전 초안을 동봉한다 (설계 결정 12)
            try:
                condense_response = await self.provider.complete(
                    build_condense_prompt(prompt, fixable, slots.model_dump_json()), schema
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

        return self._chapter_result(deck, chapter, slots, raw, warnings, sources, retried, condensed)

    async def condense_chapter(
        self,
        deck: Deck,
        chapter_id: str,
        current_slots: Any,
        sources: dict[str, str],
        preset: Preset,
        instructions: str = "",
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
        slots, raw, retried = await self._call_with_format_gate(
            prompt, chapter_response_schema(chapter.template), self._slots_parser(chapter)
        )
        if slots is None:
            return ChapterResult(status="format_error", raw_text=raw, format_retried=retried)
        warnings = self._measure(chapter, slots, preset)
        return self._chapter_result(
            deck, chapter, slots, raw, warnings, sources, retried, condensed=True
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
            chars_per_line=hangul_chars_per_line(preset, self.metrics.face(False)),
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
        )

    def _measure(self, chapter: Chapter, slots: Any, preset: Preset) -> list[CapacityWarning]:
        return build_slide(chapter, slots, 1, preset, self.metrics).warnings
