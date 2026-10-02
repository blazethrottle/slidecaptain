// Existing AI diagram replacement uses the exact confirmed server transaction.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { api, ApiError, type Deck, type DiagramGenerationResult, type DocumentChangeBasis,
  type DocumentChangePreview, type RenderPlan } from "../api/client";
import { deferred } from "../test/fixtures";
import { emptyUsage } from "../test/usage";
import { DiagramAuthoringDialog } from "./DiagramAuthoringDialog";
import { createDiagramDraft, editDiagramDraft } from "./diagramDraft";

vi.mock("../api/client", async original => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, generateDiagram: vi.fn(), measure: vi.fn(), putDeck: vi.fn(),
    reconcileDiagramStory: vi.fn(), getDocumentChangeBasis: vi.fn(), previewDocumentChange: vi.fn(), applyDocumentChange: vi.fn() } };
});
const fresh = () => structuredClone(fixture.deck) as Deck;
const basis: DocumentChangeBasis = { base_etag: '"old"', sources_fingerprint: "b".repeat(64), evidence_fingerprints: {} };
function generation(): DiagramGenerationResult {
  const slide = fresh().slides.find(s => s.slots.template === "diagram")!;
  if (slide.slots.template !== "diagram") throw new Error("fixture");
  const diagram = structuredClone(slide.slots.diagram); diagram.nodes[0].content = "AI 교체 후보";
  return { status: "ok", diagram, raw_text: "", unverified_numbers: [], format_retried: false, usage: emptyUsage(),
    base_etag: basis.base_etag, sources_fingerprint: basis.sources_fingerprint };
}
function confirmation(candidate: Deck = fresh()): DocumentChangePreview {
  return { rule_version: "document-change-v1", reason: "document_replacement", base_fingerprint: "a".repeat(64),
    sources_fingerprint: basis.sources_fingerprint, candidate_fingerprint: "c".repeat(64), candidate,
    losses: [{ id: "d".repeat(64), path: "slides/synthetic-flow", kind: "replaced", before: { text: "원래 도식" }, after: { text: "AI 교체 후보" } },
      { id: "e".repeat(64), path: "chapters/synthetic-flow", kind: "replaced", before: { text: "원래 장" }, after: { text: "확인된 장" } }],
    confirmation_token: "f".repeat(64), final_export_allowed: false, notice: "독립 검수 전 교체 후보" };
}
function open(props: Partial<React.ComponentProps<typeof DiagramAuthoringDialog>> = {}) {
  const deck = fresh();
  const defaults = { projectName: "synthetic", deck, initialDraft: editDiagramDraft(deck, "synthetic-flow"),
    onApply: vi.fn(), onCancel: vi.fn(), onBusyChange: vi.fn(), onConflict: vi.fn(), flushBeforeCheck: vi.fn().mockResolvedValue(true) };
  const all = { ...defaults, ...props };
  return { ...render(<DiagramAuthoringDialog {...all} />), props: all, ...defaults };
}
beforeEach(() => {
  vi.mocked(api.generateDiagram).mockResolvedValue(generation());
  vi.mocked(api.reconcileDiagramStory).mockImplementation(async (_name, request) => request.deck);
  vi.mocked(api.measure).mockResolvedValue(structuredClone(fixture.render_plan) as RenderPlan);
  vi.mocked(api.getDocumentChangeBasis).mockResolvedValue(basis);
  vi.mocked(api.previewDocumentChange).mockImplementation(async (_name, request) => confirmation(request.candidate));
  vi.mocked(api.applyDocumentChange).mockImplementation(async (_name, request) => request.candidate);
});
async function loadCandidate() {
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 교체 후보 생성" }));
  await screen.findByRole("region", { name: "AI 도식 후보 검토" });
  await userEvent.click(screen.getByRole("button", { name: "작성 폼에 불러오기" }));
}
async function checkCandidate() {
  await loadCandidate();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  return screen.findByRole("region", { name: "도식 교체 전후 확인" });
}
async function confirmAll() {
  for (const checkbox of screen.getAllByLabelText("이 변경을 확인했습니다")) await userEvent.click(checkbox);
}

