import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AiConsentDeclined, api, ApiError, type Deck, type GenerationUsage } from "../api/client";
import { emptyUsage } from "../test/usage";
import { StructureScreen } from "./StructureScreen";

// 계측값이 채워진 사용량 (미확인이 아님을 확인하는 테스트용, 단계 5A 묶음 C4)
function measuredUsage(overrides: Partial<GenerationUsage> = {}): GenerationUsage {
  return {
    ...emptyUsage(), calls: 1,
    input_tokens: 100, output_tokens: 50, cache_read_tokens: 0, cache_creation_tokens: 0,
    duration_ms: 1000, duration_api_ms: 900, cost_usd: 0.01,
    records: [{ purpose: "generate", ok: true, usage: {
      model: null, input_tokens: 100, output_tokens: 50, cache_read_tokens: 0, cache_creation_tokens: 0,
      duration_ms: 1000, duration_api_ms: 900, num_turns: 1, cost_usd: 0.01, stop_reason: null,
      terminal_reason: "completed", api_error_status: null, token_source: "model_usage",
    } }],
    ...overrides,
  };
}

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    generateStructure: vi.fn(), generateChapter: vi.fn(), putDeck: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };

function emptyDeck(): Deck {
  return {
    schema_version: 1,
    meta: { title: "제목", report_type: "research", audience: "", presenter: "", preset_overrides: {} },
    structure: { chapters: [] },
    slides: [],
  };
}

const CH1 = { id: "c1", topic: "표지", conclusion: "", template: "cover" as const, source_refs: [] };
const CH2 = { id: "c2", topic: "본문", conclusion: "결론", template: "bullet_box" as const, source_refs: [] };

it("구조안을 생성해 초안 표를 보여준다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: ["9999"], format_retried: false,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  expect(await screen.findByDisplayValue("본문")).toBeInTheDocument();
  expect(screen.getByText(/9999/)).toBeInTheDocument();  // 자료에 없는 수치 경고
});

it("승인하면 덱 반영 후 장별로 순차 생성해 저장한다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter)
    .mockResolvedValueOnce({ status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [],
      format_retried: false, condensed: false,
      slots: { template: "cover", title: "제목", subtitle: "", date: "" } })
    .mockResolvedValueOnce({ status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [],
      format_retried: false, condensed: false,
      slots: { template: "bullet_box", bullets: [{ text: "가", level: 0 }], conclusion: "결", footnote: "" } });
  const onDone = vi.fn();
  const onBusyChange = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone}
    onBusyChange={onBusyChange} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  onBusyChange.mockClear();  // 구조안 생성 자체의 busy 전이는 이 단언과 무관하므로 승인 클릭 이전 호출은 걷어낸다
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  // 승인 저장 1회(snapshot true) + 장 반영 2회(snapshot false)
  const calls = vi.mocked(api.putDeck).mock.calls;
  expect(calls[0][2]).toBe(true);
  expect(calls.length).toBe(3);
  expect(calls[2][1].slides).toHaveLength(2);
  // 편집 탭 게이트(ProjectView)가 순차 생성 진행 중임을 알 수 있도록 busy 전이를 알린다
  // (2026-08-29 최종 리뷰 발견)
  expect(onBusyChange.mock.calls[0]).toEqual([true]);
  expect(onBusyChange.mock.calls.at(-1)).toEqual([false]);
});

it("형식 오류면 원문과 재시도 경로를 보여준다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "format_error", structure: null, usage: emptyUsage(), raw_text: "이상한 응답",
    unverified_numbers: [], format_retried: true,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  expect(await screen.findByText(/형식에 맞게 읽지 못했습니다/)).toBeInTheDocument();
  expect(screen.getByText("이상한 응답")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "다시 생성" })).toBeInTheDocument();
});

it("기존 슬라이드가 사라지는 승인은 확인을 거친다", async () => {
  // 장 2개 중 슬라이드가 있는 c2만 삭제한다: 초안에 CH1이 남아 승인 버튼이 유지되고,
  // c2 슬라이드의 소실로 확인 대화가 뜬다 (마지막 장을 삭제하면 승인 절 자체가 사라지므로 부적합)
  const deck = emptyDeck();
  deck.structure.chapters = [CH1, CH2];
  deck.slides = [{ chapter_id: "c2", slots: {
    template: "bullet_box", bullets: [], conclusion: "결", footnote: "" } }];
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByLabelText("본문 삭제"));
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  expect(confirmSpy).toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();  // 취소했으므로 반영 없음
  confirmSpy.mockRestore();
});

