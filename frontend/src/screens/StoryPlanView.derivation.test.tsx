import { render, screen } from "@testing-library/react";
import type { Deck } from "../api/client";
import savedFixture from "../../../backend/tests/fixtures/q2c-derived-deck.json";
import { storyDeck } from "../test/story";
import { StoryPlanView } from "./StoryPlanView";

function computed() {
  return (structuredClone(savedFixture.deck) as Deck).structure.story_plan!;
}

it("백엔드 합성 저장본의 결과, 산식, 기준값과 원문 위치를 표시한다", () => {
  render(<StoryPlanView plan={computed()} />);
  const view = screen.getByRole("region", { name: "수치 계산" });
  expect(view).toHaveTextContent("계산 대상 2건 / 계산 불가 0건 / 미계산 0건");
  expect(view).toHaveTextContent("200 원");
  expect(view).toHaveTextContent("20 %");
  expect(view).toHaveTextContent("대상값 - 기준값");
  expect(view).toHaveTextContent("기준값");
  expect(view).toHaveTextContent("synthetic.md (2~2행)");
  expect(view).toHaveTextContent("synthetic.md (3~3행)");
  expect(view).toHaveTextContent("1,200원");
  expect(view).toHaveTextContent("1,000원");
  expect(view).toHaveTextContent("원문 해석");
  expect(view).not.toHaveTextContent("검수 통과");
});

it("프런트가 재계산하거나 큰 숫자를 부동소수점으로 바꾸지 않는다", () => {
  const plan = computed();
  plan.derived_values[0].value = "999999999999999999999998";
  render(<StoryPlanView plan={plan} />);
  expect(screen.getByRole("region", { name: "수치 계산" })).toHaveTextContent("999999999999999999999998 원");
});

it("반올림과 퍼센트포인트를 보존한다", () => {
  const plan = computed();
  plan.derived_values[0] = { ...plan.derived_values[0], value: "33.333333", unit: "퍼센트포인트", rounded: true };
  render(<StoryPlanView plan={plan} />);
  const view = screen.getByRole("region", { name: "수치 계산" });
  expect(view).toHaveTextContent("33.333333 퍼센트포인트");
  expect(view).toHaveTextContent("소수 최대 6자리로 반올림");
});

it("계산 불가에서는 결과 숫자를 만들지 않고 원문 위치와 사유를 보인다", () => {
  const plan = computed();
  plan.derivations = [plan.derivations[0]];
  plan.derived_values = [{ ...plan.derived_values[0], status: "blocked", value: null, unit: null, rounded: null,
    reasons: [{ code: "invalid_number", evidence_id: "e1", message: "명확한 원문 숫자가 필요합니다." }] }];
  render(<StoryPlanView plan={plan} />);
  const view = screen.getByRole("region", { name: "수치 계산" });
  expect(view).toHaveTextContent("계산 불가 1건");
  expect(view).toHaveTextContent("명확한 원문 숫자가 필요합니다.");
  expect(view).toHaveTextContent("synthetic.md (2~2행)");
  expect(view).not.toHaveTextContent("200 원");
  expect(view).not.toHaveTextContent("계산 결과");
});

it("비교 때문에 계산하지 못하면 구체적인 비교 사유도 함께 보인다", () => {
  const plan = computed();
  plan.derivations = [plan.derivations[0]];
  plan.comparison_results[0] = { ...plan.comparison_results[0], status: "incompatible",
    reasons: [{ code: "unit_mismatch", field: "unit", evidence_id: null, message: "두 근거의 단위가 다릅니다." }] };
  plan.derived_values = [{ ...plan.derived_values[0], status: "blocked", value: null, unit: null, rounded: null,
    reasons: [{ code: "comparison_blocked", evidence_id: null, message: "비교 사유를 확인해 주세요." }] }];
  render(<StoryPlanView plan={plan} />);
  expect(screen.getByRole("region", { name: "수치 계산" })).toHaveTextContent("두 근거의 단위가 다릅니다.");
});

it("0 결과는 미계산으로 바꾸지 않는다", () => {
  const plan = computed();
  plan.derived_values[0].value = "0";
  render(<StoryPlanView plan={plan} />);
  expect(screen.getByRole("region", { name: "수치 계산" })).toHaveTextContent("계산 결과: 0 원");
});

it("등록된 산식이 없는 옛 계획은 계산 대상 0건과 미수행을 표시한다", () => {
  render(<StoryPlanView plan={storyDeck().structure.story_plan!} />);
  const view = screen.getByRole("region", { name: "수치 계산" });
  expect(view).toHaveTextContent("계산 대상 0건");
  expect(view).toHaveTextContent("등록된 산식이 없어 계산하지 않았습니다.");
});

it("산식에 대응하는 서버 결과가 없으면 미계산으로 표시한다", () => {
  const plan = computed();
  plan.derived_values = [];
  render(<StoryPlanView plan={plan} />);
  const view = screen.getByRole("region", { name: "수치 계산" });
  expect(view).toHaveTextContent("미계산 2건");
  expect(view).not.toHaveTextContent("계산 결과");
});
