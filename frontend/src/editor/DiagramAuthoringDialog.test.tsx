import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../backend/tests/fixtures/q3b-project.json";
import { api, ApiError, type Deck, type RenderPlan } from "../api/client";
import { DiagramAuthoringDialog } from "./DiagramAuthoringDialog";
import { createDiagramDraft, diagramCandidate, diagramInputErrors, editDiagramDraft } from "./diagramDraft";

vi.mock("../api/client", async (original) => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, measure: vi.fn(), putDeck: vi.fn(), reconcileDiagramStory: vi.fn() } };
});
const fresh = () => structuredClone(fixture.deck) as Deck;
const chapterId = "synthetic-flow";
const plan = () => structuredClone(fixture.render_plan) as RenderPlan;
function open(deck = fresh()) {
  const onApply = vi.fn();
  const onCancel = vi.fn();
  const draft = editDiagramDraft(deck, chapterId);
  vi.mocked(api.reconcileDiagramStory).mockImplementation(async (_name, req) => req.deck);
  const result = render(<DiagramAuthoringDialog projectName="synthetic" deck={deck} initialDraft={draft}
    onApply={onApply} onCancel={onCancel} />);
  return { ...result, deck, draft, onApply, onCancel };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

function withOtherAnswer() {
  const deck = fresh();
  const draft = { ...editDiagramDraft(deck, chapterId), id: createDiagramDraft(deck).id,
    isNew: true, topic: "다른 답변 도식" };
  const candidate = diagramCandidate(deck, draft);
  candidate.structure.story_plan!.chapters.push({ chapter_id: draft.id, role: "answer", claim_ids: ["claim"] });
  return candidate;
}

it("새 장은 충돌 없는 ID로 추가하고 기존 내용과 장부를 보존한다", () => {
  const deck = fresh();
  const draft = createDiagramDraft(deck);
  draft.topic = "새 제안";
  draft.nodes[0].content = "시작";
  draft.nodes[1].content = "확인";
  draft.edges[0].label = "확인 제안";
  const candidate = diagramCandidate(deck, draft);
  expect(candidate.structure.chapters).toHaveLength(deck.structure.chapters.length + 1);
  expect(candidate.slides.slice(0, -1)).toEqual(deck.slides);
  expect(candidate.structure.story_plan).toBe(deck.structure.story_plan);
  expect(createDiagramDraft(candidate).id).not.toBe(draft.id);
  expect(deck).toEqual(fixture.deck);
});

it("수정 후보는 다른 장과 근거/계획 fingerprint를 보존한다", () => {
  const deck = fresh();
  const draft = editDiagramDraft(deck, chapterId);
  draft.nodes[0].content = "수정 접수";
  draft.topic = "새 제목";
  const candidate = diagramCandidate(deck, draft);
  expect(candidate.structure.story_plan).toBe(deck.structure.story_plan);
  expect(candidate.slides[1]).toBe(deck.slides[1]);
  expect(candidate.structure.chapters[1].topic).toBe("새 제목");
  expect(deck).toEqual(fixture.deck);
});

it("보고 계획이 있으면 역할과 주장을 연결 확인 API에 함께 보낸다", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan());
  vi.mocked(api.reconcileDiagramStory).mockImplementation(async (_name, req) => req.deck);
  open(withOtherAnswer());
  await userEvent.selectOptions(screen.getByLabelText("도식 장 보고 역할"), "evidence");
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(api.reconcileDiagramStory).toHaveBeenCalledWith("synthetic", expect.objectContaining({
    chapter_id: chapterId, role: "evidence", claim_ids: ["claim"],
  })));
  expect(api.measure).toHaveBeenCalled();
});

it("다른 답변 장에 없는 핵심 주장의 역할과 연결 제약을 입력 전에 설명한다", () => {
  open();
  const role = screen.getByLabelText("도식 장 보고 역할");
  expect(role).toHaveAccessibleDescription(/다른 답변 장/);
  expect(within(role).getByRole("option", { name: "답변" })).toBeEnabled();
  for (const name of ["맥락", "근거", "위험", "행동"]) {
    expect(within(role).getByRole("option", { name })).toBeDisabled();
  }
  expect(screen.getByLabelText("보고 계획 주장 claim")).toBeChecked();
  expect(screen.getByLabelText("보고 계획 주장 claim")).toBeDisabled();
  expect(screen.getByText("답변 연결 유지 필요")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "입력과 배치 확인" })).toBeEnabled();
});

