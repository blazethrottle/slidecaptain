"use strict";
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const constants = require("node:fs").constants;
const path = require("node:path");
const routes = require("./api-routes.json").map((r) => ({
  ...r,
  pattern: new RegExp(
    "^" +
      r.path
        .split(/(\{[^}]+\})/)
        .map((s) =>
          s.startsWith("{")
            ? "[^/]+"
            : s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
        )
        .join("") +
      "$",
  ),
}));
const MAX_FILE = 20 * 1024 * 1024,
  MAX_TOTAL = 40 * 1024 * 1024,
  MAX_COUNT = 100;
const extensions = new Set([
  ".txt",
  ".md",
  ".csv",
  ".xlsx",
  ".pdf",
  ".pptx",
  ".docx",
  ".hwp",
  ".hwpx",
]);
const allowedHeaders = new Set([
  "content-type",
  "x-requested-with",
  "x-ai-consent",
  "x-ai-selection",
  "if-match",
  "if-none-match",
]);
function validateRequest(input, origin, token) {
  if (
    !input ||
    typeof input !== "object" ||
    typeof input.path !== "string" ||
    !input.path.startsWith("/api/") ||
    input.path.length > 8192
  )
    throw Error("허용된 앱 API 경로가 아닙니다.");
  const url = new URL(input.path, origin),
    method = input.method ?? "GET";
  if (
    url.origin !== origin ||
    url.hash ||
    !["GET", "POST", "PUT", "DELETE"].includes(method)
  )
    throw Error("허용되지 않은 API 요청입니다.");
  for (const part of input.path.split("?")[0].split("/")) {
    const decoded = decodeURIComponent(part);
    if ([".", ".."].includes(decoded) || /[\\/\u0000-\u001f]/.test(decoded))
      throw Error("허용되지 않은 API 경로입니다.");
  }
  if (
    !routes.some(
      (r) => r.methods.includes(method) && r.pattern.test(url.pathname),
    )
  )
    throw Error("등록되지 않은 API 요청입니다.");
  const headers = {};
  for (const [key, value] of Object.entries(input.headers ?? {})) {
    if (
      !allowedHeaders.has(key.toLowerCase()) ||
      typeof value !== "string" ||
      value.length > 8192 ||
      /[\r\n]/.test(value)
    )
      throw Error("허용되지 않은 요청 헤더입니다.");
    headers[key] = value;
  }
  headers["X-SlideCaptain-Session"] = token;
  let body = input.body;
  if (body != null) {
    if (
      !["POST", "PUT"].includes(method) ||
      !(
        typeof body === "string" ||
        body instanceof Uint8Array ||
        body instanceof ArrayBuffer
      )
    )
      throw Error("허용되지 않은 요청 본문입니다.");
    const length =
      typeof body === "string" ? Buffer.byteLength(body) : body.byteLength;
    if (length > MAX_FILE) throw Error("요청 본문이 너무 큽니다.");
  }
  return {
    url: url.href,
    method,
    headers,
    body: body instanceof ArrayBuffer ? new Uint8Array(body) : body,
  };
}
function validateReady(data, version, instance) {
  if (
    !data ||
    data.event !== "ready" ||
    data.product !== "slidecaptain" ||
    data.version !== version ||
    data.desktop_instance_id !== instance ||
    data.ui_ready !== true ||
    !Number.isInteger(data.port) ||
    data.port < 1 ||
    data.port > 65535
  )
    throw Error("앱 서비스의 실행 정보를 확인하지 못했습니다.");
  return "http://127.0.0.1:" + data.port;
}
// 서비스가 준비 신호 대신 낼 수 있는 오류 신호의 사용자 문구 (D2a-3)
const SERVICE_ERRORS = {
  data_dir_in_use:
    "같은 자료 폴더를 다른 SlideCaptain이 사용하고 있습니다. 다른 SlideCaptain 창이나 웹 실행 창을 닫은 뒤 다시 실행해 주세요.",
};
function serviceError(data, instance) {
  if (
    !data ||
    data.event !== "error" ||
    data.product !== "slidecaptain" ||
    data.desktop_instance_id !== instance ||
    !Object.prototype.hasOwnProperty.call(SERVICE_ERRORS, data.code)
  )
    return null;
  const error = Error(SERVICE_ERRORS[data.code]);
  error.code = data.code;
  error.userMessage = SERVICE_ERRORS[data.code];
  return error;
}
function isOfficialLogin(value) {
  try {
    const u = new URL(value);
    return (
      typeof value === "string" &&
      value.length <= 8192 &&
      u.protocol === "https:" &&
      [
        "auth.openai.com",
        "auth0.openai.com",
        "chatgpt.com",
        "claude.ai",
      ].includes(u.hostname) &&
      !u.username &&
      !u.password &&
      (!u.port || u.port === "443")
    );
  } catch {
    return false;
  }
}
function assertCaller(event, window, origin) {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame ||
    new URL(event.senderFrame.url).origin !== origin
  )
    throw Error("앱의 현재 창에서만 실행할 수 있습니다.");
}
async function readSelectedFiles(selected) {
  if (!Array.isArray(selected) || selected.length > MAX_COUNT)
    throw Error("한 번에 최대 100개 문서를 선택하세요.");
  const files = [],
    notes = [];
  let total = 0;
  for (const selectedPath of selected) {
    let handle;
    const name = path.basename(selectedPath);
    try {
      if (
        name.startsWith(".") ||
        !extensions.has(path.extname(name).toLowerCase())
      )
        throw Error("지원 대상 문서 형식이 아닙니다.");
      const before = await fs.lstat(selectedPath);
      if (!before.isFile() || before.isSymbolicLink())
        throw Error("일반 문서 파일이 아닙니다.");
      if (before.size > MAX_FILE) throw Error("20MB를 넘는 파일입니다.");
      if (total + before.size > MAX_TOTAL)
        throw Error("전체 40MB 읽기 한도를 넘습니다.");
      handle = await fs.open(
        selectedPath,
        constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0),
      );
      const opened = await handle.stat();
      if (
        !opened.isFile() ||
        opened.dev !== before.dev ||
        opened.ino !== before.ino ||
        opened.size !== before.size
      )
        throw Error("선택 후 파일이 바뀌었습니다. 다시 선택하세요.");
      // Read at most the approved size: a growing file cannot bypass the budget.
      const bytes = Buffer.alloc(opened.size);
      let offset = 0;
      while (offset < bytes.length) {
        const read = await handle.read(
          bytes,
          offset,
          bytes.length - offset,
          offset,
        );
        if (!read.bytesRead) break;
        offset += read.bytesRead;
      }
      const after = await handle.stat();
      if (
        offset !== bytes.length ||
        after.size !== opened.size ||
        after.mtimeMs !== opened.mtimeMs
      )
        throw Error("읽는 동안 파일이 바뀌었습니다. 다시 선택하세요.");
      total += bytes.length;
      files.push({ name, bytes: new Uint8Array(bytes) });
    } catch (error) {
      notes.push({
        name,
        reason: error.code ? "파일을 읽을 수 없습니다." : error.message,
      });
    } finally {
      if (handle) await handle.close();
    }
  }
  return { cancelled: false, files, notes };
}
async function startService({
  command,
  args,
  cwd,
  env = {},
  version,
  timeoutMs = 60000,
}) {
  const token = crypto.randomBytes(32).toString("hex"),
    instance = crypto.randomBytes(16).toString("hex");
  const child = spawn(command, args, {
    cwd,
    env: {
      ...process.env,
      ...env,
      SLIDECAPTAIN_DESKTOP_SESSION: token,
      SLIDECAPTAIN_DESKTOP_INSTANCE: instance,
    },
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  // Do not relay raw process output into UI or append session configuration to logs.
  child.stderr.resume();
  child.stdin.on("error", () => {});
  let stopping = false,
    stopPromise;
  function stop() {
    if (stopPromise) return stopPromise;
    if (!child.pid || child.exitCode !== null || child.signalCode !== null)
      return Promise.resolve();
    stopping = true;
    stopPromise = new Promise((resolve, reject) => {
      let timer, forcedTimer;
      const done = () => {
        clearTimeout(timer);
        clearTimeout(forcedTimer);
        child.removeListener("exit", done);
        resolve();
      };
      child.once("exit", done);
      child.stdin.end();
      timer = setTimeout(() => {
        child.kill("SIGKILL");
        forcedTimer = setTimeout(() => {
          child.removeListener("exit", done);
          reject(Error("앱 서비스 종료를 확인하지 못했습니다."));
        }, 3000);
      }, 11000);
      if (child.exitCode !== null || child.signalCode !== null) done();
    });
    return stopPromise;
  }

  try {
    const ready = await new Promise((resolve, reject) => {
      let buffer = "",
        complete = false;
      const finish = (error, data) => {
        if (complete) return;
        complete = true;
        clearTimeout(timer);
        child.stdout.removeListener("data", onData);
        error ? reject(error) : resolve(data);
      };
      const onData = (chunk) => {
        buffer += chunk.toString("utf8");
        if (buffer.length > 65536)
          return finish(Error("서비스 준비 응답이 너무 큽니다."));
        let line;
        while ((line = buffer.indexOf("\n")) !== -1) {
          const value = buffer.slice(0, line);
          buffer = buffer.slice(line + 1);
          try {
            const data = JSON.parse(value);
            const failure = serviceError(data, instance);
            if (failure) return finish(failure);
            if (data.event === "ready") {
              validateReady(data, version, instance);
              finish(null, data);
            }
          } catch {
            finish(Error("서비스 준비 응답을 확인하지 못했습니다."));
          }
        }
      };
      const timer = setTimeout(
        () => finish(Error("서비스 시작 시간이 초과되었습니다.")),
        timeoutMs,
      );
      child.stdout.on("data", onData);
      child.once("error", () =>
        finish(Error("앱 서비스를 실행하지 못했습니다.")),
      );
      // 종료 직전에 쓴 오류 신호를 놓치지 않도록 표준 출력이 끝날 때까지 기다린다(최대 1초)
      const exited = () => finish(Error("앱 서비스가 준비 중 종료되었습니다."));
      child.once("exit", () => {
        if (child.stdout.readableEnded) return exited();
        child.stdout.once("end", exited);
        setTimeout(exited, 1000);
      });
    });
    child.stdout.resume();
    const origin = validateReady(ready, version, instance);
    const health = await fetch(origin + "/api/health", {
      headers: { "X-SlideCaptain-Session": token },
      signal: AbortSignal.timeout(10000),
    });
    if (!health.ok) throw Error("앱 서비스에 연결하지 못했습니다.");
    const h = await health.json();
    validateReady(
      { ...h, event: "ready", port: ready.port },
      version,
      instance,
    );
    if (child.exitCode !== null || child.signalCode !== null)
      throw Error("앱 서비스가 준비 중 종료되었습니다.");
    async function request(input, { signal } = {}) {
      const safe = validateRequest(input, origin, token);
      const response = await fetch(safe.url, {
        method: safe.method,
        headers: safe.headers,
        body: safe.body,
        redirect: "error",
        signal,
      });
      const length = Number(response.headers.get("content-length") ?? 0);
      if (length > 64 * 1024 * 1024) throw Error("응답이 너무 큽니다.");
      const chunks = [];
      let received = 0;
      const reader = response.body?.getReader();
      if (reader) {
        try {
          while (true) {
            const part = await reader.read();
            if (part.done) break;
            received += part.value.byteLength;
            if (received > 64 * 1024 * 1024) throw Error("응답이 너무 큽니다.");
            chunks.push(part.value);
          }
        } finally {
          await reader.cancel();
        }
      }
      const body = new Uint8Array(received);
      let position = 0;
      for (const chunk of chunks) {
        body.set(chunk, position);
        position += chunk.byteLength;
      }
      return {
        status: response.status,
        statusText: response.statusText,
        headers: [...response.headers].filter(([key]) =>
          ["content-type", "etag", "cache-control"].includes(key),
        ),
        body,
      };
    }
    return {
      origin,
      token,
      instance,
      child,
      request,
      stop,
      get stopping() {
        return stopping;
      },
    };
  } catch (error) {
    await stop();
    throw error;
  }
}
module.exports = {
  validateRequest,
  validateReady,
  isOfficialLogin,
  assertCaller,
  readSelectedFiles,
  startService,
};
