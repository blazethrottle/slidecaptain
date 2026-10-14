const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const {
  validateRequest,
  isOfficialLogin,
  validateReady,
  readSelectedFiles,
  assertCaller,
  settleJobBeforeClose,
} = require("../runtime.cjs");
const origin = "http://127.0.0.1:45678";
test("known API methods and encoded project names are allowed", () => {
  const r = validateRequest(
    {
      path: "/api/projects/%ED%95%A9%EC%84%B1/deck",
      method: "PUT",
      headers: {
        "X-Requested-With": "SlideCaptain",
        "If-Match": "example-etag",
      },
      body: "{}",
    },
    origin,
    "owned",
  );
  assert.equal(r.url, origin + "/api/projects/%ED%95%A9%EC%84%B1/deck");
  assert.equal(r.headers["X-SlideCaptain-Session"], "owned");
});
for (const requested of [
  { path: "https://untrusted.example/api/projects" },
  { path: "/api/../private" },
  { path: "/api/projects/%2e%2e/deck" },
  { path: "/api/projects/%2Fprivate/deck" },
  { path: "/api/projects", method: "PATCH" },
  { path: "/api/unknown" },
  { path: "/api/projects", headers: { "X-SlideCaptain-Session": "forged" } },
  { path: "/api/projects", headers: { Authorization: "untrusted" } },
])
  test(
    "rejects request outside the bridge contract " + JSON.stringify(requested),
    () => assert.throws(() => validateRequest(requested, origin, "owned")),
  );
test("excessive request body is rejected", () =>
  assert.throws(() =>
    validateRequest(
      {
        path: "/api/projects",
        method: "POST",
        body: new Uint8Array(21 * 1024 * 1024),
      },
      origin,
      "owned",
    ),
  ));
test("readiness must match own version and instance", () => {
  const ready = {
    event: "ready",
    product: "slidecaptain",
    version: "0.2.0",
    port: 45678,
    desktop_instance_id: "owned",
    ui_ready: true,
  };
  assert.equal(validateReady(ready, "0.2.0", "owned"), origin);
  for (const change of [
    { product: "other" },
    { version: "old" },
    { desktop_instance_id: "other" },
    { port: 0 },
    { ui_ready: false },
  ])
    assert.throws(() =>
      validateReady({ ...ready, ...change }, "0.2.0", "owned"),
    );
});
test("only official HTTPS login URLs are accepted", () => {
  assert.ok(
    isOfficialLogin("https://auth.openai.com/authorize?state=synthetic"),
  );
  for (const url of [
    "http://auth.openai.com/",
    "https://auth.openai.com.untrusted.example/",
    "https://user@auth.openai.com/",
    "file:///tmp/example",
    "https://auth.openai.com:8443/",
  ])
    assert.equal(isOfficialLogin(url), false);
});
test("IPC checks both sender and top-level frame", () => {
  const frame = { url: origin + "/" },
    sender = { mainFrame: frame },
    window = { webContents: sender };
  assertCaller({ sender, senderFrame: frame }, window, origin);
  for (const event of [
    { sender: {}, senderFrame: frame },
    { sender, senderFrame: { url: origin + "/" } },
    { sender, senderFrame: { url: "https://untrusted.example/" } },
  ])
    assert.throws(() => assertCaller(event, window, origin));
});
test("selected documents read bytes without changing originals; partial failure preserves successes", async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "slidecaptain-files-"));
  try {
    const source = path.join(dir, "합성.txt");
    await fs.writeFile(source, "synthetic text");
    const result = await readSelectedFiles([
      source,
      path.join(dir, "missing.txt"),
    ]);
    assert.equal(result.files.length, 1);
    assert.equal(result.files[0].name, "합성.txt");
    assert.equal(
      Buffer.from(result.files[0].bytes).toString(),
      "synthetic text",
    );
    assert.equal(await fs.readFile(source, "utf8"), "synthetic text");
    assert.equal(result.notes.length, 1);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});
test("symlinks, executable files and oversized documents are excluded", async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "slidecaptain-files-"));
  try {
    const target = path.join(dir, "sample.txt"),
      link = path.join(dir, "link.txt"),
      big = path.join(dir, "big.txt"),
      exe = path.join(dir, "sample.exe");
    await fs.writeFile(target, "sample");
    await fs.writeFile(exe, "sample");
    const h = await fs.open(big, "w");
    await h.truncate(21 * 1024 * 1024);
    await h.close();
    const files = [exe, big];
    if (process.platform !== "win32") {
      await fs.symlink(target, link);
      files.push(link);
    }
    const result = await readSelectedFiles(files);
    assert.equal(result.files.length, 0);
    assert.equal(result.notes.length, files.length);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});