it("같은 핵심 주장이 다른 답변 장에도 있으면 역할과 주장 선택을 제한하지 않는다", () => {
  open(withOtherAnswer());
  const role = screen.getByLabelText("도식 장 보고 역할");
  expect(within(role).getByRole("option", { name: "근거" })).toBeEnabled();
  expect(screen.getByLabelText("보고 계획 주장 claim")).toBeEnabled();
  expect(screen.queryByText("답변 연결 유지 필요")).not.toBeInTheDocument();
});

it.each(["context", "evidence", "risk", "action"] as const)(
  "다른 %s 장의 연결은 답변 역할의 연결을 대신하지 않는다", (role) => {
    const deck = withOtherAnswer();
    deck.structure.story_plan!.chapters[1].role = role;
    open(deck);
    expect(screen.getByLabelText("보고 계획 주장 claim")).toBeDisabled();
  },
);

it("답변 장이 여럿이어도 각 핵심 주장을 누가 다루는지 검사한다", () => {
  const deck = withOtherAnswer();
  const story = deck.structure.story_plan!;
  story.claims.push({ ...story.claims[0], id: "second", statement: "검토 뒤 결과를 확인한다." });
  story.answer_claim_ids.push("second");
  story.chapters[0].claim_ids.push("second");
  open(deck);
  expect(screen.getByLabelText("보고 계획 주장 claim")).toBeEnabled();
  expect(screen.getByLabelText("보고 계획 주장 second")).toBeDisabled();
  const role = screen.getByLabelText("도식 장 보고 역할");
  expect(within(role).getByRole("option", { name: "근거" })).toBeDisabled();
});

it("다른 답변 장들이 핵심 주장을 나누어 모두 맡으면 도식 역할을 바꿀 수 있다", () => {
  const deck = withOtherAnswer();
  const story = deck.structure.story_plan!;
  story.claims.push({ ...story.claims[0], id: "second", statement: "결과를 확인한다." });
  story.answer_claim_ids.push("second");
  story.chapters[0].claim_ids.push("second");
  const addedDraft = { ...editDiagramDraft(deck, chapterId), id: createDiagramDraft(deck).id,
    isNew: true, topic: "두 번째 주장을 맡는 답변" };
  const candidate = diagramCandidate(deck, addedDraft);
  candidate.structure.story_plan!.chapters.push({ chapter_id: addedDraft.id, role: "answer", claim_ids: ["second"] });
  open(candidate);
  const role = screen.getByLabelText("도식 장 보고 역할");
  expect(within(role).getByRole("option", { name: "근거" })).toBeEnabled();
  expect(screen.getByLabelText("보고 계획 주장 claim")).toBeEnabled();
  expect(screen.getByLabelText("보고 계획 주장 second")).toBeEnabled();
  expect(screen.queryByText("답변 연결 유지 필요")).not.toBeInTheDocument();
});

it.each(["role", "claim"])("이미 %s 연결이 잘못된 초안은 입력을 보존하고 요청 전에 차단한다", async (kind) => {
  const deck = fresh();
  const story = deck.structure.story_plan!;
  story.claims.push({ ...story.claims[0], id: "extra", statement: "확인 후 안내한다." });
  story.chapters[0].claim_ids.push("extra");
  const draft = editDiagramDraft(deck, chapterId);
  if (kind === "role") draft.storyRole = "evidence";
  else draft.claimIds = ["extra"];
  const flushBeforeCheck = vi.fn().mockResolvedValue(true);
  const onApply = vi.fn();
  render(<DiagramAuthoringDialog projectName="synthetic" deck={deck} initialDraft={draft}
    onApply={onApply} onCancel={vi.fn()} flushBeforeCheck={flushBeforeCheck} />);
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/핵심 답변/);
  expect(flushBeforeCheck).not.toHaveBeenCalled();
  expect(api.reconcileDiagramStory).not.toHaveBeenCalled();
  expect(api.measure).not.toHaveBeenCalled();
  expect(onApply).not.toHaveBeenCalled();
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
  if (kind === "role") {
    expect(screen.getByLabelText("도식 장 보고 역할")).toHaveValue("evidence");
    await userEvent.selectOptions(screen.getByLabelText("도식 장 보고 역할"), "answer");
  } else {
    expect(screen.getByLabelText("보고 계획 주장 claim")).not.toBeChecked();
    expect(screen.getByLabelText("보고 계획 주장 claim")).toBeEnabled();
    await userEvent.click(screen.getByLabelText("보고 계획 주장 claim"));
  }
  vi.mocked(api.reconcileDiagramStory).mockImplementation(async (_name, req) => req.deck);
  vi.mocked(api.measure).mockResolvedValue(plan());
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
});

