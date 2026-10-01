import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { api, AiConsentDeclined, ApiError, type Deck, type DiagramGenerationResult, type RenderPlan } from "../api/client";
import { deferred } from "../test/fixtures";
import { emptyUsage } from "../test/usage";
import { DiagramAuthoringDialog } from "./DiagramAuthoringDialog";
import { createDiagramDraft, editDiagramDraft } from "./diagramDraft";

vi.mock("../api/client", async (original) => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, generateDiagram: vi.fn(), measure: vi.fn(), putDeck: vi.fn(), reconcileDiagramStory: vi.fn() } };
});
const fresh = () => structuredClone(fixture.deck) as Deck;
function response(): DiagramGenerationResult {
  const slide = fresh().slides.find(s => s.slots.template === "diagram")!;
  if (slide.slots.template !== "diagram") throw new Error("fixture");
  const diagram = { ...slide.slots.diagram, id: "diagram-1" };
  diagram.nodes[0].content = "AI 접수 후보";
  return { status: "ok", diagram, raw_text: "synthetic response", unverified_numbers: [], format_retried: false,
    usage: { ...emptyUsage(), calls: 1, unmeasured_calls: 1 }, base_etag: '"base"', sources_fingerprint: "sources" };
}
function open(props: Partial<React.ComponentProps<typeof DiagramAuthoringDialog>> = {}) {
  const deck = fresh();
  const draft = { ...editDiagramDraft(deck, "synthetic-flow"), id: createDiagramDraft(deck).id, isNew: true, topic: "사용자 제목" };
  const onApply = vi.fn(), onCancel = vi.fn(), onBusyChange = vi.fn(), flushBeforeCheck = vi.fn().mockResolvedValue(true);
  const fullProps = { projectName: "synthetic", deck, initialDraft: draft, onApply, onCancel, onBusyChange, flushBeforeCheck, ...props };
  const view = render(<DiagramAuthoringDialog {...fullProps} />);
  return { ...view, props: fullProps, draft, deck, onApply, onCancel, onBusyChange, flushBeforeCheck };
}
beforeEach(() => {
  vi.mocked(api.generateDiagram).mockReset().mockResolvedValue(response());
  vi.mocked(api.putDeck).mockClear();
  vi.mocked(api.measure).mockReset();
  vi.mocked(api.reconcileDiagramStory).mockReset().mockImplementation(async (_name, req) => req.deck);
});

it("새 도식과 보고 계획이 함께 있을 때에만 AI 후보를 요청할 수 있다", () => {
  const deck = fresh();
  const view = open({ initialDraft: editDiagramDraft(deck, "synthetic-flow") });
  expect(screen.queryByRole("button", { name: "AI 도식 초안 생성" })).not.toBeInTheDocument();
  view.unmount();
  deck.structure.story_plan = null;
  open({ deck });
  expect(screen.queryByRole("button", { name: "AI 도식 초안 생성" })).not.toBeInTheDocument();
});

it("AI 후보는 폼과 분리해 근거와 조건을 보이고 불러오기 뒤 기존 확인과 적용을 거친다", async () => {
  const { onApply, draft, flushBeforeCheck } = open();
  const plan = structuredClone(fixture.render_plan) as RenderPlan;
  plan.slides = plan.slides.map(s => s.diagram ? { ...s, chapter_id: draft.id } : s);
  vi.mocked(api.measure).mockResolvedValue(plan);
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  const candidate = await screen.findByRole("region", { name: "AI 도식 후보 검토" });
  expect(flushBeforeCheck).toHaveBeenCalledOnce();
  expect(api.generateDiagram).toHaveBeenCalledWith("synthetic", {
    chapter_id: draft.id, topic: "사용자 제목", role: "answer", claim_ids: ["claim"], instructions: "",
  });
  expect(within(candidate).getByText("AI 접수 후보")).toBeInTheDocument();
  expect(within(candidate).getByText("효과와 비용은 확인하지 않았다.")).toBeInTheDocument();
  expect(within(candidate).getByText(/합성 운영에서는 접수 후/)).toBeInTheDocument();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(api.putDeck).not.toHaveBeenCalled();
  expect(onApply).not.toHaveBeenCalled();
  expect(screen.getByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "작성 폼에 불러오기" }));
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 접수 후보");
  expect(screen.getByLabelText("도식 제목")).toHaveValue("사용자 제목");
  expect(screen.getByLabelText("도식 장 보고 역할")).toHaveValue("answer");
  expect(screen.getByLabelText("보고 계획 주장 claim")).toBeChecked();
  expect(onApply).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  expect(onApply).toHaveBeenCalledOnce();
});

