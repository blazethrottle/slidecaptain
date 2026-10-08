import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AiConsentDeclined, api, ApiError, type Deck, type GenerationUsage } from "../api/client";
import { batchView, chapterResult, chapterView } from "../test/jobs";
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
    generateStructure: vi.fn(), generateChapter: vi.fn(), putDeck: vi.fn(), saveDraft: vi.fn(),
    prepareAi: vi.fn(), startChapters: vi.fn(), getJob: vi.fn(), getDeck: vi.fn(), listJobs: vi.fn(),
    cancelJob: vi.fn(), dismissChapterCandidate: vi.fn() } };
});

// 장 생성 묶음 (D2b-5a): 승인은 AI 준비 확인, 승인 반영 PUT, 묶음 등록, 조회 순서다
beforeEach(() => {
  vi.mocked(api.prepareAi).mockResolvedValue({ "X-AI-Consent": "SlideCaptain" });
  vi.mocked(api.listJobs).mockResolvedValue([]);
});

const COVER = { template: "cover" as const, title: "제목", subtitle: "", date: "" };
const BODY = { template: "bullet_box" as const, bullets: [{ text: "가", level: 0 as const }], conclusion: "결", footnote: "" };

function deckWith(chapters: Deck["structure"]["chapters"], slides: { chapter_id: string; slots: unknown }[]): Deck {
  const deck = emptyDeck();
  deck.structure.chapters = chapters;
  deck.slides = slides.map((s) => ({ ...s, eyebrow: "", subtitle: "" })) as Deck["slides"];
  return deck;
}

// 묶음 한 번: 등록 응답은 실행 중, 첫 조회가 final이다
function mockBatch(final: ReturnType<typeof batchView>, deckAfter: Deck) {
  vi.mocked(api.startChapters).mockResolvedValueOnce({ ...final, state: "running", outcome: null });
  vi.mocked(api.getJob).mockResolvedValueOnce(final);
  vi.mocked(api.getDeck).mockResolvedValue(deckAfter);
}

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

it("템플릿 드롭다운은 편집 가능한 신규 4종을 제공한다", async () => {
  // DB-6 속성 편집을 제공한 신규 템플릿도 선택할 수 있다.
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  const select = await screen.findByLabelText("1번 장 템플릿") as HTMLSelectElement;
  const values = Array.from(select.options).map((o) => o.value);
  expect(values).toEqual(expect.arrayContaining(["callout", "cards", "process", "matrix"]));
  expect(values).toHaveLength(10);
});

it("승인하면 덱 반영 후 장 생성 묶음을 등록하고, 끝나면 덱을 다시 읽는다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const after = deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }, { chapter_id: "c2", slots: BODY }]);
  mockBatch(batchView([chapterView("c1", "succeeded", { result: chapterResult(COVER) }),
    chapterView("c2", "succeeded", { result: chapterResult(BODY) })]), after);
  const onDone = vi.fn();
  const onBusyChange = vi.fn();
  const onDeckChange = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={onDeckChange} onDone={onDone}
    onBusyChange={onBusyChange} pollIntervalMs={0} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  onBusyChange.mockClear();  // 구조안 생성 자체의 busy 전이는 이 단언과 무관하므로 승인 클릭 이전 호출은 걷어낸다
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  // 승인 반영 1회(snapshot true)만 화면이 저장한다. 장 결과는 서버가 저장한다
  expect(vi.mocked(api.putDeck).mock.calls).toHaveLength(1);
  expect(vi.mocked(api.putDeck).mock.calls[0][2]).toBe(true);
  expect(vi.mocked(api.startChapters).mock.calls[0][1]).toEqual(["c1", "c2"]);
  // 서버가 저장한 덱과 ETag를 다시 읽어 부모에 올린다 (계획서 D2b-5a 덱 따라가기)
  expect(onDeckChange).toHaveBeenLastCalledWith(after);
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

it("핵심 답변 연결 실패는 입력 오류로 안내하지 않고 다시 생성 경로를 제공한다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({ status: "format_error", structure: null,
    usage: emptyUsage(), raw_text: "synthetic", unverified_numbers: [], format_retried: true,
    format_issue: "answer_not_in_summary" });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  const field = screen.getByLabelText("문서의 주안점 및 원하는 결과 입력");
  await userEvent.type(field, "다음 주 계획 강조");
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  expect(await screen.findByText(/핵심 답변을 설명하는 장에 일부 주장이 연결되지 않았습니다/)).toBeInTheDocument();
  expect(screen.queryByText(/원문을 확인하고/)).not.toBeInTheDocument();
  expect(field).toHaveValue("다음 주 계획 강조");
  expect(screen.getByRole("button", { name: "다시 생성" })).toBeEnabled();
});