test("folder input is bounded by count and aggregate bytes", async () => {
  await assert.rejects(readSelectedFiles(Array(101).fill("/tmp/sample.txt")));
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "slidecaptain-budget-"));
  try {
    const paths = [];
    for (let i = 0; i < 3; i++) {
      const p = path.join(dir, i + ".txt"),
        f = await fs.open(p, "w");
      await f.truncate(16 * 1024 * 1024);
      await f.close();
      paths.push(p);
    }
    const result = await readSelectedFiles(paths);
    assert.equal(result.files.length, 2);
    assert.equal(result.notes.length, 1);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

// D2b-5c: 창 닫기 전 진행 중 AI 작업 확인
function fakeService(active, { failActive = false, failCancel = false } = {}) {
  const calls = [];
  const request = async (input) => {
    calls.push(input);
    if (input.path === "/api/jobs/active") {
      if (failActive) throw Error("서비스 응답 없음");
      return { status: 200, body: new TextEncoder().encode(JSON.stringify({ active, ledger_available: true })) };
    }
    if (failCancel) throw Error("취소 실패");
    return { status: 200, body: new TextEncoder().encode("{}") };
  };
  return { request, calls };
}
const activeJob = { id: "job-1", project: "합성 보고", kind: "chapters", target: null, stage: "running",
  created_at: "", cancel_requested: false };

test("진행 중 작업이 없으면 묻지 않고 닫는다", async () => {
  const { request, calls } = fakeService(null);
  let asked = false;
  assert.equal(await settleJobBeforeClose(request, async () => { asked = true; return "cancel"; }), "close");
  assert.equal(asked, false);
  assert.deepEqual(calls.map((c) => c.path), ["/api/jobs/active"]);
});

test("계속 작업을 고르면 취소하지 않고 창을 남긴다", async () => {
  const { request, calls } = fakeService(activeJob);
  assert.equal(await settleJobBeforeClose(request, async () => "continue"), "stay");
  assert.equal(calls.length, 1);
});

test("취소 후 닫기는 그 작업의 취소 라우트를 부르고 닫는다", async () => {
  const { request, calls } = fakeService(activeJob);
  let seen;
  assert.equal(await settleJobBeforeClose(request, async (job) => { seen = job; return "cancel"; }), "close");
  assert.equal(seen.id, "job-1");
  assert.equal(calls[1].method, "POST");
  assert.equal(calls[1].path, `/api/projects/${encodeURIComponent("합성 보고")}/jobs/job-1/cancel`);
  assert.equal(calls[1].headers["X-Requested-With"], "SlideCaptain");
  // 서비스 요청 검증을 통과하는 경로와 헤더다
  assert.doesNotThrow(() => validateRequest(calls[1], "http://127.0.0.1:8765", "token"));
  assert.doesNotThrow(() => validateRequest(calls[0], "http://127.0.0.1:8765", "token"));
});

test("작업을 확인하지 못하거나 취소 요청이 실패해도 닫는다", async () => {
  assert.equal(await settleJobBeforeClose(fakeService(activeJob, { failActive: true }).request, async () => "cancel"), "close");
  assert.equal(await settleJobBeforeClose(fakeService(activeJob, { failCancel: true }).request, async () => "cancel"), "close");
});

test("서비스가 응답하지 않으면 시간 한도 뒤에 닫는다 (D2b-5c 리뷰 R4)", async () => {
  const hanging = () => new Promise(() => {});
  const started = Date.now();
  assert.equal(await settleJobBeforeClose(hanging, async () => "cancel", { timeoutMs: 50 }), "close");
  assert.ok(Date.now() - started < 2000);
});

test("취소 요청이 응답하지 않아도 시간 한도 뒤에 닫는다", async () => {
  const request = async (input) => (input.path === "/api/jobs/active"
    ? { status: 200, body: new TextEncoder().encode(JSON.stringify({ active: activeJob })) }
    : new Promise(() => {}));
  assert.equal(await settleJobBeforeClose(request, async () => "cancel", { timeoutMs: 50 }), "close");
});

test("대화 상자를 띄우지 못하면 닫지 않는다 (D2b-5c 리뷰 R5)", async () => {
  const { request } = fakeService(activeJob);
  assert.equal(await settleJobBeforeClose(request, async () => { throw Error("창 없음"); }), "stay");
});

test("200이 아닌 응답이나 cancel 밖의 답은 닫거나 남는다", async () => {
  const notOk = async () => ({ status: 503, body: new TextEncoder().encode("{}") });
  assert.equal(await settleJobBeforeClose(notOk, async () => "cancel"), "close");
  const { request, calls } = fakeService(activeJob);
  assert.equal(await settleJobBeforeClose(request, async () => undefined), "stay");
  assert.equal(calls.length, 1);
});
