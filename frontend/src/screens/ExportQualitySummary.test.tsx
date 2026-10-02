import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q1b1-quality.json";
import type { ExportResult, QualityReport } from "../api/client";
import { ExportQualitySummary } from "./ExportQualitySummary";

function result(kind: keyof typeof fixture): ExportResult {
  return {
    path: "/exports/report_v001.pptx",
    quality_path: "/exports/published-record.quality.json",
    quality: fixture[kind] as QualityReport,
  };
}

it("shows the published record path and a limited match without final approval", async () => {
  render(<ExportQualitySummary result={result("matched")} />);
  await userEvent.click(screen.getByText("점검 항목과 확인할 문구"));
  const region = screen.getByRole("region", { name: "내보낸 초안의 점검 결과" });
  expect(region).toHaveTextContent("검수 전 초안");
  expect(region).toHaveTextContent("수치 포함 칸 1개, 검사 1개, 일치 1개, 확인 필요 0개");
  expect(region).toHaveTextContent("/exports/published-record.quality.json");
  expect(within(region).getByRole("row", { name: /근거 타당성/ })).toHaveTextContent("미수행");
  expect(within(region).getByRole("row", { name: /실제 PowerPoint 표시/ })).toHaveTextContent("미수행");
  expect(region).not.toHaveTextContent("제출 가능");
});

it("shows unresolved exported text and the reason to review it", async () => {
  render(<ExportQualitySummary result={result("mismatched")} />);
  await userEvent.click(screen.getByText("점검 항목과 확인할 문구"));
  const region = screen.getByRole("region", { name: "내보낸 초안의 점검 결과" });
  expect(region).toHaveTextContent("확인 필요");
  expect(region).toHaveTextContent("수치 포함 칸 1개, 검사 1개, 일치 0개, 확인 필요 1개");
  expect(region).toHaveTextContent(fixture.mismatched.numeric_review.items[0].actual);
  expect(region).toHaveTextContent(fixture.mismatched.numeric_review.items[0].message);
});

it.each([
  ["stale", "자료나 보고 계획이 바뀌어 대조하지 않았습니다."],
  ["empty", "대상 0개는 통과가 아닙니다."],
] as const)("keeps %s as not run and gives its reason", async (kind, message) => {
  render(<ExportQualitySummary result={result(kind)} />);
  await userEvent.click(screen.getByText("점검 항목과 확인할 문구"));
  const region = screen.getByRole("region", { name: "내보낸 초안의 점검 결과" });
  expect(region).toHaveTextContent(message);
  expect(within(region).getByRole("row", { name: /계산 문구 대조/ })).toHaveTextContent("미수행");
  expect(region).toHaveTextContent("검사 0개");
});

it("does not invent a numeric verdict for a legacy record", () => {
  const legacy = result("matched");
  legacy.quality = { ...legacy.quality, gate_version: "preflight-v1", numeric_review: null,
    checks: legacy.quality.checks.filter(c => c.name !== "numeric_expressions") };
  render(<ExportQualitySummary result={legacy} />);
  expect(screen.getByRole("region")).toHaveTextContent("이 기록에는 계산 문구 대조 결과가 없습니다.");
});
