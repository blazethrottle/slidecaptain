"""Conservative whole-field linkage to Q2c computations, with no AI or writes.

Arbitrary prose and original source values remain unreviewed. An exact match
checks an explicit numerical expression, not the truth of extracted metadata.
"""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterator

from slidecaptain.models.deck import Chapter, Deck
from slidecaptain.models.numeric_review import NumericExpression, NumericReviewItem, NumericReviewReport
from slidecaptain.models.report_purpose import output_dump
from slidecaptain.models.story import StoryPlan


def chapter_numeric_expressions(plan: StoryPlan | None, chapter: Chapter) -> list[NumericExpression]:
    if plan is None or chapter.template in ("cover", "divider"):
        return []
    assignment = next((ch for ch in plan.chapters if ch.chapter_id == chapter.id), None)
    if assignment is None:
        return []
    claim_ids = set(assignment.claim_ids) | set(plan.answer_claim_ids)
    comparisons = {c.id: c for c in plan.comparisons if c.claim_id in claim_ids}
    evidence = {e.id: e for e in plan.evidence}
    values = {v.derivation_id: v for v in plan.derived_values if v.status == "computed"}
    expressions = []
    for derivation in plan.derivations:
        comparison, value = comparisons.get(derivation.comparison_id), values.get(derivation.id)
        if comparison is None or value is None or value.value is None or value.unit is None:
            continue
        left, right = evidence[comparison.left_evidence_id], evidence[comparison.right_evidence_id]
        a, b = left.metric_basis, right.metric_basis
        if a is None or b is None or a.period is None or b.period is None or a.denominator is None:
            continue
        target_period = f"{a.period.start.isoformat()}~{a.period.end.isoformat()}"
        baseline_period = f"{b.period.start.isoformat()}~{b.period.end.isoformat()}"
        label = "차이" if derivation.operation == "difference" else "증감률"
        signed = value.value if value.value.startswith("-") or value.value == "0" else "+" + value.value
        qualifier = []
        if comparison.axis == "entity":
            prefix = f"{a.entity} {a.definition}: {b.entity} 대비"
            qualifier.append(target_period)
        else:
            prefix = f"{a.entity} {a.definition}: {target_period}, {baseline_period} 대비"
        if a.denominator.kind == "population":
            qualifier.append(f"분모: {a.denominator.definition}")
        if value.rounded:
            qualifier.append("소수 최대 6자리 반올림")
        text = f"{prefix} {label} {signed}{value.unit}"
        if qualifier:
            text += f" ({', '.join(qualifier)})"
        expressions.append(NumericExpression(
            chapter_id=chapter.id, derivation_id=derivation.id, claim_id=comparison.claim_id,
            target_evidence_id=left.id, baseline_evidence_id=right.id,
            source_ids=list(dict.fromkeys((left.source_id, right.source_id))),
            formula=value.formula, text=text,
        ))
    return expressions


