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
  const folder = await fs.mkdtemp(
      path.join(os.tmpdir(), "slidecaptain-desktop-smoke-"),
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
  let service;
  const unrelated = http.createServer((_request, response) => response.end("unrelated"));
  await new Promise(resolve => unrelated.listen(0, "127.0.0.1", resolve));
  const unrelatedOrigin = "http://127.0.0.1:" + unrelated.address().port;
  try {
    service = await startService({
      command,
      args: [...args, "--data-dir", data],
      cwd: root,
      env: { PYTHONPATH: path.join(root, "backend") },
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
      env: { PYTHONPATH: path.join(root, "backend") },
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