it("기존 슬라이드가 사라지는 승인은 확인을 거친다", async () => {
  // 장 2개 중 슬라이드가 있는 c2만 삭제한다: 초안에 CH1이 남아 승인 버튼이 유지되고,
  // c2 슬라이드의 소실로 확인 대화가 뜬다 (마지막 장을 삭제하면 승인 절 자체가 사라지므로 부적합)
  const deck = emptyDeck();
  deck.structure.chapters = [CH1, CH2];
  deck.slides = [{ chapter_id: "c2", eyebrow: "", subtitle: "", slots: {
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
    return <StructureScreen project={project} deck={deck} onDeckChange={setDeck} onDone={onDone} pollIntervalMs={0} />;
  }

  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  mockBatch(batchView([chapterView("c1", "succeeded", { result: chapterResult(COVER) }),
    chapterView("c2", "failed", { result: chapterResult(null, emptyUsage(), { raw_text: "깨진 응답" }),
      error: { error_class: "ai_output", status: null, detail: "형식 오류", code: "format_error" } })],
  { state: "failed", outcome: "partial" }), deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }]));
  const onDone = vi.fn();
  render(<Wrapper onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await screen.findByText(/실패한 장만 다시 생성/);
  expect(screen.getByText("깨진 응답")).toBeInTheDocument();  // 형식 오류 원문
  expect(screen.getByText(/2장 중 1장을 만들지 못했습니다/)).toBeInTheDocument();
  expect(onDone).not.toHaveBeenCalled();

  // 재승인: 덱에 반영된 c1을 계승하고 실패한 c2만 새 묶음으로 등록한다
  mockBatch(batchView([chapterView("c2", "succeeded", { result: chapterResult(BODY) })], { id: "job-2" }),
    deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }, { chapter_id: "c2", slots: BODY }]));
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(vi.mocked(api.startChapters).mock.calls[1][1]).toEqual(["c2"]);
  // 요청 ID는 버튼을 누를 때마다 새로 만든다
  expect(vi.mocked(api.startChapters).mock.calls[0][3]).not.toBe(vi.mocked(api.startChapters).mock.calls[1][3]);
  confirmSpy.mockRestore();
});

it("다른 저장으로 사슬이 끊기면 그 장은 이전 입력 기준으로 보이고 onConflict를 부른다 (D2b-5a)", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  mockBatch(batchView([chapterView("c1", "failed", { candidate_status: "stale", result: chapterResult(COVER),
    error: { error_class: "base_changed", status: null, detail: null, code: "base_changed" } }),
  chapterView("c2", "interrupted")], { state: "failed", outcome: "chain_broken" }), deckWith([CH1, CH2], []));
  const onConflict = vi.fn();
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone}
    onConflict={onConflict} pollIntervalMs={0} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onConflict).toHaveBeenCalled());
  const row1 = screen.getByLabelText("1번 장 주제").closest("tr")!;
  const row2 = screen.getByLabelText("2번 장 주제").closest("tr")!;
  expect(within(row1).getByText("이전 입력 기준", { exact: false })).toBeInTheDocument();
  expect(within(row2).getByText("중단", { exact: false })).toBeInTheDocument();
  expect(onDone).not.toHaveBeenCalled();
  expect(api.saveDraft).not.toHaveBeenCalled();  // 장 결과는 원장에 남으므로 화면이 따로 보존하지 않는다
});

