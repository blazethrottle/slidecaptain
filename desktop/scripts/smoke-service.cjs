"use strict";
// Functional smoke: isolate every project, exercise the real native bridge and service.
const fs = require("node:fs/promises"),
  path = require("node:path"),
  os = require("node:os");
const { startService, readSelectedFiles } = require("../runtime.cjs");
const http = require("node:http");
const root = path.resolve(__dirname, "../.."),
  version = require("../package.json").version;
async function main() {
  // The service reports canonical export paths. Canonicalize the temp folder too
  // (Windows 8.3 names and junctions, macOS /var -> /private/var) so the
  // containment check below compares like with like.
  const folder = await fs.realpath(
      await fs.mkdtemp(path.join(os.tmpdir(), "slidecaptain-desktop-smoke-")),
    ),
    data = path.join(folder, "projects");
  const executable = process.argv[2],
    command =
      executable ??
      process.env.SLIDECAPTAIN_PYTHON ??
      path.join(
        root,
        "backend",
        ".venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      );
  const args = executable ? [] : ["-m", "slidecaptain.desktop_service"];
  // D2b-2: never reach a real Claude login. A missing CLI path makes the login check fail closed.
  const serviceEnv = {
    PYTHONPATH: path.join(root, "backend"),
    SLIDECAPTAIN_CLAUDE_CLI: path.join(folder, "no-claude-cli"),
  };
  let service;
  const unrelated = http.createServer((_request, response) => response.end("unrelated"));
  await new Promise(resolve => unrelated.listen(0, "127.0.0.1", resolve));
  const unrelatedOrigin = "http://127.0.0.1:" + unrelated.address().port;
  try {
    service = await startService({
      command,
      args: [...args, "--data-dir", data],
      cwd: root,
      env: serviceEnv,
      version,
    });
    if ((await fetch(service.origin + "/api/health")).status !== 403)
      throw Error("Unauthenticated health was accessible");
    const ui = await fetch(service.origin + "/", {
      headers: { "X-SlideCaptain-Session": service.token },
    });
    if (!ui.ok || !(await ui.text()).includes('id="root"'))
      throw Error("Packaged UI missing");
    async function request(apiPath, method = "GET", body, extra = {}) {
      const reply = await service.request({
        path: apiPath,
        method,
        body,
        headers: {
          "X-Requested-With": "SlideCaptain",
          ...(typeof body === "string"
            ? { "Content-Type": "application/json" }
            : {}),
          ...extra,
        },
      });
      if (reply.status >= 400)
        throw Error("API failed " + reply.status + " " + apiPath);
      return {
        value: JSON.parse(new TextDecoder().decode(reply.body)),
        headers: reply.headers,
      };
    }
    await request(
      "/api/projects",
      "POST",
      JSON.stringify({
        name: "desktop-smoke",
        title: "Synthetic desktop report",
      }),
    );
    const file = path.join(folder, "sample.txt");
    await fs.writeFile(file, "합성 자료: 완료 업무 8건");
    const imported = await readSelectedFiles([file]);
    if (imported.files.length !== 1)
      throw Error("Selected source was not read");
    await request(
      "/api/projects/desktop-smoke/sources/sample.txt/upload?overwrite=false",
      "POST",
      imported.files[0].bytes,
    );
    if (
      (await request("/api/projects/desktop-smoke/sources/sample.txt")).value
        .text !== "합성 자료: 완료 업무 8건"
    )
      throw Error("Imported bytes changed");
    const { value: deck, headers } = await request(
      "/api/projects/desktop-smoke/deck",
    );
    deck.structure = {
      chapters: [
        { id: "cover", topic: "Synthetic desktop report", template: "cover" },
      ],
    };
    deck.slides = [
      {
        chapter_id: "cover",
        slots: { template: "cover", title: "Synthetic desktop report" },
      },
    ];
    const etag = headers.find(([key]) => key === "etag")[1];
    await request(
      "/api/projects/desktop-smoke/deck",
      "PUT",
      JSON.stringify(deck),
      { "If-Match": etag },
    );
    if (
      (await request("/api/projects/desktop-smoke/deck")).value.slides[0].slots
        .title !== "Synthetic desktop report"
    )
      throw Error("Saved content missing");
    const result = (
      await request("/api/projects/desktop-smoke/export", "POST", "{}")
    ).value;
    if (
      !result.path.startsWith(data + path.sep) ||
      !(await fs.stat(result.path)).isFile() ||
      result.quality.final_export_allowed
    )
      throw Error("Draft export contract");
    const history = (await request("/api/projects/desktop-smoke/exports")).value;
    if (history.total !== 1 || history.items[0]?.artifact_status !== "matched" || history.items[0]?.slide_count !== 1)
      throw Error("History missing");
    // D2b-2: the job ledger opens in the packaged service and records a generation that cannot log in.
    const status = (await request("/api/status")).value;
    if (status.login.logged_in === true) throw Error("Claude login visible; refusing to register a generation");
    // The missing-CLI override must be what blocked the login, not some other state (D2b-2 review R13).
    if (!String(status.login.error ?? "").includes("SLIDECAPTAIN_CLAUDE_CLI"))
      throw Error("The Claude CLI override did not reach the service: " + JSON.stringify(status.login));
    const registered = await request(
      "/api/projects/desktop-smoke/jobs",
      "POST",
      JSON.stringify({ request_id: "smoke-ledger-0001", kind: "structure", params: {} }),
      { "X-AI-Consent": "SlideCaptain", "X-AI-Selection": status.selection_id },
    );
    let job = registered.value;
    const deadline = Date.now() + 30000;
    while (["queued", "running", "validating", "cancel_requested"].includes(job.state) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      job = (await request("/api/projects/desktop-smoke/jobs/" + job.id)).value;
    }
    if (job.state !== "failed" || job.error?.error_class !== "connection")
      throw Error("Ledger job did not fail closed: " + JSON.stringify(job));
    await fs.access(path.join(data, ".slidecaptain-jobs.sqlite3"));
    try {
      await fs.access(path.join(data, "desktop-smoke", "ai-usage.jsonl"));
      throw Error("A usage record exists although no AI call was allowed");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    // D2a-3: the same data folder cannot get a second service; the first one keeps answering.
    let secondRefused = false;
    try {
      const second = await startService({
        command,
        args: [...args, "--data-dir", data],
        cwd: root,
        env: serviceEnv,
        version,
        timeoutMs: 30000,
      });
      await second.stop();
    } catch (error) {
      secondRefused = error.code === "data_dir_in_use";
      if (!secondRefused) throw Error("Second service failed for another reason: " + error.message);
    }
    if (!secondRefused) throw Error("A second service started on the same data folder");
    if (!(await request("/api/projects/desktop-smoke/deck")).value.meta)
      throw Error("The first service stopped answering after the refused second start");
    const stopping = service.stop();
    if (service.stop() !== stopping) throw Error("Concurrent shutdown did not share completion");
    await stopping;
    try {
      await fetch(service.origin + "/api/health");
      throw Error("Service still alive after parent EOF");
    } catch (error) {
      if (error.message === "Service still alive after parent EOF") throw error;
    }
    const restarted = await startService({
      command,
      args: [...args, "--data-dir", data],
      cwd: root,
      env: serviceEnv,
      version,
    });
    try {
      const reread = await restarted.request({
        path: "/api/projects/desktop-smoke/deck",
      });
      if (
        JSON.parse(new TextDecoder().decode(reread.body)).slides[0].slots
          .title !== "Synthetic desktop report"
      )
        throw Error("Restart lost data");
    } finally {
      await restarted.stop();
    }
    if ((await (await fetch(unrelatedOrigin)).text()) !== "unrelated") throw Error("An unrelated service was affected");
    console.log(
      JSON.stringify({
        mode: executable ? "frozen" : "development",
        ui: "passed",
        native_read_import_save_export_restart: "passed",
        parent_eof_shutdown: "passed",
        unrelated_service_preserved: "passed",
        same_folder_second_service_refused: "passed",
        job_ledger_fail_closed: "passed",
        ai_calls: 0,
      }),
    );
  } finally {
    unrelated.closeAllConnections();
    await new Promise(resolve => unrelated.close(resolve));
    if (service) await service.stop();
    await fs.rm(folder, { recursive: true, force: true });
  }
}
main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
