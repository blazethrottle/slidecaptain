import type { Deck } from "../api/client";

export function storyDeck(): Deck {
  return {
    schema_version: 1,
    meta: { title: "합성 보고", report_type: "approval", audience: "검토 담당자", presenter: "", preset_overrides: {} },
    slides: [],
    structure: {
      chapters: [{ id: "c1", topic: "조건부 판단", conclusion: "비용 확인 후 판단", template: "summary", source_refs: ["합성.md"] }],
      story_plan: {
        version: "q2a-v1", input_fingerprint: "a".repeat(64),
        brief: { decision_question: "운영을 확대할 것인가?", audience: "검토 담당자", report_type: "approval", reading_profile: "미지정", constraints: [] },
        evidence: [{ id: "e1", source_id: "합성.md", source_revision: "b".repeat(64),
          locator: { line_start: 2, line_end: 2 }, excerpt: "확대 비용 미확인", value: null, unit: null, period: null, entity: null, denominator: null }],
        claims: [{ id: "k1", statement: "비용 확인 후 확대 여부를 판단한다", kind: "proposal", evidence_ids: ["e1"], caveats: ["비용은 미확인"] }],
        answer_claim_ids: ["k1"], chapters: [{ chapter_id: "c1", role: "answer", claim_ids: ["k1"] }],
        unanswered_questions: ["확대 비용은 얼마인가?"],
        comparisons: [], comparison_results: [],
        derivations: [], derived_values: [],
      },
    },
  };
}

export function comparisonDeck(): Deck {
  const deck = storyDeck();
  const plan = deck.structure.story_plan!;
  plan.version = "q2b-v1";
  const basis = {
    definition: "순매출", unit: "원", entity: "A팀",
    period: { start: "2026-01-01", end: "2026-01-31", grain: "month" as const, aggregation: "sum" as const, coverage: "complete" as const },
    denominator: { kind: "none" as const, definition: null },
  };
  plan.evidence = [
    { ...plan.evidence[0], value: "100", excerpt: "A팀 1월 순매출 100원", metric_basis: basis },
    { ...plan.evidence[0], id: "e2", source_id: "두번째.md", value: "100", excerpt: "B팀 1월 순매출 100천원",
      metric_basis: { ...basis, unit: "천원", entity: "B팀" } },
  ];
  plan.claims[0].evidence_ids = ["e1", "e2"];
  plan.comparisons = [{ id: "cmp1", claim_id: "k1", left_evidence_id: "e1", right_evidence_id: "e2", axis: "entity" }];
  plan.comparison_results = [{ comparison_id: "cmp1", rule_version: "q2b-v1", status: "incompatible",
    reasons: [{ code: "unit_mismatch", field: "unit", evidence_id: null, message: "두 근거의 단위가 다릅니다." }] }];
  deck.structure.chapters[0].source_refs = ["합성.md", "두번째.md"];
  return deck;
}

export function derivedDeck(): Deck {
  const deck = comparisonDeck();
  const plan = deck.structure.story_plan!;
  plan.version = "q2c-v1";
  plan.derivations = [{ id: "d1", comparison_id: "cmp1", operation: "difference" }];
  plan.derived_values = [{ derivation_id: "d1", rule_version: "q2c-v1", status: "blocked", formula: "대상값 - 기준값",
    value: null, unit: null, rounded: null,
    reasons: [{ code: "comparison_blocked", evidence_id: null, message: "비교 조건이 일치하지 않습니다." }] }];
  return deck;
}