it("최초 승인 반영의 putDeck이 412면 생성을 시작하지 않고 onConflict를 부른다 (A5b 리뷰)", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockRejectedValue(
    new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  vi.mocked(api.saveDraft).mockResolvedValue({ id: "d", saved_at: "2026-10-08T10:00:00+09:00",
    reason: "conflict", source: "structure_approval", base_etag: null });
  const onConflict = vi.fn();
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone}
    onConflict={onConflict} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onConflict).toHaveBeenCalled());
  expect(onDone).not.toHaveBeenCalled();
  expect(api.startChapters).not.toHaveBeenCalled();  // 생성을 등록하지 않았다
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

it("AI 전송을 취소하면 승인 반영도 하지 않고 안내 문구만 보인다 (D2b-5a)", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.prepareAi).mockRejectedValue(new AiConsentDeclined());
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  expect(await screen.findByText("전송을 취소했습니다. 필요하면 다시 시도해 주세요.")).toBeInTheDocument();
  // 지금 루프는 덱을 먼저 바꾼 뒤 장마다 취소했다. 이제는 덱을 바꾸지 않는다
  expect(api.putDeck).not.toHaveBeenCalled();
  expect(api.startChapters).not.toHaveBeenCalled();
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
  // DOCUMENT_POSITION_PRECEDING(2): usageP가 approveBtn보다 문서상 앞에 있다 (F6 리뷰 반영: 주석 정정)
  // eslint-disable-next-line no-bitwise
  expect(approveBtn.compareDocumentPosition(usageP) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
});

// C 묶음 최종 리뷰 major C-1: 구조안 최초 생성이 format_error로 끝나도 계측된 사용량이
// 화면에 남아야 한다(draft가 비어 있어 "장 구성" 섹션 자체가 없는 경우)
it("구조안 최초 생성이 format_error면 사용량이 형식 오류 안내와 함께 보인다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "format_error", structure: null, usage: measuredUsage(),
    raw_text: "이상한 응답", unverified_numbers: [], format_retried: true,
  });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByText(/형식에 맞게 읽지 못했습니다/);
  expect(await screen.findByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
});

// 같은 결함의 두 번째 경로: 기존 구조안이 있는 상태(장 구성 섹션이 이미 렌더됨)에서
// "다시 생성"이 format_error로 끝나면 새로 받은 사용량이 문단으로 보여야 한다
it("기존 구조안이 있는 상태에서 다시 생성이 format_error면 새 사용량이 보인다", async () => {
  const deck = emptyDeck();
  deck.structure.chapters = [CH1];
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "format_error", structure: null, usage: measuredUsage(),
    raw_text: "이상한 응답 2", unverified_numbers: [], format_retried: true,
  });
  render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={() => {}} />);
  expect(screen.getByRole("button", { name: "승인하고 내용 생성" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다시 생성" }));
  await screen.findByText(/형식에 맞게 읽지 못했습니다/);
  expect(await screen.findByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
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
  mockBatch(batchView([chapterView("c1", "succeeded", { result: chapterResult(COVER, measuredUsage()) }),
    chapterView("c2", "succeeded", { result: chapterResult(BODY, measuredUsage()) })]),
  deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }, { chapter_id: "c2", slots: BODY }]));
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} pollIntervalMs={0} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  // 두 장의 usage(입력 100 토큰씩)를 합산한 값이 보인다: 장 생성 2회, 입력 200 토큰
  expect(await screen.findByText(/장 생성 2회.*입력 200 토큰/)).toBeInTheDocument();
});

const FAILED_503 = { error_class: "connection" as const, status: 503, detail: "AI 서비스가 응답하지 않습니다.", code: null };

