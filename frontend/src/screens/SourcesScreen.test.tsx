import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api, type Deck } from "../api/client";
import { SourcesScreen } from "./SourcesScreen";

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api,
    listSources: vi.fn(), readSource: vi.fn(), writeSource: vi.fn(), putDeck: vi.fn() } };
});

const project = { name: "p1", title: "제목", updated_at: "", status: "ok" as const };
const deck: Deck = {
  schema_version: 1,
  meta: { title: "제목", report_type: "research", audience: "", preset_overrides: {} },
  structure: { chapters: [] },
  slides: [],
};

it("자료 목록을 보여주고 파일을 열어 저장한다", async () => {
  vi.mocked(api.listSources).mockResolvedValue(["자료.md"]);
  vi.mocked(api.readSource).mockResolvedValue({ text: "원문" });
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.click(await screen.findByText("자료.md"));
  const area = await screen.findByLabelText("자료 내용");
  expect(area).toHaveValue("원문");
  await userEvent.clear(area);
  await userEvent.type(area, "고친 원문");
  await userEvent.click(screen.getByText("자료 저장"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "자료.md", "고친 원문");
});

it("보고 정보를 저장하면 덱이 갱신된다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.putDeck).mockResolvedValue({ ok: true });
  const onDeckChange = vi.fn();
  render(<SourcesScreen project={project} deck={deck} onDeckChange={onDeckChange} />);
  const title = screen.getByLabelText("보고서 제목");
  await userEvent.clear(title);
  await userEvent.type(title, "새 제목");
  await userEvent.click(screen.getByText("보고 정보 저장"));
  expect(api.putDeck).toHaveBeenCalledWith(
    "p1", expect.objectContaining({ meta: expect.objectContaining({ title: "새 제목" }) }), false);
  expect(onDeckChange).toHaveBeenCalled();
});

it("새 자료 이름에 확장자가 없으면 .md를 붙인다", async () => {
  vi.mocked(api.listSources).mockResolvedValue([]);
  vi.mocked(api.writeSource).mockResolvedValue({ ok: true });
  vi.mocked(api.readSource).mockResolvedValue({ text: "" });
  render(<SourcesScreen project={project} deck={deck} onDeckChange={() => {}} />);
  await userEvent.type(screen.getByLabelText("새 자료 이름"), "리서치");
  await userEvent.click(screen.getByText("자료 추가"));
  expect(api.writeSource).toHaveBeenCalledWith("p1", "리서치.md", "");
});
