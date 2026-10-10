// 공통 알림 지점의 계약 시험 (개정판 D3a-3, 계획 4.5). 실제 request()를 거치도록 fetch만 흉내 낸다
import { api, followJob, onProjectEvent, resetEtags, type JobView, type ProjectEvent } from "./client";
import { deckWith } from "../test/fixtures";
import { batchView } from "../test/jobs";

let events: ProjectEvent[] = [];
let stop: () => void = () => {};
beforeEach(() => { resetEtags(); events = []; stop = onProjectEvent((e) => events.push(e)); });
afterEach(() => { stop(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const ok = (body: unknown, etag?: string) => new Response(JSON.stringify(body),
  { status: 200, headers: etag ? { ETag: etag } : {} });

it("저장 성공(덱 PUT, 자료 저장, 업로드, 복원, 내보내기)을 그 프로젝트의 저장 알림으로 낸다", async () => {
  const fetchMock = vi.fn().mockImplementation(async () => ok({ ok: true }, '"e1"'));
  vi.stubGlobal("fetch", fetchMock);
  await api.putDeck("p1", deckWith(["하나"]), false);
  await api.writeSource("p1", "a.md", "본문");
  fetchMock.mockResolvedValueOnce(ok({ filename: "a.xlsx", chars: 1, sheets: 1, cells: 1, truncated: false, notes: [] }));
  await api.uploadSource("p1", new File(["x"], "a.xlsx"), false);
  fetchMock.mockResolvedValueOnce(ok(deckWith(["하나"]), '"e2"'));
  await api.restoreSnapshot("p1", "deck-1");
  fetchMock.mockResolvedValueOnce(ok({ path: "x.pptx", quality_path: "x.json", quality: null }));
  await api.exportDeck("p1");
  expect(events).toEqual(Array(5).fill({ kind: "saved", project: "p1" }));
});

it("저장하지 않는 POST(실측, 수치 검토)와 조회는 알리지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ok({ slides: [] })));
  await api.measure(deckWith(["하나"]), "p1");
  await api.reviewNumbers("p1", deckWith(["하나"]));
  await api.listJobs("p1");
  expect(events).toEqual([]);
});

it("실패한 저장은 알리지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "충돌" }), { status: 412 })));
  await expect(api.putDeck("p1", deckWith(["하나"]), false)).rejects.toThrow();
  expect(events).toEqual([]);
});

it("작업 등록은 응답을 받은 뒤 작업 ID와 함께 알린다", async () => {
  let resolve!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((r) => { resolve = r; })));
  const pending = api.startChapters("p1", ["c1"], {}, "req-1");
  await Promise.resolve();
  expect(events).toEqual([]);  // 응답 전에는 알리지 않는다
  resolve(ok({ ...batchView([]), id: "job-9", state: "running" }));
  await pending;
  expect(events).toEqual([{ kind: "job_started", project: "p1", jobId: "job-9" }]);
});

it("작업 조회가 종결 상태를 보면 작업 종결을 알린다", async () => {
  const running = { ...batchView([]), id: "job-9", state: "running" } as JobView;
  const done = { ...running, state: "succeeded" } as JobView;
  const fetchJob = vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(done);
  await followJob(fetchJob, () => {}, { intervalMs: 0 });
  expect(events).toEqual([{ kind: "job_ended", project: "p1", jobId: "job-9" }]);
});

it("듣는 쪽의 오류는 요청을 실패로 만들지 않는다", async () => {
  const off = onProjectEvent(() => { throw new Error("듣는 쪽 오류"); });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ok: true })));
  await expect(api.writeSource("p1", "a.md", "본문")).resolves.toEqual({ ok: true });
  off();
});

// 저장 경로와 알림 표 (D3a-3 리뷰 R5). 앱의 모든 변경 요청을 한 표에 두고, 알리는 것과 알리지 않는 것을 함께 지킨다.
// 알리지 않는 것: 실측, 미리 보기, 대조, 수치와 의미 검토(저장하지 않음), 보존본 저장과 삭제, 스냅샷 만들기(진행
// 계산에 들지 않음, 내보내기가 알림), 제출본 자격 기록(진행 API가 읽지 않음)
const deck = deckWith(["하나"]);
const ROUTES: [string, () => Promise<unknown>, "saved" | "job_started" | null][] = [
  ["덱 저장", () => api.putDeck("p1", deck, false), "saved"],
  ["자료 저장", () => api.writeSource("p1", "a.md", "x"), "saved"],
  ["문서 변경 적용", () => api.applyDocumentChange("p1", {} as never, '"e"'), "saved"],
  ["근거 이동 적용", () => api.applyEvidenceMigration("p1", {} as never, '"e"'), "saved"],
  ["재작성 적용", () => api.applyStoryRewrite("p1", { deck, sources_fingerprint: "s", base_etag: '"e"' } as never), "saved"],
  ["보존본 복원", () => api.restoreDraft("p1", "d1"), "saved"],
  ["스냅샷 복원", () => api.restoreSnapshot("p1", "s1"), "saved"],
  ["내보내기", () => api.exportDeck("p1"), "saved"],
  ["검수 기록", () => api.recordExportReview("p1", "x", {} as never, '"e"'), "saved"],
  ["후보 처분", () => api.settleCandidate("p1", "j", "dismissed"), "saved"],
  ["장 후보 버리기", () => api.dismissChapterCandidate("p1", "j", "c1"), "saved"],
  ["장 생성 묶음 등록", () => api.startChapters("p1", ["c1"], {}, "req-1"), "job_started"],
  ["작업 등록", () => api.startJob("p1", { request_id: "req-1", kind: "structure", params: {} }, {}), "job_started"],
  ["실측", () => api.measure(deck, "p1"), null],
  ["도식 대조", () => api.reconcileDiagramStory("p1", {} as never), null],
  ["문서 변경 미리 보기", () => api.previewDocumentChange("p1", {} as never, '"e"'), null],
  ["근거 이동 미리 보기", () => api.previewEvidenceMigration("p1", {} as never, '"e"'), null],
  ["수치 검토", () => api.reviewNumbers("p1", deck), null],
  ["의미 검토", () => api.reviewSemantics("p1", deck), null],
  ["보존본 저장", () => api.saveDraft("p1", { reason: "conflict", source: "editor", deck }), null],
  ["보존본 삭제", () => api.deleteDraft("p1", "d1"), null],
  ["스냅샷 만들기", () => api.createSnapshot("p1"), null],
  ["작업 취소", () => api.cancelJob("p1", "j"), null],
];

it.each(ROUTES)("%s의 알림은 표대로다", async (_name, call, kind) => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ok({ ...batchView([]), id: "job-1" }, '"e1"')));
  await call();
  expect(events).toEqual(kind === null ? [] : [kind === "job_started"
    ? { kind, project: "p1", jobId: "job-1" } : { kind, project: "p1" }]);
});

it("등록 응답이 이미 종결이면 조회 없이도 작업 종결을 알린다 (D3a-3 리뷰 R9)", async () => {
  const { waitJob } = await import("./jobs");
  const done = { ...batchView([]), id: "job-2", state: "failed" } as JobView;
  await waitJob("p1", done);
  expect(events).toEqual([{ kind: "job_ended", project: "p1", jobId: "job-2" }]);
});