it("승인 루프에서 한 장이 503으로 실패하면 합계 줄에 포함되지 않았다는 단서가 보인다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  mockBatch(batchView([chapterView("c1", "succeeded", { result: chapterResult(COVER, measuredUsage()) }),
    chapterView("c2", "failed", { error: FAILED_503 })], { state: "failed", outcome: "partial" }),
  deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }]));
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} pollIntervalMs={0} />);
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

// F1 리뷰 반영: "다시 생성"은 새 구조안을 받으므로 이전 승인 루프의 장 사용량 합계는 더 이상 유효하지 않다
it("다시 생성을 누르면 이전 승인 루프의 사용량 합계가 사라진다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  mockBatch(batchView([chapterView("c1", "succeeded", { result: chapterResult(COVER, measuredUsage()) }),
    chapterView("c2", "succeeded", { result: chapterResult(BODY, measuredUsage()) })]),
  deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }, { chapter_id: "c2", slots: BODY }]));
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} pollIntervalMs={0} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(await screen.findByText(/장 생성 2회/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "다시 생성" }));
  await waitFor(() => expect(screen.queryByText(/장 생성 2회/)).not.toBeInTheDocument());
});

// F2 리뷰 반영: 성공한 장이 하나도 없어도(전부 실패) 사용량 관련 안내는 사라지지 않아야 한다
it("승인 루프에서 모든 장이 실패해도 실패 단서가 보인다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  mockBatch(batchView([chapterView("c1", "failed", { error: FAILED_503 }), chapterView("c2", "interrupted",
    { error: { error_class: null, status: null, detail: null, code: "provider_failed" } })],
  { state: "failed", outcome: "partial" }), deckWith([CH1, CH2], []));
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={onDone} pollIntervalMs={0} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await screen.findByText(/AI 서비스가 응답하지 않습니다/);
  expect(onDone).not.toHaveBeenCalled();
  // 성공분이 0건이라 "장 생성 N회" 합계 줄은 없지만, 실패했다는 사실 자체는 화면에 남아야 한다
  expect(screen.getByText(
    "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 ai-usage.jsonl)",
    { exact: false },
  )).toBeInTheDocument();
});

it("목표 장수와 주안점이 각각 한 줄을 차지하고 주안점 입력란이 5줄이다", () => {
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  const target = screen.getByLabelText("목표 장수");
  const instructions = screen.getByLabelText("문서의 주안점 및 원하는 결과 입력");
  expect(instructions).toHaveAttribute("rows", "5");
  const targetField = target.closest(".field");
  const instructionsField = instructions.closest(".field");
  expect(targetField).not.toBeNull();
  expect(instructionsField).not.toBeNull();
  expect(targetField).not.toBe(instructionsField);  // 한 줄 배치로 회귀하면 같은 조상이 되거나 null이 된다
});

it("주안점을 생성에 전달하고 실패해도 입력을 보존한다", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({ status: "format_error", structure: null,
    usage: emptyUsage(), raw_text: "synthetic", unverified_numbers: [], format_retried: true });
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} />);
  const field = screen.getByLabelText("문서의 주안점 및 원하는 결과 입력");
  await userEvent.type(field, "이번 주 진행과 다음 주 계획");
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByText(/형식에 맞게 읽지 못했습니다/);
  expect(api.generateStructure).toHaveBeenCalledWith("p1", expect.objectContaining({
    instructions: "이번 주 진행과 다음 주 계획",
  }));
  expect(field).toHaveValue("이번 주 진행과 다음 주 계획");
});


// -- D2a-2와 D2b-5a: 승인 반영 실패의 보존과 묶음 등록 실패 ------------------------------------

const draftInfo = { id: "draft-20261008-100000-000001", saved_at: "2026-10-08T10:00:00+09:00",
  reason: "conflict" as const, source: "structure_approval" as const, base_etag: null };
async function approveTwoChapters(final: ReturnType<typeof batchView> | null, after: Deck = emptyDeck()) {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  if (final) mockBatch(final, after);
  const view = render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}}
    onConflict={() => {}} pollIntervalMs={0} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  return view;
}

