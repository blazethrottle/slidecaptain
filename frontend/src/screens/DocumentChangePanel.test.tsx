import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { api, ApiError, type Deck, type DocumentChangePreview } from "../api/client";
import { storyDeck } from "../test/story";
import { DocumentChangePanel } from "./DocumentChangePanel";

vi.mock("../api/client", async original => {
  const mod = await original<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getDocumentChangeBasis: vi.fn(), previewDocumentChange: vi.fn(),
    applyDocumentChange: vi.fn(), previewEvidenceMigration: vi.fn(), applyEvidenceMigration: vi.fn() } };
});
const basis = { base_etag: '"old"', sources_fingerprint: "b".repeat(64), evidence_fingerprints: { e1: "c".repeat(64) } };
const preview = (): DocumentChangePreview => ({ rule_version: "document-change-v1", reason: "document_replacement",
  base_fingerprint: "a".repeat(64), sources_fingerprint: basis.sources_fingerprint, candidate_fingerprint: "d".repeat(64),
  candidate: { ...storyDeck(), meta: { ...storyDeck().meta, presenter: "변경 후보" } },
  losses: [{ id: "e".repeat(64), path: "meta", kind: "replaced", before: { presenter: "원본" }, after: { presenter: "변경 후보" } },
    { id: "f".repeat(64), path: "chapters/order", kind: "reordered", before: ["c1"], after: ["c2", "c1"] }],
  confirmation_token: "1".repeat(64), final_export_allowed: false, notice: "아직 독립 검수하지 않은 변경 후보" });

