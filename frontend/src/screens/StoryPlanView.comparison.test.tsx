import { render, screen, within } from "@testing-library/react";
import type { StoryPlan } from "../api/client";
import { comparisonDeck, storyDeck } from "../test/story";
import { StoryPlanView } from "./StoryPlanView";

function compared(status: "compatible" | "incompatible" | "insufficient_metadata"): StoryPlan {
  const plan = storyDeck().structure.story_plan!;
  return {
    ...plan, version: "q2b-v1",
    evidence: [plan.evidence[0], { ...plan.evidence[0], id: "e2", source_id: "두번째.md" }],
    comparisons: [{ id: "cmp1", claim_id: "k1", left_evidence_id: "e1", right_evidence_id: "e2", axis: "entity" }],
    comparison_results: [{ comparison_id: "cmp1", rule_version: "q2b-v1", status, reasons: status === "compatible" ? [] : [{
      code: status === "incompatible" ? "unit_mismatch" : "missing_metadata", field: "unit",
      evidence_id: status === "incompatible" ? null : "e2",
      message: status === "incompatible" ? "두 근거의 단위가 다릅니다." : "단위 정보가 없습니다.",
    }] }],
  };
}

it.each([
  ["incompatible", "비교 불가", "두 근거의 단위가 다릅니다."],
  ["insufficient_metadata", "정보 부족", "단위 정보가 없습니다."],
] as const)("%s 판정의 주장, 두 원문 위치와 사유를 표시한다", (status, label, reason) => {
  render(<StoryPlanView plan={compared(status)} />);
  const view = screen.getByRole("region", { name: "지표 비교" });
  expect(view).toHaveTextContent(label);
  expect(view).toHaveTextContent(reason);
  expect(view).toHaveTextContent("비용 확인 후 확대 여부를 판단한다");
  expect(view).toHaveTextContent("합성.md (2~2행)");
  expect(view).toHaveTextContent("두번째.md (2~2행)");
  expect(view).toHaveTextContent("검사 대상 1건");
});

it("일치 판정은 입력 조건의 일치로 표시하고 의미 검수와 구분한다", () => {
  render(<StoryPlanView plan={compared("compatible")} />);
  const view = screen.getByRole("region", { name: "지표 비교" });
  expect(view).toHaveTextContent("입력 조건 일치");
  expect(view).toHaveTextContent("원문 해석의 정확성");
  expect(within(view).queryByText("검수 통과")).not.toBeInTheDocument();
});

it("등록한 비교가 없는 기존 계획은 대상 0건을 통과로 표시하지 않는다", () => {
  render(<StoryPlanView plan={storyDeck().structure.story_plan!} />);
  const view = screen.getByRole("region", { name: "지표 비교" });
  expect(view).toHaveTextContent("검사 대상 0건");
  expect(view).toHaveTextContent("등록된 비교가 없어 검사하지 않았습니다.");
});

it("비교 요청은 있지만 결과가 없는 경우 미검사로 표시한다", () => {
  render(<StoryPlanView plan={{ ...compared("compatible"), comparison_results: [] }} />);
  const view = screen.getByRole("region", { name: "지표 비교" });
  expect(view).toHaveTextContent("미검사");
  expect(view).toHaveTextContent("검사 대상 1건");
  expect(view).not.toHaveTextContent("입력 조건 일치");
});

it("비교에 실제 사용한 정의, 기간, 단위와 분모를 보여 준다", () => {
  render(<StoryPlanView plan={comparisonDeck().structure.story_plan!} />);
  const view = screen.getByRole("region", { name: "지표 비교" });
  expect(view).toHaveTextContent("순매출");
  expect(view).toHaveTextContent("천원");
  expect(view).toHaveTextContent("2026-01-01~2026-01-31 / 월 / 합계 / 전체 기간");
  expect(view).toHaveTextContent("해당 없음");
});