it("묶음 등록이 실패하면 장 구성은 저장했고 생성을 시작하지 못했다고 알리고 다시 시작할 수 있다 (D2b-5a)", async () => {
  vi.mocked(api.startChapters).mockRejectedValueOnce(new ApiError(409, "다른 AI 생성이 진행 중입니다. 끝난 뒤 다시 시도해 주세요.",
    "generation_active"));
  await approveTwoChapters(null);
  expect(await screen.findByText(/장 구성은 저장했고 내용 생성은 시작하지 못했습니다.*다른 AI 생성이 진행 중/))
    .toBeInTheDocument();
  expect(vi.mocked(api.putDeck).mock.calls).toHaveLength(1);
  mockBatch(batchView([chapterView("c1", "succeeded"), chapterView("c2", "succeeded")]),
    deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }, { chapter_id: "c2", slots: BODY }]));
  await userEvent.click(screen.getByRole("button", { name: "내용 생성 다시 시작" }));
  await waitFor(() => expect(api.startChapters).toHaveBeenCalledTimes(2));
});

it("완료 여부를 확인하지 못한 장을 다시 생성하기 전에 확인을 받는다 (D2b-5a)", async () => {
  function Host() {
    const [current, setCurrent] = useState(emptyDeck());
    return <StructureScreen project={project} deck={current} onDeckChange={setCurrent} onDone={() => {}}
      pollIntervalMs={0} />;
  }
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  mockBatch(batchView([chapterView("c1", "succeeded"), chapterView("c2", "remote_completion_unknown")],
    { state: "failed", outcome: "partial" }), deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }]));
  render(<Host />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  const row2 = await waitFor(() => screen.getByLabelText("2번 장 주제").closest("tr")!);
  await waitFor(() => expect(within(row2).getByText("완료 여부 확인 필요", { exact: false })).toBeInTheDocument());
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  expect(confirm.mock.calls[0][0]).toContain("AI 사용량이 한 번 더 기록될 수 있습니다");
  expect(api.startChapters).toHaveBeenCalledTimes(1);
  confirm.mockRestore();
});

it("화면을 다시 열면 진행 중인 묶음을 이어서 조회하고 끝나면 덱을 다시 읽는다 (D2b-5a)", async () => {
  const deck = deckWith([CH1, CH2], []);
  const running = batchView([chapterView("c1", "succeeded"), chapterView("c2", "running")],
    { state: "running", outcome: null });
  vi.mocked(api.listJobs).mockResolvedValue([running]);
  vi.mocked(api.getJob).mockResolvedValueOnce(running)
    .mockResolvedValueOnce(batchView([chapterView("c1", "succeeded"), chapterView("c2", "succeeded")]));
  const after = deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }, { chapter_id: "c2", slots: BODY }]);
  vi.mocked(api.getDeck).mockResolvedValue(after);
  const onBusyChange = vi.fn();
  const onDeckChange = vi.fn();
  const onDone = vi.fn();
  render(<StructureScreen project={project} deck={deck} onDeckChange={onDeckChange} onDone={onDone}
    onBusyChange={onBusyChange} pollIntervalMs={0} />);
  await waitFor(() => expect(onDeckChange).toHaveBeenLastCalledWith(after));
  expect(onBusyChange.mock.calls[0]).toEqual([true]);
  await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
  expect(onDone).not.toHaveBeenCalled();  // 이 화면에서 등록한 작업이 아니면 편집 탭으로 옮기지 않는다
});

it("끝난 지난 묶음은 실패 요약을 보인다 (D2b-5a)", async () => {
  const deck = deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }]);
  vi.mocked(api.listJobs).mockResolvedValue([batchView([chapterView("c1", "succeeded"),
    chapterView("c2", "failed", { error: FAILED_503 })], { state: "failed", outcome: "partial" })]);
  render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={() => {}} />);
  expect(await screen.findByText(/2장 중 1장을 만들지 못했습니다/)).toBeInTheDocument();
  const row2 = screen.getByLabelText("2번 장 주제").closest("tr")!;
  expect(within(row2).getByText("실패", { exact: false })).toBeInTheDocument();
});

