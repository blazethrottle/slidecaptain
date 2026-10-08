"use strict";
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const fs = require("node:fs/promises");
const path = require("node:path");
const {
  startService,
  assertCaller,
  readSelectedFiles,
  isOfficialLogin,
  settleJobBeforeClose,
} = require("./runtime.cjs");
let service,
  window,
  quitting = false,
  shutdownComplete = false,
  closing = false,
  // 창을 닫기 전 진행 중 AI 작업을 확인했는지 (D2b-5c). 계속 작업을 고르면 다시 거짓이 된다
  jobCloseChecked = false,
  jobCloseChecking = false;
const requests = new Map();
// D2a-3: 앱을 두 번 실행하면 두 번째 실행은 기존 창을 앞으로 가져오고 끝난다.
// 서비스의 자료 폴더 잠금은 그 아래의 방어선이다(다른 설치본이나 웹 모드와 겹칠 때)
let focusWhenShown = false;
const primaryInstance = app.requestSingleInstanceLock();
if (!primaryInstance) {
  shutdownComplete = true;
  app.quit();
} else {
  app.on("second-instance", () => {
    // 첫 실행이 아직 창을 만들기 전이면 창이 뜨는 즉시 앞으로 가져온다 (D2a-3 리뷰 R6)
    if (!window || window.isDestroyed()) {
      focusWhenShown = true;
      return;
    }
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  });
}
const root = path.resolve(__dirname, "..");
function shutdown() {
  if (quitting) return;
  quitting = true;
  for (const controller of requests.values()) controller.abort();
  void Promise.resolve(service?.stop())
    .catch(() => dialog.showErrorBox("SlideCaptain", "앱 서비스 종료를 확인하지 못했습니다."))
    .finally(() => { shutdownComplete = true; app.quit(); });
}
function backendCommand() {
  if (app.isPackaged)
    return {
      command: path.join(
        process.resourcesPath,
        "service",
        "slidecaptain-service" + (process.platform === "win32" ? ".exe" : ""),
      ),
      args: [],
      cwd: app.getPath("userData"),
    };
  return {
    command:
      process.env.SLIDECAPTAIN_PYTHON ??
      path.join(
        root,
        "backend",
        ".venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      ),
    args: ["-m", "slidecaptain.desktop_service"],
    cwd: root,
  };
}
function caller(event) {
  assertCaller(event, window, service.origin);
}
async function chooseFiles(event, folder) {
  caller(event);
  const selected = await dialog.showOpenDialog(window, {
    title: folder ? "자료 폴더 선택" : "자료 파일 선택",
    properties: folder ? ["openDirectory"] : ["openFile", "multiSelections"],
    filters: folder
      ? []
      : [
          {
            name: "문서",
            extensions: [
              "txt",
              "md",
              "csv",
              "xlsx",
              "pdf",
              "pptx",
              "docx",
              "hwp",
              "hwpx",
            ],
          },
        ],
  });
  if (selected.canceled) return { cancelled: true, files: [], notes: [] };
  let files = selected.filePaths;
  if (folder) {
    const entries = await fs.readdir(files[0], { withFileTypes: true });
    if (entries.length > 1000)
      throw Error("폴더 항목이 너무 많습니다. 문서만 모은 폴더를 선택하세요.");
    files = entries
      .filter(
        (e) =>
          e.isFile() &&
          !e.name.startsWith(".") &&
          /\.(txt|md|csv|xlsx|pdf|pptx|docx|hwp|hwpx)$/i.test(e.name),
      )
      .map((e) => path.join(files[0], e.name))
      .sort();
  }
  return readSelectedFiles(files);
}
function registerIPC() {
  ipcMain.handle("desktop:request", async (event, input) => {
    caller(event);
    if (
      !input ||
      typeof input.id !== "string" ||
      !/^[a-f0-9-]{36}$/.test(input.id) ||
      requests.has(input.id) ||
      requests.size >= 128
    )
      throw Error("요청 식별자를 확인하지 못했습니다.");
    const controller = new AbortController();
    requests.set(input.id, controller);
    try {
      return await service.request(input, { signal: controller.signal });
    } finally {
      requests.delete(input.id);
    }
  });
  ipcMain.handle("desktop:cancel-request", (event, id) => {
    caller(event);
    if (typeof id === "string") requests.get(id)?.abort();
  });
  ipcMain.handle("desktop:choose-files", (event) => chooseFiles(event, false));
  ipcMain.handle("desktop:choose-folder", (event) => chooseFiles(event, true));
  ipcMain.handle("desktop:open-login", async (event, url) => {
    caller(event);
    if (!isOfficialLogin(url)) throw Error("공식 로그인 주소가 아닙니다.");
    await shell.openExternal(url);
  });
}
async function start() {
  await fs.mkdir(app.getPath("userData"), { recursive: true });
  const dataDir =
    process.env.SLIDECAPTAIN_DATA_DIR ??
    path.join(app.getPath("home"), "slidecaptain-projects");
  const command = backendCommand();
  service = await startService({
    ...command,
    args: [...command.args, "--data-dir", dataDir],
    env: app.isPackaged ? {} : { PYTHONPATH: path.join(root, "backend") },
    version: app.getVersion(),
  });
  if (quitting) {
    await service.stop();
    return;
  }
  window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 800,
    minHeight: 600,
    show: false,
    title: "SlideCaptain",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });
  const contents = window.webContents;
  const nativeSession = contents.session;
  nativeSession.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false),
  );
  nativeSession.setPermissionCheckHandler(() => false);
  nativeSession.webRequest.onBeforeRequest(
    { urls: ["http://*/*", "https://*/*"] },
    (details, callback) => {
      const url = new URL(details.url);
      callback({
        cancel:
          contents.isDestroyed() ||
          details.webContentsId !== contents.id ||
          url.origin !== service.origin ||
          url.pathname.startsWith("/api/"),
      });
    },
  );
  nativeSession.webRequest.onBeforeSendHeaders(
    { urls: [service.origin + "/*"] },
    (details, callback) => {
      if (
        !contents.isDestroyed() &&
        details.webContentsId === contents.id &&
        !new URL(details.url).pathname.startsWith("/api/")
      )
        callback({
          requestHeaders: {
            ...details.requestHeaders,
            "X-SlideCaptain-Session": service.token,
          },
        });
      else callback({ cancel: true });
    },
  );
  nativeSession.webRequest.onHeadersReceived(
    { urls: [service.origin + "/*"] },
    (details, callback) =>
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          "Content-Security-Policy": [
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-src 'none'",
          ],
        },
      }),
  );
  window.webContents.on("will-navigate", (event, url) => {
    const destination = new URL(url);
    if (
      destination.origin !== service.origin ||
      !["/", "/index.html"].includes(destination.pathname)
    )
      event.preventDefault();
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (isOfficialLogin(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-attach-webview", (event) =>
    event.preventDefault(),
  );
  registerIPC();
  window.once("ready-to-show", () => {
    window?.show();
    if (focusWhenShown) window?.focus();
  });
  service.child.once("exit", () => {
    if (!service.stopping && !quitting) {
      dialog.showErrorBox(
        "SlideCaptain",
        "앱 서비스가 종료되었습니다. 앱을 다시 실행해 주세요.",
      );
      app.quit();
    }
  });
  // 진행 중 AI 작업이 있으면 "계속 작업 / 취소 후 닫기"를 묻는다. 취소 후 닫기는 그 작업에 취소를 요청한 뒤
  // 닫고, 서비스 종료 처리가 남은 행을 정리한다 (계획서 D2b-5c, 5.5)
  window.on("close", (event) => {
    if (jobCloseChecked || quitting) return;
    event.preventDefault();
    if (jobCloseChecking) return;
    jobCloseChecking = true;
    void settleJobBeforeClose(
      (input) => service.request(input),
      async (active) => {
        const { response } = await dialog.showMessageBox(window, {
          type: "warning",
          buttons: ["계속 작업", "취소 후 닫기"],
          defaultId: 0,
          cancelId: 0,
          title: "SlideCaptain",
          message: active.cancel_requested
            ? "AI 생성 작업에 이미 취소를 요청했고 아직 멈추지 않았습니다. 지금 닫을까요?"
            : "AI 생성이 진행 중입니다. 작업을 취소하고 닫을까요?",
          // 결과 없이 끝난 작업은 다시 열 때 구조안 화면(장 내용 생성)이나 스냅샷 복구 화면에서 보인다 (리뷰 R2, R18)
          detail: `프로젝트: ${active.project}. 취소 후 닫으면 다시 열 때 그 작업은 취소됨, 중단됨 또는 완료 여부 확인 필요로 보입니다. 장 내용 생성은 구조안 화면, 그 밖의 작업은 스냅샷 복구 화면에서 볼 수 있습니다.`,
        });
        return response === 1 ? "cancel" : "continue";
      },
    ).catch(() => "stay").then((decision) => {
      jobCloseChecking = false;
      if (decision === "stay") {
        closing = false;
        return;
      }
      jobCloseChecked = true;
      if (window && !window.isDestroyed()) window.close();
    });
  });
  window.webContents.on("will-prevent-unload", (event) => {
    const leave = dialog.showMessageBoxSync(window, {
      type: "warning",
      buttons: ["종료", "계속 작업"],
      defaultId: 1,
      cancelId: 1,
      title: "SlideCaptain",
      message:
        "저장하지 않은 변경이나 진행 중인 작업이 있습니다. 앱을 종료할까요?",
    });
    if (leave === 0) event.preventDefault();
    else {
      closing = false;
      jobCloseChecked = false;
    }
  });
  window.on("closed", () => {
    window = null;
    shutdown();
  });
  await window.loadURL(service.origin + "/");
}
app.on("before-quit", (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  if (quitting) return;
  if (window && !window.isDestroyed()) {
    if (!closing) {
      closing = true;
      window.close();
    }
    return;
  }
  shutdown();
});
// Our closed handler owns async service shutdown; Electron must not exit first.
app.on("window-all-closed", () => {});
app
  .whenReady()
  .then(() => (primaryInstance ? start() : undefined))
  .catch(async (error) => {
    dialog.showErrorBox(
      "SlideCaptain",
      // 서비스가 알린 원인(예: 같은 자료 폴더 사용 중)이 있으면 그 문구를 보인다 (D2a-3)
      error?.userMessage ??
        "앱을 시작하지 못했습니다. 설치 상태와 자료 폴더 접근 권한을 확인해 주세요.",
    );
    if (window && !window.isDestroyed()) window.destroy();
    else shutdown();
  });