def _strings(value: object, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        if re.search(r"\d", value):
            yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _strings(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _strings(child, f"{path}/{index}")


def numeric_fields(deck: Deck) -> Iterator[tuple[str, str, str]]:
    chapters = {c.id: c for c in deck.structure.chapters}
    for slide in deck.slides:
        chapter = chapters[slide.chapter_id]
        excluded = {"template", "tone"}
        if chapter.template == "cover":
            excluded.add("date")
        if chapter.template == "divider":
            excluded.add("section_no")
        if slide.chart is not None:
            # 차트가 있는 장은 표를 그리지 않는다(엔진이 표 자리를 차트로 바꾸고, 그릴 수 없으면 표로 대체하지 않고 실패한다).
            # 차트 값은 등록 비교의 근거에서 오므로 원문과 이미 연결돼 있다. 보이는 칸만 대조한다(도식 장과 같은 원칙,
            # 회사 PC 이월표 (14): 표의 원문 수치 칸이 unlinked_expression으로 세어졌다). 각주는 계속 본다
            excluded |= {"columns", "rows"}
        if slide.slots.template == "diagram":
            # 보이는 문구만 대조한다. 버전/ID/근거 참조는 보고서 숫자가 아니다.
            diagram = slide.slots.diagram
            fields = list(_strings(slide.slots.footnote, "/slots/footnote"))
            for index, node in enumerate(diagram.nodes):
                fields.extend(_strings(node.content, f"/slots/diagram/nodes/{index}/content"))
                fields.extend(_strings(node.caveats, f"/slots/diagram/nodes/{index}/caveats"))
            for index, edge in enumerate(diagram.edges):
                fields.extend(_strings(edge.label, f"/slots/diagram/edges/{index}/label"))
        else:
            fields = list(_strings(slide.slots.model_dump(exclude=excluded), "/slots"))
        fields.extend(_strings(slide.eyebrow, "/eyebrow"))
        fields.extend(_strings(slide.subtitle, "/subtitle"))
        if chapter.template not in ("cover", "divider"):
            fields.extend(_strings(chapter.topic, "/topic"))
        for path, text in fields:
            yield chapter.id, path, text


def assess_numeric_review(deck: Deck, sources: dict[str, str]) -> NumericReviewReport:
    # Avoid trusting a previously loaded or in-memory edited computed result.
    # Revalidation also leaves the caller's draft untouched.
    deck = Deck.model_validate(deck.model_dump(mode="json"))
    from slidecaptain.pipeline.story import StaleStoryPlan, require_current_story

    basis = {
        "rule_version": "q2d-v1", "deck": output_dump(deck),  # 보고 목적 칸을 뺀다 (D3b-2)
        "sources": {key: hashlib.sha256(text.encode("utf-8")).hexdigest() for key, text in sources.items()},
    }
    if any(slide.chart is not None for slide in deck.slides):
        # 검사할 칸을 고르는 규칙의 표지. 2026-10-20 차트 장의 표 칸을 뺐다(회사 PC 이월표 (14)). 규칙이 바뀌기 전에 저장된
        # 검토 결과가 같은 지문으로 현재 결과처럼 읽히지 않게 한다. 차트가 없는 덱은 검사 칸이 그대로이므로 지문도 그대로 둔다
        basis["field_rule"] = "visible-2026-10-20"
    fingerprint = hashlib.sha256(json.dumps(
        basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    fields = list(numeric_fields(deck))
    plan = deck.structure.story_plan
    reason = None
    if plan is None:
        reason = "missing_plan"
    else:
        try:
            require_current_story(deck, sources)
        except StaleStoryPlan:
            reason = "stale_plan"
        if reason is None:
            for evidence in plan.evidence:
                source = sources.get(evidence.source_id)
                lines = source.splitlines() if source is not None else []
                if (source is None or evidence.locator.line_end > len(lines)
                    or evidence.source_revision != hashlib.sha256(source.encode("utf-8")).hexdigest()
                    or evidence.excerpt != "\n".join(lines[evidence.locator.line_start - 1:evidence.locator.line_end])):
                    reason = "evidence_mismatch"
                    break
    expressions = [] if reason else [
        expression for ch in deck.structure.chapters
        for expression in chapter_numeric_expressions(plan, ch)
    ]
    if reason is None and not fields:
        reason = "no_numeric_fields"
    elif reason is None and not expressions:
        reason = "no_computed_expressions"
    if reason:
        return NumericReviewReport(
            status="not_run", reason=reason, input_fingerprint=fingerprint,
            numeric_fields=len(fields), evaluated=0, matched=0, unresolved=len(fields),
            expressions=expressions, items=[],
        )
    lookup: dict[tuple[str, str], list[NumericExpression]] = defaultdict(list)
    for expression in expressions:
        lookup[(expression.chapter_id, expression.text)].append(expression)
    items = []
    for chapter_id, path, text in fields:
        candidates = lookup.get((chapter_id, text), [])
        if len(candidates) == 1:
            code, message = "matched", "대상과 기준, 부호, 단위, 기간, 분모와 반올림을 포함한 계산 문구가 일치합니다."
        elif candidates:
            code, message = "ambiguous_expression", "같은 문구에 여러 산식이 대응해 근거 연결을 확정할 수 없습니다."
        else:
            code, message = "unlinked_expression", "연결 가능한 계산 문구와 다릅니다. 원문 수치, 다른 표현 또는 비교 조건을 직접 확인해 주세요."
        items.append(NumericReviewItem(
            chapter_id=chapter_id, path=path, actual=text, code=code, message=message,
            derivation_id=candidates[0].derivation_id if len(candidates) == 1 else None,
        ))
    matched = sum(item.code == "matched" for item in items)
    return NumericReviewReport(
        status="matched" if matched == len(items) else "needs_review",
        input_fingerprint=fingerprint, numeric_fields=len(fields), evaluated=len(items),
        matched=matched, unresolved=len(items) - matched, expressions=expressions, items=items,
    )
