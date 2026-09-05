import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AiConsentDeclined, api, type ChapterResult, type Deck } from "../api/client";
import { emptyUsage } from "../test/usage";
import { GeneratePanel } from "./GeneratePanel";

// 계측값이 채워진 사용량 (미확인이 아님을 확인하는 테스트용, 단계 5A 묶음 C4)
function measuredUsage(): ChapterResult["usage"] {
  return {
    ...emptyUsage(), calls: 1,
    input_tokens: 100, output_tokens: 50, cache_read_tokens: 0, cache_creation_tokens: 0,
    duration_ms: 1000, duration_api_ms: 900, cost_usd: 0.01,
    records: [{ purpose: "generate", ok: true, usage: {
      model: null, input_tokens: 100, output_tokens: 50, cache_read_tokens: 0, cache_creation_tokens: 0,
      duration_ms: 1000, duration_api_ms: 900, num_turns: 1, cost_usd: 0.01, stop_reason: null,
      terminal_reason: "completed", api_error_status: null, token_source: "model_usage",
    } }],
  };
}

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, generateChapter: vi.fn(), condenseChapter: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "t", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
  structure: { chapters: [
    { id: "c1", topic: "주제", conclusion: "", template: "bullet_box", source_refs: [] }] },
  slides: [{ chapter_id: "c1", slots: {
    template: "bullet_box", bullets: [{ text: "옛 내용", level: 0 }], conclusion: "결", footnote: "" } }],
};

const okResult: ChapterResult = {
  status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: ["8888"],
  format_retried: false, condensed: true,
  slots: { template: "bullet_box", bullets: [{ text: "새 내용", level: 0 }], conclusion: "결", footnote: "" },
};

it("재생성 결과를 보여주고 반영하면 onReplace에 새 슬롯이 담긴다", async () => {
  vi.mocked(api.generateChapter).mockResolvedValue(okResult);
  const onReplace = vi.fn();
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={onReplace} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/8888/)).toBeInTheDocument();  // 수치 경고
  expect(screen.getByText(/축약했습니다/)).toBeInTheDocument();  // condensed 표시
  await userEvent.click(screen.getByText("반영"));
  const next = onReplace.mock.calls[0][0] as Deck;
  const slots = next.slides[0].slots;
  expect(slots.template === "bullet_box" && slots.bullets?.[0].text).toBe("새 내용");
});

it("축약은 현재 슬롯을 동봉해 호출한다", async () => {
  vi.mocked(api.condenseChapter).mockResolvedValue(okResult);
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  await waitFor(() => expect(api.condenseChapter).toHaveBeenCalled());
  const [, , sentSlots] = vi.mocked(api.condenseChapter).mock.calls[0];
  expect(sentSlots.template === "bullet_box" && sentSlots.bullets?.[0].text).toBe("옛 내용");
});

it("형식 오류는 원문과 재시도 경로를 보여주고 버리기 전까지 반영 버튼이 없다", async () => {
  vi.mocked(api.generateChapter).mockResolvedValue({
    status: "format_error", slots: null, usage: emptyUsage(), raw_text: "이상한 원문",
    warnings: [], unverified_numbers: [], format_retried: true, condensed: false,
  });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText("이상한 원문")).toBeInTheDocument();
  expect(screen.queryByText("반영")).not.toBeInTheDocument();
});

it("장을 전환하면 이전 장의 결과 패널이 사라진다", async () => {
  vi.mocked(api.generateChapter).mockResolvedValue(okResult);
  const { rerender } = render(
    <GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText("반영")).toBeInTheDocument();
  rerender(<GeneratePanel project={project} deck={deck} chapterId="c2" onReplace={() => {}} />);
  expect(screen.queryByText("반영")).not.toBeInTheDocument();
});

// AI 전송 고지 취소 (계획서 B3): 취소는 실패가 아니므로 role=alert가 아닌 안내 문구로 보인다
it("재생성에서 AI 전송을 취소하면 알림이 아닌 안내 문구를 보인다", async () => {
  vi.mocked(api.generateChapter).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("축약에서 AI 전송을 취소해도 알림이 아닌 안내 문구를 보인다", async () => {
  vi.mocked(api.condenseChapter).mockRejectedValue(new AiConsentDeclined());
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 축약"));
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
});

// 태스크 C4: 결과 안내(축약, 재시도 문구) 옆에 사용량 한 줄을 보인다
it("재생성 결과 안내 옆에 사용량 한 줄을 보인다", async () => {
  // F8 리뷰 반영: 제목이 실제로 검증하지 않는 "값이 없으면 미확인" 주장을 포함하고 있었다.
  // 그 케이스는 바로 다음 테스트가 담당하므로 제목을 실제 검증 내용에 맞춘다.
  vi.mocked(api.generateChapter).mockResolvedValue({ ...okResult, usage: measuredUsage() });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
  expect(screen.getByText(/입력 100 토큰/)).toBeInTheDocument();
});

it("사용량 값이 없으면 미확인이 보인다", async () => {
  vi.mocked(api.generateChapter).mockResolvedValue(okResult);  // okResult.usage는 emptyUsage()
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/토큰 미확인/)).toBeInTheDocument();
  expect(screen.getByText(/비용 미확인/)).toBeInTheDocument();
});

// F5 리뷰 반영: usage는 상태와 무관하게 항상 채워지는 필수 필드다(C2/C3 가정 6). 형식 오류로
// 끝나도 최소 1회 호출은 있었으므로 그 사용량을 화면에서 감추면 안 된다.
it("형식 오류에도 사용량 한 줄이 보인다", async () => {
  vi.mocked(api.generateChapter).mockResolvedValue({
    status: "format_error", slots: null, usage: measuredUsage(), raw_text: "이상한 원문",
    warnings: [], unverified_numbers: [], format_retried: true, condensed: false,
  });
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  await userEvent.click(screen.getByText("이 장 다시 생성"));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
});

it("지시사항 입력이 .field 안에 있고 버튼은 .actions 행에 있다", () => {
  render(<GeneratePanel project={project} deck={deck} chapterId="c1" onReplace={() => {}} />);
  expect(screen.getByLabelText("재생성 지시사항").closest(".field")).not.toBeNull();
  expect(screen.getByText("이 장 다시 생성").closest(".actions")).not.toBeNull();
});