it("생성 중단은 작업 취소를 요청하고 취소 요청 안내를 보인다 (D2b-5a)", async () => {
  vi.mocked(api.cancelJob).mockResolvedValue(batchView([], { state: "cancel_requested" }));
  const running = batchView([chapterView("c1", "running"), chapterView("c2", "queued")], { state: "running", outcome: null });
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  vi.mocked(api.startChapters).mockResolvedValueOnce(running);
  let release: (v: ReturnType<typeof batchView>) => void = () => {};
  vi.mocked(api.getJob).mockResolvedValueOnce(running).mockImplementationOnce(() => new Promise((r) => { release = r; }));
  vi.mocked(api.getDeck).mockResolvedValue(deckWith([CH1, CH2], []));
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}} pollIntervalMs={0} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await userEvent.click(await screen.findByRole("button", { name: "생성 중단" }));
  expect(api.cancelJob).toHaveBeenCalledWith("p1", "job-1");
  expect(await screen.findByText("취소를 요청했습니다. AI가 응답을 멈추면 취소됨으로 바뀝니다.")).toBeInTheDocument();
  release(batchView([chapterView("c1", "cancelled"), chapterView("c2", "cancelled")], { state: "cancelled", outcome: "cancelled" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "승인하고 내용 생성" })).toBeEnabled());
});

it("최초 승인 반영이 412면 승인하려던 구성을 보존한다 (D2a-2)", async () => {
  vi.mocked(api.saveDraft).mockResolvedValue({ ...draftInfo, reason: "conflict" });
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockRejectedValue(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}}
    onConflict={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await waitFor(() => expect(api.saveDraft).toHaveBeenCalledOnce());
  const [, req] = vi.mocked(api.saveDraft).mock.calls[0];
  expect(req.reason).toBe("conflict");
  expect(req.deck.structure.chapters.map((c) => c.id)).toEqual([CH1.id, CH2.id]);
});

it("장 구성 초안을 고치면 창 닫기 경고를 위해 미저장을 알린다 (D2a-2)", async () => {
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  const onDirtyChange = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}}
    onDirtyChange={onDirtyChange} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
});

it("보존도 실패한 승인 구성은 미저장으로 알리고, 다시 승인하기 전에 확인을 받는다 (리뷰 R1)", async () => {
  vi.mocked(api.saveDraft).mockRejectedValue(new ApiError(503, "서버가 응답하지 않습니다."));
  const onDirtyChange = vi.fn();
  vi.mocked(api.generateStructure).mockResolvedValue({
    status: "ok", structure: { chapters: [CH1, CH2] },
    usage: emptyUsage(), raw_text: "", unverified_numbers: [], format_retried: false,
  });
  vi.mocked(api.putDeck).mockRejectedValueOnce(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}}
    onConflict={() => {}} onDirtyChange={onDirtyChange} />);
  await userEvent.click(screen.getByRole("button", { name: "구조안 생성" }));
  await screen.findByDisplayValue("본문");
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  await screen.findByText(/보존도 하지 못했습니다/);
  await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
  await userEvent.click(screen.getByRole("button", { name: "승인하고 내용 생성" }));
  expect(confirm.mock.calls[0][0]).toContain("저장하지 못한 생성 결과");
  expect(screen.getByText(/보존도 하지 못했습니다/)).toBeInTheDocument();
  expect(api.startChapters).not.toHaveBeenCalled();
});

it("결정 질문만 고쳐도 미저장으로 알린다 (리뷰 R16)", async () => {
  const onDirtyChange = vi.fn();
  render(<StructureScreen project={project} deck={emptyDeck()} onDeckChange={() => {}} onDone={() => {}}
    onDirtyChange={onDirtyChange} />);
  await userEvent.type(screen.getByLabelText("보고 질문"), "무엇을 결정하나");
  await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
});