it("일부 장이 실패하면 onDone을 부르지 않고, 재승인은 성공분을 계승한다", async () => {
  // onDeckChange를 실제 화면(ProjectView)처럼 상태로 반영해야 재승인 시 deck.slides에
  // 직전 성공분(c1)이 반영된다: 실제 앱과 어긋나는 no-op 콜백으로는 이 시나리오를 재현할 수 없다
  function Wrapper({ onDone }: { onDone: () => void }) {
    const [deck, setDeck] = useState<Deck>(emptyDeck());
    return <StructureScreen project={project} deck={deck} onDeckChange={setDeck} onDone={onDone} />;
  }

  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter)
    .mockResolvedValueOnce({ status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [],
      format_retried: false, condensed: false,
      slots: { template: "cover", title: "제목", subtitle: "", date: "" } })
    .mockResolvedValueOnce({ status: "format_error", slots: null, usage: emptyUsage(), raw_text: "깨진 응답",
      warnings: [], unverified_numbers: [], format_retried: true, condensed: false });
  const onDone = vi.fn();
  render(<Wrapper onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  // 첫 승인은 빈 덱에서 시작하므로(구조안 생성 직후 draftGenerated=true, deck.slides=[]) 사라질 슬라이드가 없어
  // window.confirm이 뜨지 않는다: 그래도 실행 경로에 있으면 안전하게 진행되도록 true로 스파이해 둔다
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await screen.findByText(/실패한 장만 다시 시도/);
  expect(onDone).not.toHaveBeenCalled();

  // 재승인: setDraftGenerated(false) 정정 덕분에 deck.slides의 c1이 계승되어(kept) 실패한 c2만 재생성 대상이 된다
  vi.mocked(api.generateChapter).mockResolvedValueOnce({
    status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [],
    format_retried: false, condensed: false,
    slots: { template: "bullet_box", bullets: [{ text: "가", level: 0 }], conclusion: "결", footnote: "" } });
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  // generateChapter는 총 3회만 불렸다(1회차 c1 성공, c2 실패 + 2회차 c2 재시도뿐, c1은 다시 부르지 않는다)
  const calls = vi.mocked(api.generateChapter).mock.calls;
  expect(calls).toHaveLength(3);
  expect(calls[2][1]).toBe("c2");
  confirmSpy.mockRestore();
});

it("승인 루프의 putDeck이 412면 그 장을 실패로 표시하고 onConflict를 부르며 멈춘다 (A5)", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck)
    .mockResolvedValueOnce({ ok: true })  // 최초 승인 반영 (snapshot true)
    .mockRejectedValueOnce(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  vi.mocked(api.generateChapter).mockResolvedValue({
    status: "ok", usage: emptyUsage(), raw_text: "", warnings: [], unverified_numbers: [],
    format_retried: false, condensed: false,
    slots: { template: "cover", title: "제목", subtitle: "", date: "" },
  });
  const onConflict = vi.fn();
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone}
    onConflict={onConflict} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onConflict).toHaveBeenCalled());
  const row = screen.getByLabelText("1번 장 주제").closest("tr")!;
  expect(within(row).getByText("실패", { exact: false })).toBeInTheDocument();
  expect(onDone).not.toHaveBeenCalled();
  // c1(표지)에서 멈췄으므로 c2(본문)의 생성 호출은 없다
  expect(api.generateChapter).toHaveBeenCalledTimes(1);
});

it("최초 승인 반영의 putDeck이 412면 생성을 시작하지 않고 onConflict를 부른다 (A5b 리뷰)", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  const onConflict = vi.fn();
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone}
    onConflict={onConflict} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onConflict).toHaveBeenCalled());
  expect(onDone).not.toHaveBeenCalled();
  expect(api.generateChapter).not.toHaveBeenCalled();  // 어떤 장도 시도되지 않았다
});

