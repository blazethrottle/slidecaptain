"use strict";
// Resolve external build paths before electron-builder interprets its macros.
const fs = require("node:fs");
const path = require("node:path");
const build = require("./package.json").build;
const resource = process.env.SLIDECAPTAIN_BACKEND_RESOURCE;
const output = process.env.SLIDECAPTAIN_DESKTOP_OUTPUT;
if (!resource || !output || !path.isAbsolute(resource) || !path.isAbsolute(output)) {
  throw Error("Specify absolute SLIDECAPTAIN_BACKEND_RESOURCE and SLIDECAPTAIN_DESKTOP_OUTPUT paths.");
}
const executable = path.join(resource, "slidecaptain-service" + (process.platform === "win32" ? ".exe" : ""));
if (!fs.statSync(executable).isFile()) throw Error("Build the desktop service for this host OS first.");
const root = path.resolve(__dirname, "..");
if (output === root || output.startsWith(root + path.sep)) throw Error("Choose a build output outside the checkout.");
module.exports = {
  ...build,
  directories: { output },
  extraResources: [{ from: resource, to: "service", filter: ["**/*"] }],
};
