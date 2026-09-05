import { emptyUsage } from "../test/usage";
import * as aiGate from "./aiGate";
import { AiConsentDeclined, api, resetEtags } from "./client";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
beforeEach(() => resetEtags());  // ETag 맵은 모듈 전역이라 테스트 사이에 새지 않게 비운다

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

it("모든 요청에 SlideCaptain 표식 헤더를 붙인다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.listProjects();
  const [, init] = fetchMock.mock.calls[0];
  const headers = new Headers((init as RequestInit).headers ?? {});
  expect(headers.get("X-Requested-With")).toBe("SlideCaptain");
});

it("getDeck 뒤 putDeck은 If-Match를 보내고, 응답 ETag로 다음 If-Match가 바뀐다", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1 }), {
      status: 200, headers: { ETag: '"etag-1"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
      status: 200, headers: { ETag: '"etag-2"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.getDeck("p1");
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  const put1Init = fetchMock.mock.calls[1][1] as RequestInit;
  expect(new Headers(put1Init.headers ?? {}).get("If-Match")).toBe('"etag-1"');
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  const put2Init = fetchMock.mock.calls[2][1] as RequestInit;
  expect(new Headers(put2Init.headers ?? {}).get("If-Match")).toBe('"etag-2"');
});

it("ETag를 모르면 If-Match를 보내지 않는다", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.putDeck("p1", { schema_version: 1 } as never, false);
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  expect(new Headers(init.headers ?? {}).has("If-Match")).toBe(false);
});

// AI 전송 고지 관문 배선 (계획서 B3): 화면 테스트는 api를 통째로 목 처리하므로 관문 배선을 검증할
// 수 없다. 여기서는 fetch만 스텁하고 aiGate.ensureConsent를 spy해 client.ts의 실제 구현을 검증한다.
it("동의가 있으면 구조안 생성 요청에 X-AI-Consent 헤더를 붙인다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", structure: null, usage: emptyUsage(), raw_text: "", unverified_numbers: [],
      format_retried: false }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.generateStructure("p1", {});
  expect(aiGate.ensureConsent).toHaveBeenCalledTimes(1);
  const [, init] = fetchMock.mock.calls[0];
  expect(new Headers((init as RequestInit).headers ?? {}).get("X-AI-Consent")).toBe("SlideCaptain");
});

it("동의가 없으면 구조안 생성은 fetch를 부르지 않고 AiConsentDeclined를 던진다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(false);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.generateStructure("p1", {})).rejects.toBeInstanceOf(AiConsentDeclined);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("장 생성도 동의 관문을 거쳐 헤더를 붙인다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", slots: null, usage: emptyUsage(), raw_text: "", warnings: [],
      unverified_numbers: [], format_retried: false, condensed: false }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.generateChapter("p1", "c1");
  expect(aiGate.ensureConsent).toHaveBeenCalledTimes(1);
  const [, init] = fetchMock.mock.calls[0];
  expect(new Headers((init as RequestInit).headers ?? {}).get("X-AI-Consent")).toBe("SlideCaptain");
});

it("장 생성은 동의가 없으면 fetch를 부르지 않는다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(false);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.generateChapter("p1", "c1")).rejects.toBeInstanceOf(AiConsentDeclined);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("축약도 동의 관문을 거쳐 헤더를 붙인다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", slots: null, usage: emptyUsage(), raw_text: "", warnings: [],
      unverified_numbers: [], format_retried: false, condensed: false }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.condenseChapter("p1", "c1", { template: "bullet_box", bullets: [], conclusion: "", footnote: "" });
  expect(aiGate.ensureConsent).toHaveBeenCalledTimes(1);
  const [, init] = fetchMock.mock.calls[0];
  expect(new Headers((init as RequestInit).headers ?? {}).get("X-AI-Consent")).toBe("SlideCaptain");
});

it("축약은 동의가 없으면 fetch를 부르지 않는다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(false);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.condenseChapter("p1", "c1",
    { template: "bullet_box", bullets: [], conclusion: "", footnote: "" }))
    .rejects.toBeInstanceOf(AiConsentDeclined);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("다른 프로젝트 이름은 다른 ETag 키다", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1 }), {
      status: 200, headers: { ETag: '"p1-etag"' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await api.getDeck("p1");
  await api.putDeck("p2", { schema_version: 1 } as never, false);
  const init = fetchMock.mock.calls[1][1] as RequestInit;
  expect(new Headers(init.headers ?? {}).has("If-Match")).toBe(false);
});
