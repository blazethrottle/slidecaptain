import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

it("오류 응답의 detail을 ApiError 메시지로 만든다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "자료가 너무 큽니다" }), { status: 422 }),
  ));
  await expect(api.listProjects()).rejects.toThrowError("자료가 너무 큽니다");
});

it("성공 응답의 JSON을 그대로 돌려준다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify([{ name: "p1", title: "t", updated_at: "", status: "ok" }]), { status: 200 }),
  ));
  const projects = await api.listProjects();
  expect(projects[0].name).toBe("p1");
});

it("스냅샷 여부를 쿼리로 보낸다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.putDeck("p1", { schema_version: 1, meta: { title: "t" } } as never, false);
  expect(fetchMock.mock.calls[0][0]).toContain("/deck?snapshot=false");
});