it("시작 전에 취소된 장만 있으면 사용량 누락 단서를 보이지 않고, 시작한 뒤 취소된 장은 보인다 (D2b-5a)", async () => {
  const clue = "(실패한 장의 사용량은 이 합계에 포함되지 않았습니다. 정확한 기록은 프로젝트 폴더의 ai-usage.jsonl)";
  const deck = deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }]);
  vi.mocked(api.listJobs).mockResolvedValueOnce([batchView([
    chapterView("c1", "succeeded", { result: chapterResult(COVER, measuredUsage()) }),
    chapterView("c2", "cancelled")], { state: "cancelled", outcome: "cancelled" })]);
  const first = render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={() => {}} />);
  expect(await screen.findByText(/장 생성 1회/)).toBeInTheDocument();
  expect(screen.queryByText(clue, { exact: false })).toBeNull();
  first.unmount();
  vi.mocked(api.listJobs).mockResolvedValueOnce([batchView([
    chapterView("c1", "succeeded", { result: chapterResult(COVER, measuredUsage()) }),
    chapterView("c2", "cancelled", { started_at: "2026-10-08T10:00:01+09:00" })], { state: "cancelled", outcome: "cancelled" })]);
  render(<StructureScreen project={project} deck={deck} onDeckChange={() => {}} onDone={() => {}} />);
  expect(await screen.findByText(clue, { exact: false })).toBeInTheDocument();
});

const CH3 = { id: "c3", topic: "셋째", conclusion: "", template: "bullet_box" as const, source_refs: [] };

it("실패한 장은 그 장만 새 묶음으로 다시 생성하고, 다른 장이 비어 있으면 편집 탭으로 옮기지 않는다 (D2b-5a)", async () => {
  function Host({ onDone }: { onDone: () => void }) {
    const [current, setCurrent] = useState(deckWith([CH1, CH2, CH3], [{ chapter_id: "c1", slots: COVER }]));
    return <StructureScreen project={project} deck={current} onDeckChange={setCurrent} onDone={onDone} pollIntervalMs={0} />;
  }
  vi.mocked(api.listJobs).mockResolvedValueOnce([batchView([chapterView("c1", "succeeded"),
    chapterView("c2", "failed", { error: FAILED_503 }), chapterView("c3", "interrupted",
      { error: { error_class: null, status: null, detail: null, code: "provider_failed" } })],
  { state: "failed", outcome: "partial" })]);
  mockBatch(batchView([chapterView("c2", "succeeded")], { id: "job-2" }),
    deckWith([CH1, CH2, CH3], [{ chapter_id: "c1", slots: COVER }, { chapter_id: "c2", slots: BODY }]));
  const onDone = vi.fn();
  render(<Host onDone={onDone} />);
  expect(await screen.findByText(/3장 중 2장을 만들지 못했습니다/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "2번 장 다시 생성" }));
  await waitFor(() => expect(screen.getByText(/3장 중 1장을 만들지 못했습니다/)).toBeInTheDocument());
  expect(vi.mocked(api.startChapters).mock.calls[0][1]).toEqual(["c2"]);
  expect(api.putDeck).not.toHaveBeenCalled();  // 장 구성은 이미 저장했다
  expect(onDone).not.toHaveBeenCalled();       // c3가 아직 비어 있다
  // 완료된 장에는 다시 생성 버튼이 없다
  expect(screen.queryByRole("button", { name: "2번 장 다시 생성" })).toBeNull();
});

