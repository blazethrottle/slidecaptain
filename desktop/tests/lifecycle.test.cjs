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
// D2a-3: 같은 자료 폴더를 다른 SlideCaptain이 쓰면 서비스가 오류 신호를 내고 끝난다.
// 시간 초과를 기다리지 않고 즉시 사용자 문구로 알린다. 다른 실행의 오류 신호는 따르지 않는다.
const errorService = (instanceExpr) =>
  "const i=" + instanceExpr + ";console.log(JSON.stringify({event:'error',product:'slidecaptain'," +
  "desktop_instance_id:i,code:'data_dir_in_use',holder_started_at:'2026-10-08T10:00:00+09:00'}));process.exit(3)";
test("data directory in use is reported at once with a user message and code", async () => {
  const started = Date.now();
  await assert.rejects(
    startService({
      command: process.execPath,
      args: ["-e", errorService("process.env.SLIDECAPTAIN_DESKTOP_INSTANCE")],
      version: "0.2.0",
      timeoutMs: 20000,
    }),
    (error) => {
      assert.equal(error.code, "data_dir_in_use");
      assert.match(error.message, /다른 SlideCaptain/);
      assert.match(error.userMessage, /자료 폴더/);
      return true;
    },
  );
  assert.ok(Date.now() - started < 5000);
});
test("an error record from another instance is not trusted", async () => {
  await assert.rejects(
    startService({
      command: process.execPath,
      args: ["-e", errorService("'other-instance'")],
      version: "0.2.0",
      timeoutMs: 5000,
    }),
    (error) => {
      assert.notEqual(error.code, "data_dir_in_use");
      assert.match(error.message, /종료되었습니다|준비 응답/);
      return true;
    },
  );
});
