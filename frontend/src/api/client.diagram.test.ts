import { api, AiConsentDeclined, resetEtags } from "./client";
import * as aiGate from "./aiGate";
import { deferred } from "../test/fixtures";

const input = { chapter_id: "diagram-1", topic: "요청 처리", role: "evidence" as const,
  claim_ids: ["claim"], instructions: "등록 근거를 확인해 주세요." };

beforeEach(() => {
  resetEtags();
  vi.spyOn(api, "getStatus").mockResolvedValue({ provider: "chatgpt", model: "chosen-model", selection_id: "chosen",
    checked_at: "", login: { logged_in: true } });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("도식 생성은 알려진 저장본이 없으면 동의나 전송을 시작하지 않는다", async () => {
  const consent = vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(true);
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(api.generateDiagram("p1", input)).rejects.toMatchObject({ status: 428 });
  expect(consent).not.toHaveBeenCalled();
  expect(api.getStatus).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it("도식 생성 동의를 취소하면 생성 요청을 보내지 않는다", async () => {
  vi.spyOn(aiGate, "ensureConsent").mockResolvedValue(false);
  const fetch = vi.fn().mockResolvedValueOnce(new Response("{}", { headers: { ETag: '"base"' } }));
  vi.stubGlobal("fetch", fetch);
  await api.getDeck("p1");
  await expect(api.generateDiagram("p1", input)).rejects.toBeInstanceOf(AiConsentDeclined);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("도식 생성의 기준 ETag는 동의 전에 고정하고 늦은 응답으로 저장 ETag를 덮어쓰지 않는다", async () => {
  const consent = deferred<boolean>();
  vi.spyOn(aiGate, "ensureConsent").mockReturnValue(consent.promise);
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response("{}", { headers: { ETag: '"base"' } }))
    .mockResolvedValueOnce(new Response("{}", { headers: { ETag: '"newer"' } }))
    .mockResolvedValueOnce(new Response('{"status":"ok"}', { headers: { ETag: '"base"' } }))
    .mockResolvedValueOnce(new Response('{"ok":true}'));
  vi.stubGlobal("fetch", fetch);
  await api.getDeck("합성 보고");
  const generation = api.generateDiagram("합성 보고", input);
  await api.getDeck("합성 보고");
  consent.resolve(true);
  await generation;
  const [url, init] = fetch.mock.calls[2] as [string, RequestInit];
  expect(url).toBe(`/api/projects/${encodeURIComponent("합성 보고")}/generate/diagram`);
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body as string)).toEqual(input);
  expect(Object.fromEntries(new Headers(init.headers))).toMatchObject({
    "x-requested-with": "SlideCaptain", "x-ai-consent": "SlideCaptain", "x-ai-selection": "chosen", "if-match": '"base"',
  });
  await api.putDeck("합성 보고", {} as never, false);
  expect(new Headers((fetch.mock.calls[3][1] as RequestInit).headers).get("If-Match")).toBe('"newer"');
});