function setup(props: Partial<Parameters<typeof DocumentChangePanel>[0]> = {}) {
  const onApplied = vi.fn(), onActiveChange = vi.fn(), onBusyChange = vi.fn(), onDirtyChange = vi.fn(), onScreenReady = vi.fn();
  const all = { projectName: "synthetic", deck: storyDeck(), disabled: false, onApplied, onActiveChange, onBusyChange,
    onDirtyChange, onScreenReady, ...props };
  return { ...render(<DocumentChangePanel {...all} />), ...all };
}
beforeEach(() => {
  vi.mocked(api.getDocumentChangeBasis).mockResolvedValue(basis);
  vi.mocked(api.previewDocumentChange).mockResolvedValue(preview());
  vi.mocked(api.previewEvidenceMigration).mockResolvedValue({ ...preview(), reason: "evidence_migration" });
  vi.mocked(api.applyDocumentChange).mockResolvedValue(preview().candidate);
  vi.mocked(api.applyEvidenceMigration).mockResolvedValue(preview().candidate);
});
async function showPreview() {
  await waitFor(() => expect(screen.getByRole("button", { name: "변경 기준 다시 확인" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("문서 후보 JSON"), { target: { value: JSON.stringify(storyDeck()) } });
  await userEvent.click(screen.getByRole("button", { name: "변경 미리보기" }));
  return screen.findByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" });
}
async function acknowledge() {
  await userEvent.click(screen.getByLabelText("1번 변경 내용 확인"));
  await userEvent.click(screen.getByLabelText("2번 변경 내용 확인"));
}

it("원문 전후와 모든 변경을 확인한 후보만 명시적으로 적용한다", async () => {
  const ui = setup();
  expect(await showPreview()).toHaveTextContent("아직 독립 검수하지 않은 변경 후보");
  expect(screen.getByLabelText("1번 변경 전")).toHaveTextContent("원본");
  expect(screen.getByLabelText("1번 변경 후")).toHaveTextContent("변경 후보");
  expect(api.applyDocumentChange).not.toHaveBeenCalled();
  await userEvent.click(screen.getByLabelText("1번 변경 내용 확인"));
  expect(screen.getByRole("button", { name: "확인한 변경 적용" })).toBeDisabled();
  await userEvent.click(screen.getByLabelText("2번 변경 내용 확인"));
  await userEvent.click(screen.getByRole("button", { name: "확인한 변경 적용" }));
  expect(api.applyDocumentChange).toHaveBeenCalledWith("synthetic", { candidate: preview().candidate,
    expected_source_fingerprint: basis.sources_fingerprint, confirmation_token: preview().confirmation_token,
    acknowledged_loss_ids: preview().losses.map(i => i.id) }, basis.base_etag);
  expect(ui.onApplied).toHaveBeenCalledWith(preview().candidate);
});

it("자신이 적용한 저장본의 부모 재렌더링은 성공 안내를 유지하고 새 기준 확인을 요구한다", async () => {
  const active = vi.fn();
  function Harness() {
    const [deck, setDeck] = useState(storyDeck());
    return <DocumentChangePanel projectName="synthetic" deck={deck} disabled={false} onApplied={setDeck} onActiveChange={active} />;
  }
  render(<Harness />); await showPreview(); await acknowledge();
  await userEvent.click(screen.getByRole("button", { name: "확인한 변경 적용" }));
  expect(await screen.findByText("변경을 적용했습니다. 내용과 현재 PPTX 표시의 독립 검수가 필요합니다.")).toBeInTheDocument();
  expect(screen.queryByText(/저장본이 바뀌었습니다. 입력과 후보를 보존/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("문서 후보 JSON")).toHaveValue("");
  expect(screen.queryByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "변경 미리보기" })).toBeDisabled();
  expect(screen.getByText(/변경 기준을 다시 확인하고 새 미리보기를 만들어야/)).toBeInTheDocument();
  expect(api.getDocumentChangeBasis).toHaveBeenCalledTimes(1);
});

it("외부 저장본 변경은 작성 입력과 기존 후보를 유지하면서 적용 확인을 무효화한다", async () => {
  const ui = setup(); await showPreview(); await acknowledge();
  const input = (screen.getByLabelText("문서 후보 JSON") as HTMLTextAreaElement).value;
  ui.rerender(<DocumentChangePanel {...ui} deck={{ ...ui.deck, meta: { ...ui.deck.meta, presenter: "외부 저장본" } }} />);
  expect(await screen.findByText(/저장본이 바뀌었습니다. 입력과 후보를 보존/)).toBeInTheDocument();
  expect(screen.getByLabelText("문서 후보 JSON")).toHaveValue(input);
  expect(screen.getByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" })).toHaveTextContent("변경 후보");
  expect(screen.getByLabelText("1번 변경 내용 확인")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "확인한 변경 적용" })).toBeDisabled();
  expect(api.applyDocumentChange).not.toHaveBeenCalled();
});

it.each([409, 412])("충돌 %s는 입력·후보를 보존하고 기준 재확인 후 새 미리보기를 요구한다", async status => {
  vi.mocked(api.applyDocumentChange).mockRejectedValueOnce(new ApiError(status, "자료나 저장본이 바뀌었습니다"));
  const conflict = vi.fn(); setup({ onConflict: conflict });
  await showPreview(); await acknowledge();
  const text = screen.getByLabelText("문서 후보 JSON"); const original = (text as HTMLTextAreaElement).value;
  await userEvent.click(screen.getByRole("button", { name: "확인한 변경 적용" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("자료나 저장본");
  expect(text).toHaveValue(original);
  expect(screen.getByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "확인한 변경 적용" })).toBeDisabled();
  expect(conflict).toHaveBeenCalledTimes(status === 412 ? 1 : 0);
  await userEvent.click(screen.getByRole("button", { name: "변경 기준 다시 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "변경 미리보기" })).toBeEnabled());
  expect(screen.getByRole("button", { name: "확인한 변경 적용" })).toBeDisabled();
});

it("근거 이동은 기존 fingerprint와 선택만 보내고 발췌를 자기신고하지 않는다", async () => {
  setup(); await waitFor(() => expect(screen.getByRole("button", { name: "변경 기준 다시 확인" })).toBeEnabled());
  await userEvent.selectOptions(screen.getByLabelText("변경 방식"), "migration");
  const selection = JSON.parse((screen.getByLabelText("새 근거 선택 JSON") as HTMLTextAreaElement).value);
  expect(selection).not.toHaveProperty("source_revision"); expect(selection).not.toHaveProperty("excerpt");
  selection.source_id = "이동한.md";
  fireEvent.change(screen.getByLabelText("새 근거 선택 JSON"), { target: { value: JSON.stringify(selection) } });
  await userEvent.click(screen.getByRole("button", { name: "변경 미리보기" }));
  await screen.findByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" });
  expect(api.previewEvidenceMigration).toHaveBeenCalledWith("synthetic", { evidence_id: "e1",
    old_evidence_fingerprint: basis.evidence_fingerprints.e1, new_selection: selection,
    expected_source_fingerprint: basis.sources_fingerprint }, basis.base_etag);
  expect(screen.getByText(/여러 건을 함께 이동하는 기능은 아직 지원/)).toBeInTheDocument();
  await acknowledge(); await userEvent.click(screen.getByRole("button", { name: "확인한 변경 적용" }));
  expect(api.applyEvidenceMigration).toHaveBeenCalledWith("synthetic", expect.objectContaining({ new_selection: selection,
    old_evidence_fingerprint: basis.evidence_fingerprints.e1, confirmation_token: preview().confirmation_token }), basis.base_etag);
});

it("입력 편집은 이전 후보를 보존하되 적용을 무효화한다", async () => {
  setup(); await showPreview(); await acknowledge();
  fireEvent.change(screen.getByLabelText("문서 후보 JSON"), { target: { value: "새 입력" } });
  expect(screen.getByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "확인한 변경 적용" })).toBeDisabled();
});

it("여러 이탈 guard 중 확인만 하고 입력을 미리 지우지 않는다", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const ready = vi.fn(); setup({ onScreenReady: ready }); await showPreview();
  await act(async () => expect(await ready.mock.calls.at(-1)![0]()).toBe(true));
  expect(screen.getByLabelText("문서 후보 JSON")).not.toHaveValue("");
  expect(screen.getByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" })).toBeInTheDocument();
});

it("선택 파일 읽기가 끝나기 전 중복 실행·이탈을 차단하고 unmount에도 lease를 보존한다", async () => {
  let finish!: (text: string) => void;
  const file = new File(["{}"], "후보.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => new Promise<string>(resolve => { finish = resolve; }) });
  const ready = vi.fn(); const ui = setup({ onScreenReady: ready }); await waitFor(() => expect(screen.getByRole("button", { name: "변경 기준 다시 확인" })).toBeEnabled());
  await userEvent.upload(screen.getByLabelText("문서 후보 JSON 파일"), file);
  const button = screen.getByRole("button", { name: "변경 미리보기" });
  fireEvent.click(button); fireEvent.click(button);
  expect(ui.onBusyChange).toHaveBeenLastCalledWith(true);
  expect(await ready.mock.calls.at(-1)![0]()).toBe(false);
  ui.unmount(); expect(ui.onBusyChange).toHaveBeenLastCalledWith(true);
  await act(async () => finish(JSON.stringify(storyDeck())));
  expect(api.previewDocumentChange).not.toHaveBeenCalled();
  expect(ui.onBusyChange).toHaveBeenLastCalledWith(false);
  expect(ui.onApplied).not.toHaveBeenCalled();
});

it("늦은 후보 응답이 새 저장본에 나타나지 않으며 입력은 보존한다", async () => {
  let finish!: (value: DocumentChangePreview) => void;
  vi.mocked(api.previewDocumentChange).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const ui = setup(); await waitFor(() => expect(screen.getByRole("button", { name: "변경 기준 다시 확인" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("문서 후보 JSON"), { target: { value: JSON.stringify(storyDeck()) } });
  await userEvent.click(screen.getByRole("button", { name: "변경 미리보기" }));
  const next: Deck = { ...ui.deck, meta: { ...ui.deck.meta, presenter: "새 저장본" } };
  ui.rerender(<DocumentChangePanel {...ui} deck={next} />);
  await act(async () => finish(preview()));
  expect(screen.queryByRole("region", { name: "아직 적용하지 않은 문서 변경 후보" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("문서 후보 JSON")).not.toHaveValue("");
  expect(screen.getByRole("button", { name: "변경 미리보기" })).toBeDisabled();
});

it("큰 파일과 UTF8 입력은 미리보기 전에 차단한다", async () => {
  setup(); await waitFor(() => expect(screen.getByRole("button", { name: "변경 기준 다시 확인" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("문서 후보 JSON"), { target: { value: JSON.stringify({ text: "한".repeat(400000) }) } });
  await userEvent.click(screen.getByRole("button", { name: "변경 미리보기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("1MiB");
  expect(api.previewDocumentChange).not.toHaveBeenCalled();
});

it("선택한 큰 파일을 읽지 않고 보존하여 크기 제한을 안내한다", async () => {
  setup(); await waitFor(() => expect(screen.getByRole("button", { name: "변경 기준 다시 확인" })).toBeEnabled());
  const file = new File(["x".repeat(1024 * 1024 + 1)], "큰후보.json", { type: "application/json" });
  const read = vi.fn(); Object.defineProperty(file, "text", { value: read });
  await userEvent.upload(screen.getByLabelText("문서 후보 JSON 파일"), file);
  await userEvent.click(screen.getByRole("button", { name: "변경 미리보기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("1MiB");
  expect(screen.getByText("선택한 파일: 큰후보.json")).toBeInTheDocument();
  expect(read).not.toHaveBeenCalled(); expect(api.previewDocumentChange).not.toHaveBeenCalled();
});

it("파일을 읽는 동안 readonly로 바뀌면 후보 요청을 보내지 않는다", async () => {
  let finish!: (text: string) => void;
  const file = new File(["{}"], "후보.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => new Promise<string>(resolve => { finish = resolve; }) });
  const ui = setup(); await waitFor(() => expect(screen.getByRole("button", { name: "변경 기준 다시 확인" })).toBeEnabled());
  await userEvent.upload(screen.getByLabelText("문서 후보 JSON 파일"), file);
  await userEvent.click(screen.getByRole("button", { name: "변경 미리보기" }));
  ui.rerender(<DocumentChangePanel {...ui} disabled />);
  await act(async () => finish(JSON.stringify(storyDeck())));
  expect(api.previewDocumentChange).not.toHaveBeenCalled();
  expect(screen.getByText("선택한 파일: 후보.json")).toBeInTheDocument();
});
