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