// AI 전송 고지 취소 (계획서 B3): 취소는 실패가 아니므로 role=alert가 아닌 안내 문구로 보인다
it("구조안 생성에서 AI 전송을 취소하면 알림이 아닌 안내 문구를 보인다", async () => {
  vi.mocked(api.generateStructure).mockRejectedValue(new AiConsentDeclined());
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  const notice = await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.");
  expect(notice.closest('[role="alert"]')).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("승인 루프에서 첫 장을 취소하면 남은 장은 관문을 다시 묻지 않고 취소로 표시되며 onDone을 부르지 않는다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter).mockRejectedValue(new AiConsentDeclined());
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => {
    const row1 = screen.getByLabelText("1번 장 주제").closest("tr")!;
    const row2 = screen.getByLabelText("2번 장 주제").closest("tr")!;
    expect(within(row1).getByText("취소", { exact: false })).toBeInTheDocument();
    expect(within(row2).getByText("취소", { exact: false })).toBeInTheDocument();
  });
  // 취소한 장 이후로는 관문(generateChapter)을 다시 부르지 않는다: 1회만 호출됐어야 한다
  expect(api.generateChapter).toHaveBeenCalledTimes(1);
  expect(onDone).not.toHaveBeenCalled();
  expect(screen.queryByRole("alert")).toBeNull();
});

// 태스크 C4: 구조안 결과 아래(승인 버튼 위)에 사용량 한 줄을 보인다
it("구조안 생성 뒤 사용량 문단이 승인 버튼 위에 보인다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: measuredUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  const usageP = await screen.findByText(/AI 사용량: 호출 1회/);
  const approveBtn = screen.getByRole("button", { name: "승인하고 내용 생성" });
  // DOCUMENT_POSITION_FOLLOWING(4): usageP가 approveBtn보다 문서상 앞에 있다
  // eslint-disable-next-line no-bitwise
  expect(approveBtn.compareDocumentPosition(usageP) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
});

it("사용량 값이 없으면 미확인이 보인다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  expect(await screen.findByText(/토큰 미확인/)).toBeInTheDocument();
  expect(screen.getByText(/비용 미확인/)).toBeInTheDocument();
});

it("승인 루프가 끝나면 장 생성 합계 한 줄을 보인다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter)
    .mockResolvedValueOnce({ status: "ok", usage: measuredUsage(), raw_text: "", warnings: [],
      unverified_numbers: [], format_retried: false, condensed: false,
      slots: { template: "cover", title: "제목", subtitle: "", date: "" } })
    .mockResolvedValueOnce({ status: "ok", usage: measuredUsage(), raw_text: "", warnings: [],
      unverified_numbers: [], format_retried: false, condensed: false,
      slots: { template: "bullet_box", bullets: [{ text: "가", level: 0 }], conclusion: "결", footnote: "" } });
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  // 두 장의 usage(입력 100 토큰씩)를 합산한 값이 보인다: 장 생성 2회, 입력 200 토큰
  expect(await screen.findByText(/장 생성 2회.*입력 200 토큰/)).toBeInTheDocument();
});

it("승인 루프에서 한 장이 503으로 실패하면 합계 줄에 포함되지 않았다는 단서가 보인다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.generateChapter)
    .mockResolvedValueOnce({ status: "ok", usage: measuredUsage(), raw_text: "", warnings: [],
      unverified_numbers: [], format_retried: false, condensed: false,
      slots: { template: "cover", title: "제목", subtitle: "", date: "" } })
    .mockRejectedValueOnce(new ApiError(503, "AI 서비스가 응답하지 않습니다."));
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await screen.findByText(/AI 서비스가 응답하지 않습니다/);
  expect(onDone).not.toHaveBeenCalled();
  // 성공한 1개 장(c1)의 usage만 합계에 실리고, 실패한 c2는 결과 자체가 없어 빠졌다는 단서가 보인다
  expect(screen.getByText(/장 생성 1회.*입력 100 토큰/)).toBeInTheDocument();
  expect(screen.getByText(
    "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 ai-usage.jsonl)",
    { exact: false },
  )).toBeInTheDocument();
});

it("목표 장수와 지시사항이 각각 한 줄을 차지하고 지시사항 입력란이 5줄이다", () => {
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  const target = screen.getByLabelText("목표 장수");
  const instructions = screen.getByLabelText("지시사항");
  expect(instructions).toHaveAttribute("rows", "5");
  const targetField = target.closest(".field");
  const instructionsField = instructions.closest(".field");
  expect(targetField).not.toBeNull();
  expect(instructionsField).not.toBeNull();
  expect(targetField).not.toBe(instructionsField);  // 한 줄 배치로 회귀하면 같은 조상이 되거나 null이 된다
});