it("이전 입력 기준 후보는 내용을 볼 수 있고, 구성 계획 보류 장과 고친 초안에는 다시 생성 버튼이 없다 (D2b-5a)", async () => {
  vi.mocked(api.listJobs).mockResolvedValueOnce([batchView([
    chapterView("c1", "failed", { candidate_status: "stale", result: chapterResult(COVER),
      error: { error_class: "base_changed", status: null, detail: null, code: "base_changed" } }),
    chapterView("c2", "interrupted", { error: { error_class: null, status: null, detail: null, code: "held_stale_plan" } })],
  { state: "failed", outcome: "chain_broken" })]);
  render(<StructureScreen project={project} deck={deckWith([CH1, CH2], [])} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(await screen.findByText("후보 보기"));
  expect(screen.getByText("제목")).toBeInTheDocument();  // 후보 슬롯의 글자
  expect(screen.getByRole("button", { name: "1번 장 다시 생성" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "2번 장 다시 생성" })).toBeNull();
  await userEvent.type(screen.getByLabelText("1번 장 주제"), " 수정");
  expect(screen.queryByRole("button", { name: "1번 장 다시 생성" })).toBeNull();
});

it("완료 여부를 모르는 장을 그 장만 다시 생성할 때도 확인을 받는다 (D2b-5a)", async () => {
  vi.mocked(api.listJobs).mockResolvedValueOnce([batchView([chapterView("c1", "succeeded"),
    chapterView("c2", "remote_completion_unknown")], { state: "failed", outcome: "partial" })]);
  render(<StructureScreen project={project} deck={deckWith([CH1, CH2], [{ chapter_id: "c1", slots: COVER }])}
    onDeckChange={() => {}} onDone={() => {}} />);
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
  await userEvent.click(await screen.findByRole("button", { name: "2번 장 다시 생성" }));
  expect(confirm.mock.calls[0][0]).toContain("AI 사용량이 한 번 더 기록될 수 있습니다");
  expect(api.prepareAi).not.toHaveBeenCalled();
  expect(api.startChapters).not.toHaveBeenCalled();
  confirm.mockRestore();
});

it("장 하나 다시 생성의 등록이 412면 충돌로 알린다 (D2b-5a)", async () => {
  vi.mocked(api.listJobs).mockResolvedValueOnce([batchView([chapterView("c1", "failed", { error: FAILED_503 })],
    { state: "failed", outcome: "partial" })]);
  vi.mocked(api.startChapters).mockRejectedValueOnce(new ApiError(412, "다른 창이나 프로그램에서 이 프로젝트가 먼저 저장되었습니다."));
  const onConflict = vi.fn();
  render(<StructureScreen project={project} deck={deckWith([CH1], [])} onDeckChange={() => {}} onDone={() => {}}
    onConflict={onConflict} />);
  await userEvent.click(await screen.findByRole("button", { name: "1번 장 다시 생성" }));
  await waitFor(() => expect(onConflict).toHaveBeenCalled());
  expect(screen.getByRole("alert")).toHaveTextContent("먼저 저장되었습니다");
});

it("이전 입력 기준 후보를 버리면 후보 표시가 사라지고 다시 생성은 남는다 (D2b-4 리뷰 R5)", async () => {
  const staleRow = chapterView("c1", "failed", { candidate_status: "stale", result: chapterResult(COVER),
    error: { error_class: "base_changed", status: null, detail: null, code: "base_changed" } });
  vi.mocked(api.listJobs).mockResolvedValueOnce([batchView([staleRow], { state: "failed", outcome: "chain_broken" })]);
  vi.mocked(api.dismissChapterCandidate).mockResolvedValueOnce(batchView([{ ...staleRow, candidate_status: "dismissed" }],
    { state: "failed", outcome: "chain_broken" }));
  render(<StructureScreen project={project} deck={deckWith([CH1], [])} onDeckChange={() => {}} onDone={() => {}} />);
  await userEvent.click(await screen.findByRole("button", { name: "1번 장 후보 버리기" }));
  expect(api.dismissChapterCandidate).toHaveBeenCalledWith("p1", "job-1", "c1");
  await waitFor(() => expect(screen.queryByText("후보 보기")).toBeNull());
  expect(screen.queryByRole("button", { name: "1번 장 후보 버리기" })).toBeNull();
  expect(screen.getByRole("button", { name: "1번 장 다시 생성" })).toBeInTheDocument();
});