it("기존 편집을 저장하지 못하면 AI를 호출하지 않고 작성 입력을 보존한다", async () => {
  open({ flushBeforeCheck: vi.fn().mockResolvedValue(false) });
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("저장하지 못했습니다");
  expect(api.generateDiagram).not.toHaveBeenCalled();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
});

it("동의 취소는 오류 대신 안내를 보이고 호출 잠금을 해제한다", async () => {
  vi.mocked(api.generateDiagram).mockRejectedValue(new AiConsentDeclined());
  const { onBusyChange } = open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  expect(await screen.findByText(/전송을 취소했습니다/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
  expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
});

it("형식 오류여도 원문과 사용량을 보이고 불러오기를 허용하지 않는다", async () => {
  vi.mocked(api.generateDiagram).mockResolvedValue({ ...response(), status: "format_error", diagram: null, format_retried: true });
  open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("형식에 맞게 읽지 못했습니다");
  expect(screen.getByText("synthetic response")).toBeInTheDocument();
  expect(screen.getByText(/AI 사용량: 호출 1회/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "작성 폼에 불러오기" })).not.toBeInTheDocument();
});

it("입력 변경은 늦은 후보를 무효화하되 응답이 끝날 때까지 호출 잠금을 유지한다", async () => {
  const pending = deferred<DiagramGenerationResult>();
  vi.mocked(api.generateDiagram).mockReturnValue(pending.promise);
  const { onBusyChange } = open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "계속 작성한 입력" } });
  expect(screen.getByRole("button", { name: "AI 도식 초안 생성" })).toBeDisabled();
  expect(onBusyChange.mock.calls).toEqual([[true]]);
  await act(async () => pending.resolve(response()));
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("계속 작성한 입력");
  expect(screen.queryByRole("button", { name: "작성 폼에 불러오기" })).not.toBeInTheDocument();
  expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
});

it("닫은 창의 응답은 후보를 적용하지 않고 응답 완료 때 소유한 잠금만 해제한다", async () => {
  const pending = deferred<DiagramGenerationResult>();
  vi.mocked(api.generateDiagram).mockReturnValue(pending.promise);
  const { onBusyChange, onApply, onCancel, unmount } = open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  expect(onCancel).toHaveBeenCalledOnce(); unmount();
  expect(onBusyChange.mock.calls).toEqual([[true]]);
  await act(async () => pending.resolve(response()));
  expect(onApply).not.toHaveBeenCalled();
  expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
});