it("새 도식과 계획 없는 도식에는 기존 핵심 답변 제약을 추가하지 않는다", () => {
  const deck = fresh();
  const draft = createDiagramDraft(deck);
  draft.topic = "새 도식";
  draft.storyRole = "evidence";
  draft.claimIds = ["claim"];
  draft.nodes.forEach((node, i) => { node.content = `새 항목 ${i}`; });
  draft.edges[0].label = "제안";
  expect(diagramInputErrors(draft, deck.structure.story_plan)).toEqual([]);
  draft.storyRole = "";
  draft.claimIds = [];
  expect(diagramInputErrors(draft)).toEqual([]);
});

it("보고 계획 연결을 선택하지 않으면 도식 배치 확인을 요청하지 않는다", async () => {
  const deck = fresh();
  const draft = editDiagramDraft(deck, chapterId);
  draft.storyRole = "";
  draft.claimIds = [];
  vi.mocked(api.reconcileDiagramStory).mockClear();
  vi.mocked(api.measure).mockClear();
  render(<DiagramAuthoringDialog projectName="synthetic" deck={deck} initialDraft={draft}
    onApply={vi.fn()} onCancel={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(screen.getByRole("alert")).toHaveTextContent("보고 계획 연결 역할을 선택해 주세요");
  expect(api.reconcileDiagramStory).not.toHaveBeenCalled();
  expect(api.measure).not.toHaveBeenCalled();
});

it("사실 노드의 근거가 없으면 검사 요청과 적용을 막는다", async () => {
  const { onApply } = open();
  await userEvent.click(screen.getByLabelText("항목 1 근거 e1"));
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(screen.getByRole("alert")).toHaveTextContent("항목 1: 사실에는 근거가 필요합니다");
  expect(api.measure).not.toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();
  expect(onApply).not.toHaveBeenCalled();
});

it("발췌문을 보여 주고 선택한 관계 근거를 후보에 연결한다", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan());
  const { onApply } = open();
  expect(screen.getAllByText("합성 도식 자료.md (3~3행)").length).toBeGreaterThan(0);
  expect(screen.getAllByText(/합성 운영에서는 접수 후 요청을 검토/).length).toBeGreaterThan(0);
  await userEvent.click(screen.getByLabelText("관계 1 근거 e1"));
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "도식 적용" }));
  const candidate = onApply.mock.calls[0][0] as Deck;
  const slots = candidate.slides[0].slots;
  expect(slots.template === "diagram" && slots.diagram.edges[0].evidence_ids).toEqual(["e3", "e1"]);
  expect(api.putDeck).not.toHaveBeenCalled();
});

it("검사 후 입력을 바꾸면 기존 성공을 적용할 수 없다", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan());
  open();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "수정 접수" } });
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(screen.queryByRole("group", { name: "도식 미리보기" })).not.toBeInTheDocument();
});

it("검사 중 입력이 바뀌면 늦은 성공 응답을 버린다", async () => {
  const pending = deferred<RenderPlan>();
  vi.mocked(api.measure).mockReturnValue(pending.promise);
  open();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "수정 접수" } });
  await act(async () => pending.resolve(plan()));
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
});

it("서버의 배치 실패를 표시하고 저장과 적용을 하지 않는다", async () => {
  vi.mocked(api.measure).mockRejectedValue(new ApiError(422, "한 줄의 인접한 노드 연결만 지원합니다."));
  const { onApply } = open();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("인접한 노드 연결");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  expect(onApply).not.toHaveBeenCalled();
  expect(api.putDeck).not.toHaveBeenCalled();
});