it("기존 도식 mode replace·프로젝트 실측·전후 모든 변경 확인 후 저장된 후보만 인계한다", async () => {
  const ui = open(); await checkCandidate();
  expect(api.generateDiagram).toHaveBeenCalledWith("synthetic", expect.objectContaining({ mode: "replace", chapter_id: "synthetic-flow",
    role: "answer", claim_ids: ["claim"] }));
  expect(api.measure).toHaveBeenCalledWith(expect.any(Object), "synthetic");
  expect(screen.getByRole("region", { name: "도식 교체 전후 확인" })).toHaveTextContent("원래 도식");
  expect(api.applyDocumentChange).not.toHaveBeenCalled();
  await userEvent.click(screen.getAllByLabelText("이 변경을 확인했습니다")[0]);
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  await userEvent.click(screen.getAllByLabelText("이 변경을 확인했습니다")[1]);
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  await waitFor(() => expect(ui.onApply).toHaveBeenCalledTimes(1));
  expect(ui.onApply.mock.calls[0].slice(1)).toEqual([ui.deck, "synthetic-flow", true]);
  expect(api.applyDocumentChange).toHaveBeenCalledWith("synthetic", { candidate: ui.onApply.mock.calls[0][0],
    expected_source_fingerprint: basis.sources_fingerprint, confirmation_token: confirmation().confirmation_token,
    acknowledged_loss_ids: confirmation().losses.map(loss => loss.id) }, basis.base_etag);
  expect(api.putDeck).not.toHaveBeenCalled();
});

it("원래 근거 참조 누락으로 서버 후보가 거절되면 폼을 보존하고 덮어쓰지 않는다", async () => {
  vi.mocked(api.previewDocumentChange).mockRejectedValue(new ApiError(422, "기존 근거 참조를 보존해야 합니다"));
  const ui = open(); await loadCandidate();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("기존 근거 참조");
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 교체 후보");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(ui.onApply).not.toHaveBeenCalled(); expect(api.applyDocumentChange).not.toHaveBeenCalled();
});

it.each(["basis", "preview"])("%s 늦은 응답은 새 폼 입력의 검사 결과로 사용하지 않는다", async stage => {
  const pendingBasis = deferred<DocumentChangeBasis>(), pendingPreview = deferred<DocumentChangePreview>();
  if (stage === "basis") vi.mocked(api.getDocumentChangeBasis).mockReturnValue(pendingBasis.promise);
  else vi.mocked(api.previewDocumentChange).mockReturnValue(pendingPreview.promise);
  const ui = open(); await loadCandidate();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(stage === "basis" ? api.getDocumentChangeBasis : api.previewDocumentChange).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "새 수동 입력" } });
  await act(async () => { if (stage === "basis") pendingBasis.resolve(basis); else pendingPreview.resolve(confirmation()); });
  expect(screen.queryByRole("region", { name: "도식 교체 전후 확인" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("새 수동 입력");
  if (stage === "basis") expect(api.previewDocumentChange).not.toHaveBeenCalled();
  expect(ui.onApply).not.toHaveBeenCalled();
});

it("적용 응답이 새 저장본 뒤에 도착하면 이전 후보를 인계하지 않는다", async () => {
  const pending = deferred<Deck>(); vi.mocked(api.applyDocumentChange).mockReturnValue(pending.promise);
  const ui = open(); await checkCandidate(); await confirmAll();
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  ui.rerender(<DiagramAuthoringDialog {...ui.props} deck={fresh()} />);
  await act(async () => pending.resolve(confirmation().candidate));
  expect(ui.onApply).not.toHaveBeenCalled();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 교체 후보");
});

it("적용412는 입력과 전후 후보를 보존하면서 추가 요청을 차단한다", async () => {
  vi.mocked(api.applyDocumentChange).mockRejectedValue(new ApiError(412, "다른 창이 먼저 저장"));
  const ui = open(); await checkCandidate(); await confirmAll();
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  await waitFor(() => expect(ui.onConflict).toHaveBeenCalled());
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 교체 후보");
  expect(screen.getByRole("region", { name: "도식 교체 전후 확인" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "AI 도식 교체 후보 생성" })).toBeDisabled();
  expect(ui.onApply).not.toHaveBeenCalled();
});

it("미리보기412도 입력을 보존하며 기준을 다시 열기 전 생성을 차단한다", async () => {
  vi.mocked(api.previewDocumentChange).mockRejectedValue(new ApiError(412, "저장본 변경"));
  const ui = open(); await loadCandidate();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(ui.onConflict).toHaveBeenCalled());
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 교체 후보");
  expect(screen.getByRole("button", { name: "AI 도식 교체 후보 생성" })).toBeDisabled();
});

