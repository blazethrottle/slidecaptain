const test = require("node:test");
const assert = require("node:assert/strict");
const { startService } = require("../runtime.cjs");
test("missing service executable fails promptly without hanging cleanup", async () => {
  await assert.rejects(
    startService({
      command: "slidecaptain-nonexistent-executable",
      args: [],
      version: "0.2.0",
      timeoutMs: 500,
    }),
    /실행하지 못했습니다/,
  );
});
test("startup timeout closes only its own parent pipe", async () => {
  const code =
    "process.stdin.resume();process.stdin.on('end',()=>process.exit(0));setInterval(()=>{},1000)";
  await assert.rejects(
    startService({
      command: process.execPath,
      args: ["-e", code],
      version: "0.2.0",
      timeoutMs: 80,
    }),
    /초과/,
  );
});
test("invalid readiness record cannot attach an unrelated service", async () => {
  const code =
    "console.log(JSON.stringify({event:'ready',product:'other',port:8765}));process.stdin.resume();process.stdin.on('end',()=>process.exit(0))";
  await assert.rejects(
    startService({
      command: process.execPath,
      args: ["-e", code],
      version: "0.2.0",
      timeoutMs: 1000,
    }),
    /준비 응답/,
  );
});