it("확인한 대상 도식이 없는 응답으로 적용을 허용하지 않는다", async () => {
  vi.mocked(api.measure).mockResolvedValue({ ...plan(), slides: [] });
  open();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("도식 미리보기를 확인하지 못했습니다");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
});

it("원본 덱이 달라지면 작성 내용을 남기고 적용을 막는다", async () => {
  vi.mocked(api.measure).mockResolvedValue(plan());
  const { rerender, deck, draft, onApply, onCancel } = open();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
  rerender(<DiagramAuthoringDialog projectName="synthetic" deck={{ ...deck, meta: { ...deck.meta, title: "다른 변경" } }}
    initialDraft={draft} onApply={onApply} onCancel={onCancel} />);
  expect(screen.getByRole("alert")).toHaveTextContent("원본 덱이 변경");
  expect(screen.getByLabelText("항목 1 내용")).toHaveValue("요청 접수");
  expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
});

it("닫힌 작성 창의 늦은 응답으로 덱을 적용하지 않는다", async () => {
  const pending = deferred<RenderPlan>();
  vi.mocked(api.measure).mockReturnValue(pending.promise);
  const { unmount, onApply, onCancel } = open();
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
  expect(onCancel).toHaveBeenCalledOnce();
  unmount();
  await act(async () => pending.resolve(plan()));
  expect(onApply).not.toHaveBeenCalled();
});

it("연결된 항목의 삭제를 막고 관계 삭제 뒤에만 항목을 삭제한다", async () => {
  open();
  expect(screen.getByRole("button", { name: "항목 3 삭제" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "관계 2 삭제" }));
  await userEvent.click(screen.getByRole("button", { name: "항목 3 삭제" }));
  expect(screen.queryByLabelText("항목 3 내용")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "항목 2 삭제" })).toBeDisabled();
});

it("작성 창 안에서 Tab 포커스를 유지한다", async () => {
  open();
  const dialog = screen.getByRole("dialog");
  const close = within(dialog).getByRole("button", { name: "변경 버리고 닫기" });
  close.focus();
  await userEvent.tab();
  expect(dialog.contains(document.activeElement)).toBe(true);
  expect(document.activeElement).not.toBe(close);
});

it.each([true, false])("기존 편집 저장 결과가 %s일 때에만 연결 확인을 진행한다", async (saved) => {
  const pending = deferred<boolean>();
  const flushBeforeCheck = vi.fn(() => pending.promise);
  const deck = fresh();
  vi.mocked(api.reconcileDiagramStory).mockImplementation(async (_name, req) => req.deck);
  vi.mocked(api.measure).mockResolvedValue(plan());
  render(<DiagramAuthoringDialog projectName="synthetic" deck={deck}
    initialDraft={editDiagramDraft(deck, chapterId)} onApply={vi.fn()} onCancel={vi.fn()}
    flushBeforeCheck={flushBeforeCheck} />);
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  expect(flushBeforeCheck).toHaveBeenCalledOnce();
  expect(api.reconcileDiagramStory).not.toHaveBeenCalled();
  await act(async () => pending.resolve(saved));
  if (saved) {
    await waitFor(() => expect(screen.getByRole("button", { name: "도식 적용" })).toBeEnabled());
    expect(api.reconcileDiagramStory).toHaveBeenCalledOnce();
  } else {
    expect(screen.getByRole("alert")).toHaveTextContent("기존 편집 내용을 저장하지 못했습니다");
    expect(api.reconcileDiagramStory).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "도식 적용" })).toBeDisabled();
  }
});

it.each(["edit", "close"])("연결 응답 대기 중 %s 뒤에는 배치 요청과 적용을 하지 않는다", async (action) => {
  const pending = deferred<Deck>();
  const { deck, unmount, onApply } = open();
  vi.mocked(api.reconcileDiagramStory).mockReturnValue(pending.promise);
  await userEvent.click(screen.getByRole("button", { name: "입력과 배치 확인" }));
  if (action === "edit") {
    fireEvent.change(screen.getByLabelText("항목 1 내용"), { target: { value: "늦은 응답 이후 보존" } });
  } else {
    await userEvent.click(screen.getByRole("button", { name: "변경 버리고 닫기" }));
    unmount();
  }
  await act(async () => pending.resolve(deck));
  expect(api.measure).not.toHaveBeenCalled();
  expect(onApply).not.toHaveBeenCalled();
});
