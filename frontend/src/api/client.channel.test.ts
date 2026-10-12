// 다른 탭 알림의 계약 시험 (개정판 D3a-6, 계획 4.5). 실제 BroadcastChannel(Node)로 다른 탭의 채널을 흉내 낸다.
// 두 탭의 모듈 분리는 jsdom이 흉내 내지 못하므로 회귀 판정은 헤드리스 Chromium 두 탭으로 한다(구현 기록)
import { batchView } from "../test/jobs";

const CHANNEL_NAME = "slidecaptain-project-events";
const ok = (body: unknown, etag?: string) => new Response(JSON.stringify(body),
  { status: 200, headers: etag ? { ETag: etag } : {} });

// 다른 탭: 같은 이름의 채널을 따로 열어 이 탭(모듈)이 보낸 메시지를 받는다
function otherTab() {
  const received: unknown[] = [];
  const peer = new BroadcastChannel(CHANNEL_NAME);
  peer.onmessage = (m) => received.push(m.data);
  return { received, peer };
}
const settle = () => new Promise((r) => setTimeout(r, 30));  // 채널 메시지는 비동기로 도착한다

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.resetModules(); });

it("저장과 작업 등록 알림을 다른 탭에 보내되, 등록은 응답을 받은 뒤에만 보낸다", async () => {
  const { api } = await import("./client");
  const { received, peer } = otherTab();
  let resolve!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(new Promise<Response>((r) => { resolve = r; }))
    .mockImplementation(async () => ok({ ok: true }, '"e1"')));
  const pending = api.startChapters("p1", ["c1"], {}, "req-1");
  await settle();
  expect(received).toEqual([]);  // 응답 전에 보내면 받은 탭의 조회가 빈 결과를 받는다
  resolve(ok({ ...batchView([]), id: "job-9", state: "running" }));
  await pending;
  await api.writeSource("p1", "a.md", "본문");
  await settle();
  expect(received).toEqual([{ kind: "job_started", project: "p1", jobId: "job-9" }, { kind: "saved", project: "p1" }]);
  peer.close();
});

it("다른 탭의 메시지를 받으면 듣는 쪽을 부르고, 같은 탭의 알림은 다른 탭 듣는 쪽으로 오지 않는다", async () => {
  const { notifyProject, onProjectEvent, onRemoteProjectEvent } = await import("./client");
  const remote: unknown[] = [];
  const local: unknown[] = [];
  const offRemote = onRemoteProjectEvent((e) => remote.push(e));
  const offLocal = onProjectEvent((e) => local.push(e));
  const { peer } = otherTab();
  peer.postMessage({ kind: "job_ended", project: "p1", jobId: "job-9", state: "succeeded" });
  notifyProject({ kind: "saved", project: "p1" });
  await settle();
  // 받는 알림에는 종류와 프로젝트만 싣는다. 내용은 믿지 않고 서버를 다시 조회한다
  expect(remote).toEqual([{ kind: "job_ended", project: "p1" }]);
  expect(local).toEqual([{ kind: "saved", project: "p1" }]);  // 다른 탭의 알림은 같은 탭 듣는 쪽(종결 알림 등)으로 가지 않는다
  offRemote(); offLocal(); peer.close();
});

it("형식이 맞지 않는 메시지는 버린다", async () => {
  const { onRemoteProjectEvent } = await import("./client");
  const remote: unknown[] = [];
  const off = onRemoteProjectEvent((e) => remote.push(e));
  const { peer } = otherTab();
  peer.postMessage({ kind: "deck", project: "p1" });
  peer.postMessage({ kind: "saved" });
  peer.postMessage("saved");
  await settle();
  expect(remote).toEqual([]);
  off(); peer.close();
});

it("채널 객체는 탭마다 하나만 만든다", async () => {
  const created: string[] = [];
  class CountingChannel {
    onmessage: ((m: MessageEvent) => void) | null = null;
    constructor(name: string) { created.push(name); }
    postMessage() {}
    close() {}
  }
  vi.stubGlobal("BroadcastChannel", CountingChannel);
  const { notifyProject, onRemoteProjectEvent } = await import("./client");
  const offA = onRemoteProjectEvent(() => {});
  const offB = onRemoteProjectEvent(() => {});
  notifyProject({ kind: "saved", project: "p1" });
  notifyProject({ kind: "saved", project: "p2" });
  expect(created).toEqual([CHANNEL_NAME]);
  offA(); offB();
});

it("채널이 없는 환경에서도 같은 탭 알림은 그대로 돌고 다른 탭 듣기는 아무 일도 하지 않는다", async () => {
  vi.stubGlobal("BroadcastChannel", undefined);
  const { notifyProject, onProjectEvent, onRemoteProjectEvent } = await import("./client");
  const local: unknown[] = [];
  const off = onProjectEvent((e) => local.push(e));
  const offRemote = onRemoteProjectEvent(() => { throw new Error("불리면 안 된다"); });
  expect(() => notifyProject({ kind: "saved", project: "p1" })).not.toThrow();
  expect(local).toEqual([{ kind: "saved", project: "p1" }]);
  off(); offRemote();
});