it("토큰 거절422는 폼을 유지하고 이전 확인을 무효화해 새 배치·후보 확인을 요구한다", async () => {
  vi.mocked(api.applyDocumentChange).mockRejectedValueOnce(new ApiError(422, "후보를 다시 미리 보세요"));
  const ui = open(); await checkCandidate(); await confirmAll();
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("다시 미리");
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 교체 후보");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(ui.onApply).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(api.previewDocumentChange).toHaveBeenCalledTimes(2));
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
});

it("적용 중 unmount되어도 실제 요청이 끝날 때까지 소유한 busy를 해제하지 않는다", async () => {
  const pending = deferred<Deck>(); vi.mocked(api.applyDocumentChange).mockReturnValue(pending.promise);
  const ui = open(); await checkCandidate(); await confirmAll();
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  expect(ui.onBusyChange).toHaveBeenLastCalledWith(true);
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" })); ui.unmount();
  expect(ui.onBusyChange).toHaveBeenLastCalledWith(true);
  await act(async () => pending.resolve(confirmation().candidate));
  expect(ui.onBusyChange).toHaveBeenLastCalledWith(false);
  expect(ui.onApply).not.toHaveBeenCalled();
});

it("적용 중 폼 편집·닫기·Escape를 차단하고 확정된 후보의 저장 응답을 인계한다", async () => {
  const pending = deferred<Deck>(); vi.mocked(api.applyDocumentChange).mockReturnValue(pending.promise);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const ui = open(); await checkCandidate(); await confirmAll();
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  expect(screen.getByRole("region", { name: "도식 내용 입력" })).toHaveAttribute("inert");
  expect(screen.getByRole("button", { name: "변경 버리고 닫기" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "입력과 배치 확인" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "저장 중 입력을 바꾸려 함" } });
  fireEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 교체 후보");
  expect(confirm).not.toHaveBeenCalled(); expect(ui.onCancel).not.toHaveBeenCalled();
  expect(api.applyDocumentChange).toHaveBeenCalledTimes(1);
  expect(ui.onBusyChange).toHaveBeenLastCalledWith(true);
  const saved = vi.mocked(api.applyDocumentChange).mock.calls[0][1].candidate;
  await act(async () => pending.resolve(saved));
  expect(ui.onApply).toHaveBeenCalledWith(saved, ui.deck, "synthetic-flow", true);
  expect(ui.onBusyChange).toHaveBeenLastCalledWith(false);
});

it("새 수동 도식은 기존 확인 경로를 사용하며 문서 교체 API를 호출하지 않는다", async () => {
  const deck = fresh(); const draft = { ...editDiagramDraft(deck, "synthetic-flow"), id: createDiagramDraft(deck).id, isNew: true };
  const plan = structuredClone(fixture.render_plan) as RenderPlan;
  plan.slides = plan.slides.map(slide => slide.diagram ? { ...slide, chapter_id: draft.id } : slide);
  vi.mocked(api.measure).mockResolvedValue(plan);
  const ui = open({ deck, initialDraft: draft });
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  expect(ui.onApply).toHaveBeenCalledWith(expect.any(Object), deck, draft.id);
  expect(api.getDocumentChangeBasis).not.toHaveBeenCalled(); expect(api.applyDocumentChange).not.toHaveBeenCalled();
});