it.each(["deck", "blocked"])("%s 변경은 도착한 후보의 불러오기를 막는다", async (change) => {
  const view = open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  await screen.findByRole("button", { name: "작성 폼에 불러오기" });
  view.rerender(<DiagramAuthoringDialog {...view.props} {...(change === "deck" ? { deck: structuredClone(view.deck) } : { blocked: true })} />);
  expect(screen.queryByRole("button", { name: "작성 폼에 불러오기" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
});

it("AI 응답의 412는 충돌로 전달하고 현재 폼과 Deck을 보존한다", async () => {
  vi.mocked(api.generateDiagram).mockRejectedValue(new ApiError(412, "다른 창에서 저장되었습니다."));
  const onConflict = vi.fn(); const { onApply } = open({ onConflict });
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  await waitFor(() => expect(onConflict).toHaveBeenCalledWith("다른 창에서 저장되었습니다."));
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(api.putDeck).not.toHaveBeenCalled(); expect(onApply).not.toHaveBeenCalled();
});

it("지원하지 않는 관계 후보는 수동 배치 검사에서 멈추고 후보 내용과 Deck을 보존한다", async () => {
  const generated = response();
  generated.diagram!.edges[0].to_node_id = generated.diagram!.nodes[2].id;
  vi.mocked(api.generateDiagram).mockResolvedValue(generated);
  vi.mocked(api.measure).mockRejectedValue(new ApiError(422, "한 줄의 인접한 노드 연결만 지원합니다."));
  const { onApply } = open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  await userEvent.click(await screen.findByRole("button", { name: "작성 폼에 불러오기" }));
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("인접한 노드 연결");
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("AI 접수 후보");
  expect(screen.getByLabelText("관계 1 대상")).toHaveValue(generated.diagram!.nodes[2].id);
  expect(onApply).not.toHaveBeenCalled(); expect(api.putDeck).not.toHaveBeenCalled();
});

it("기존 편집 저장을 기다리다 입력이 바뀌면 AI 전송을 시작하지 않고 잠금을 해제한다", async () => {
  const saving = deferred<boolean>();
  const { onBusyChange } = open({ flushBeforeCheck: () => saving.promise });
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  expect(api.generateDiagram).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("AI 도식 지시사항"), { target: { value: "바꾼 지시" } });
  await act(async () => saving.resolve(true));
  expect(api.generateDiagram).not.toHaveBeenCalled();
  expect(screen.getByLabelText("AI 도식 지시사항")).toHaveValue("바꾼 지시");
  expect(onBusyChange.mock.calls).toEqual([[true], [false]]);
});

it("도착한 후보가 있어도 제목이나 지시를 바꾸면 기존 후보를 불러올 수 없다", async () => {
  open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  await screen.findByRole("button", { name: "작성 폼에 불러오기" });
  fireEvent.change(screen.getByLabelText("도식 제목"), { target: { value: "새 판단으로 바꾼 제목" } });
  expect(screen.queryByRole("button", { name: "작성 폼에 불러오기" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
});

it.each(["deck", "blocked"])("응답 대기 중 %s 변경이 있으면 늦은 후보를 표시하거나 적용하지 않는다", async (change) => {
  const pending = deferred<DiagramGenerationResult>();
  vi.mocked(api.generateDiagram).mockReturnValue(pending.promise);
  const view = open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  view.rerender(<DiagramAuthoringDialog {...view.props} {...(change === "deck" ? { deck: structuredClone(view.deck) } : { blocked: true })} />);
  await act(async () => pending.resolve(response()));
  expect(screen.queryByRole("button", { name: "작성 폼에 불러오기" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(view.onApply).not.toHaveBeenCalled();
  expect(view.onBusyChange.mock.calls).toEqual([[true], [false]]);
});

it("입력을 바꾼 뒤 도착한 412도 충돌로 전달하고 새 요청을 차단한다", async () => {
  const pending = deferred<DiagramGenerationResult>();
  vi.mocked(api.generateDiagram).mockReturnValue(pending.promise);
  const onConflict = vi.fn(); open({ onConflict });
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "응답 중 작성한 입력" } });
  await act(async () => pending.reject(new ApiError(412, "다른 창 저장")));
  expect(onConflict).toHaveBeenCalledWith("다른 창 저장");
  expect(screen.getByRole("button", { name: "AI 도식 초안 생성" })).toBeDisabled();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("응답 중 작성한 입력");
});

it("부모 콜백이 바뀌어도 호출 시작 때 얻은 잠금의 소유자에게만 해제를 알린다", async () => {
  const pending = deferred<DiagramGenerationResult>();
  vi.mocked(api.generateDiagram).mockReturnValue(pending.promise);
  const view = open();
  await userEvent.click(screen.getByRole("button", { name: "AI 도식 초안 생성" }));
  const replacement = vi.fn();
  view.rerender(<DiagramAuthoringDialog {...view.props} onBusyChange={replacement} />);
  await act(async () => pending.resolve(response()));
  expect(view.onBusyChange.mock.calls).toEqual([[true], [false]]);
  expect(replacement).not.toHaveBeenCalled();
});
