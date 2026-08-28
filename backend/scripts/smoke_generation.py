"""실호출 스모크: 구독 프로바이더로 구조안과 장 하나를 실제 생성해 본다.

pytest 대상이 아니다 (실호출은 구독 사용량을 쓴다). 수동 실행:
  backend 폴더에서 .venv/Scripts/python.exe scripts/smoke_generation.py
"""

import asyncio
import json

from slidecaptain.metrics.font_metrics import FontMetrics
from slidecaptain.models.deck import Deck, DeckMeta, Structure
from slidecaptain.models.preset import Preset
from slidecaptain.pipeline.service import GenerationService
from slidecaptain.pipeline.subscription import SubscriptionProvider

SOURCES = {
    "리서치.md": (
        "국내 구독형 콘텐츠 시장 규모는 2025년 1조 2,000억 원으로 추정된다. "
        "연평균 성장률은 14.5%다. 주요 사업자는 3곳이며 상위 사업자 점유율은 62%다."
    )
}


async def main() -> None:
    service = GenerationService(SubscriptionProvider(), FontMetrics.load_default())
    meta = DeckMeta(title="구독 시장 검토", report_type="research", audience="경영진")

    print("== 구조안 생성 ==")
    structure_result = await service.generate_structure(meta, SOURCES, target_chapters=4)
    print("status:", structure_result.status, "/ 재시도:", structure_result.format_retried)
    print("근거 없는 수치:", structure_result.unverified_numbers)
    if structure_result.status != "ok":
        print("원문:", structure_result.raw_text[:500])
        return
    for ch in structure_result.structure.chapters:
        print(f"  [{ch.id}] {ch.topic} ({ch.template}) refs={ch.source_refs}")

    body_chapter = next(
        (ch for ch in structure_result.structure.chapters if ch.template not in ("cover", "divider")),
        None,
    )
    if body_chapter is None:
        print("본문 장이 없어 장별 생성을 건너뜁니다 (구조안이 표지와 간지뿐입니다).")
        return
    deck = Deck(meta=meta, structure=Structure(chapters=structure_result.structure.chapters))

    print(f"== 장별 생성: [{body_chapter.id}] {body_chapter.topic} ==")
    chapter_result = await service.generate_chapter(deck, body_chapter.id, SOURCES, Preset())
    print("status:", chapter_result.status, "/ 축약:", chapter_result.condensed)
    print("분량 경고:", [w.slot for w in chapter_result.warnings])
    print("근거 없는 수치:", chapter_result.unverified_numbers)
    if chapter_result.slots is not None:
        print(json.dumps(chapter_result.slots.model_dump(), ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    asyncio.run(main())
