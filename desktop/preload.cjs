"use strict";
const { contextBridge, ipcRenderer } = require("electron");
// No session value, filesystem API, arbitrary IPC channel, or subprocess handle.
contextBridge.exposeInMainWorld(
  "slidecaptain",
  Object.freeze({
    request: (input) => ipcRenderer.invoke("desktop:request", input),
    cancelRequest: (id) => ipcRenderer.invoke("desktop:cancel-request", id),
    chooseFiles: () => ipcRenderer.invoke("desktop:choose-files"),
    chooseFolder: () => ipcRenderer.invoke("desktop:choose-folder"),
    openLogin: (url) => ipcRenderer.invoke("desktop:open-login", url),
  }),
);
