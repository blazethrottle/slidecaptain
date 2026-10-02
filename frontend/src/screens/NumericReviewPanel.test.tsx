import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import fixture from "../../../backend/tests/fixtures/q2d-numeric-review.json";
import { api, ApiError, type Deck, type NumericReviewReport } from "../api/client";
import { NumericReviewPanel } from "./NumericReviewPanel";

vi.mock("../api/client", async (original) => ({
  ...await original<typeof import("../api/client")>(),
  api: { reviewNumbers: vi.fn() },
}));

const deck = fixture.deck as Deck;
const matched = fixture.matched_report as NumericReviewReport;
beforeEach(() => vi.clearAllMocks());

it("reviews the exact editor input without saving or generating and shows linked expressions", async () => {
  vi.mocked(api.reviewNumbers).mockResolvedValue(matched);
  const before = JSON.stringify(deck);
  render(<NumericReviewPanel projectName="synthetic" deck={deck} />);
  expect(api.reviewNumbers).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  expect(await screen.findByText("텍스트 칸 1개 중 일치 1개, 확인 필요 0개.")).toBeInTheDocument();
  expect(api.reviewNumbers).toHaveBeenCalledWith("synthetic", deck);
  expect(screen.getByText(/원문 해석, 자유로운 문장의 의미와 보고서 품질은 미검수/)).toBeInTheDocument();
  expect(JSON.stringify(deck)).toBe(before);
});

it("shows an incorrect sign as unresolved with the original draft and expected expression", async () => {
  vi.mocked(api.reviewNumbers).mockResolvedValue(fixture.mismatched_report as NumericReviewReport);
  render(<NumericReviewPanel projectName="synthetic" deck={deck} />);
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  expect(await screen.findByText("텍스트 칸 1개 중 일치 0개, 확인 필요 1개.")).toBeInTheDocument();
  expect(screen.getByText(fixture.mismatched_report.items[0].actual)).toBeInTheDocument();
  expect(screen.getByText(matched.expressions[0].text)).toBeInTheDocument();
});

it("removes a result on edit and does not resurrect it after undo", async () => {
  vi.mocked(api.reviewNumbers).mockResolvedValue(matched);
  const view = render(<NumericReviewPanel projectName="synthetic" deck={deck} />);
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  await screen.findByText("텍스트 칸 1개 중 일치 1개, 확인 필요 0개.");
  view.rerender(<NumericReviewPanel projectName="synthetic" deck={{ ...deck, slides: [] }} />);
  expect(screen.queryByText(/일치 1개, 확인 필요 0개/)).not.toBeInTheDocument();
  view.rerender(<NumericReviewPanel projectName="synthetic" deck={deck} />);
  expect(screen.queryByText(/일치 1개, 확인 필요 0개/)).not.toBeInTheDocument();
});

it("ignores late responses from earlier edits and keeps the newer response", async () => {
  let finish!: (report: NumericReviewReport) => void;
  vi.mocked(api.reviewNumbers).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }))
    .mockResolvedValueOnce(fixture.mismatched_report as NumericReviewReport);
  const view = render(<NumericReviewPanel projectName="synthetic" deck={deck} />);
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  const edited = { ...deck, slides: [...deck.slides] };
  view.rerender(<NumericReviewPanel projectName="synthetic" deck={edited} />);
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  await screen.findByText("텍스트 칸 1개 중 일치 0개, 확인 필요 1개.");
  await act(async () => finish(matched));
  expect(screen.queryByText(/일치 1개, 확인 필요 0개/)).not.toBeInTheDocument();
  expect(screen.getByText(/일치 0개, 확인 필요 1개/)).toBeInTheDocument();
});

it("shows not-run separately from a zero-issue match", async () => {
  vi.mocked(api.reviewNumbers).mockResolvedValue({ ...matched, status: "not_run", reason: "stale_plan", evaluated: 0, matched: 0, expressions: [], items: [] });
  render(<NumericReviewPanel projectName="synthetic" deck={deck} />);
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  expect(await screen.findByText(/자료나 보고 계획이 바뀌어 대조하지 않았습니다/)).toBeInTheDocument();
  expect(screen.queryByText(/텍스트 칸 1개 중/)).not.toBeInTheDocument();
});

it("clears the old match while retrying and after an API error", async () => {
  vi.mocked(api.reviewNumbers).mockResolvedValueOnce(matched).mockRejectedValueOnce(new ApiError(422, "입력 자료가 없습니다."));
  render(<NumericReviewPanel projectName="synthetic" deck={deck} />);
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  await screen.findByText("텍스트 칸 1개 중 일치 1개, 확인 필요 0개.");
  fireEvent.click(screen.getByRole("button", { name: "계산 문구 대조" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("입력 자료가 없습니다.");
  expect(screen.queryByText(/일치 1개, 확인 필요 0개/)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "계산 문구 대조" })).toBeEnabled());
});
