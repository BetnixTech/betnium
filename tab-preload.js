const { contextBridge, ipcRenderer } = require('electron');

window.addEventListener('message', (ev) => {
  const d = ev.data;
  if (d && d.__fromBrowserHost) {
    ipcRenderer.sendToHost('content-dialog', d);
  }
});

// expose a safe API for sites (minimal)
contextBridge.exposeInMainWorld('electronSafe', {
  // nothing by default
});
