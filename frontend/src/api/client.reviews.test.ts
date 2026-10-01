import { api, resetEtags, type ExportReviewRequest } from "./client";
import { exportReviews } from "../test/reviews";

const input: ExportReviewRequest = {
  expected_input_fingerprint: "a".repeat(64), expected_artifact_sha256: "b".repeat(64),
  category: "narrative", status: "passed", reviewer: "합성 검수자", note: "합성 QA입니다.", pages: [1, 2],
};

beforeEach(() => { resetEtags(); });
afterEach(() => { vi.unstubAllGlobals(); });

it("조회 기준을 재사용하고 검수 GET/POST로 전역 저장 ETag를 바꾸지 않는다", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response("{}", { headers: { ETag: '"current-editor"' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify(exportReviews()), { headers: { ETag: '"review-old"' } }))
    .mockResolvedValueOnce(new Response(JSON.stringify(exportReviews()), { headers: { ETag: '"review-save"' } }))
    .mockResolvedValueOnce(new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  await api.getDeck("합성 보고");
  const basis = await api.getExportReviews("합성 보고", "report_v001");
  await api.recordExportReview("합성 보고", "report_v001", input, basis.base_etag!);
  const [getUrl, getInit] = fetch.mock.calls[1] as [string, RequestInit];
  expect(getUrl).toBe(`/api/projects/${encodeURIComponent("합성 보고")}/exports/report_v001/reviews`);
  expect(getInit.cache).toBe("no-store");
  expect(new Headers(getInit.headers).get("If-Match")).toBeNull();
  const [postUrl, postInit] = fetch.mock.calls[2] as [string, RequestInit];
  expect(postUrl).toBe(getUrl);
  expect(postInit.method).toBe("POST");
  expect(JSON.parse(postInit.body as string)).toEqual(input);
  expect(Object.fromEntries(new Headers(postInit.headers))).toMatchObject({
    "x-requested-with": "SlideCaptain", "if-match": '"opened-deck"',
  });
  expect(new Headers(postInit.headers).get("X-AI-Consent")).toBeNull();
  await api.putDeck("합성 보고", {} as never, false);
  expect(new Headers((fetch.mock.calls[3][1] as RequestInit).headers).get("If-Match")).toBe('"current-editor"');
});

it("검수 기준 ETag가 없으면 전역 캐시로 대체하지 않고 전송을 거절한다", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("{}", { headers: { ETag: '"editor"' } }));
  vi.stubGlobal("fetch", fetch);
  await api.getDeck("p1");
  await expect(api.recordExportReview("p1", "report_v001", input, "")).rejects.toMatchObject({ status: 428 });
  expect(fetch).toHaveBeenCalledTimes(1);
});
