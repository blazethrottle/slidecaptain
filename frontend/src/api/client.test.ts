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

it("자료 파일 업로드는 파일 본문을 그대로 보내고 JSON 헤더를 붙이지 않는다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ filename: "리서치.md", chars: 3 }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const file = new File(["abc"], "리서치.md", { type: "text/markdown" });
  const result = await api.uploadSource("p1", file, true);
  expect(result.filename).toBe("리서치.md");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`/api/projects/p1/sources/${encodeURIComponent("리서치.md")}/upload?overwrite=true`);
  expect(init.method).toBe("POST");
  expect(init.body).toBe(file);
  const headers = new Headers(init.headers ?? {});
  expect(headers.has("Content-Type")).toBe(false);
  expect(headers.get("X-Requested-With")).toBe("SlideCaptain");  // 서버가 요구하는 앱 식별 헤더
});

it("업로드 오류 응답의 detail도 ApiError로 만든다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "같은 이름의 자료가 이미 있습니다: a.md" }), { status: 409 }),
  ));
  await expect(api.uploadSource("p1", new File(["x"], "a.md"), false))
    .rejects.toMatchObject({ status: 409, message: "같은 이름의 자료가 이미 있습니다: a.md" });
});
