const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('browserAPI', {
  createTab: (url) => ipcRenderer.invoke('create-tab', url),
  getTabs: () => ipcRenderer.invoke('get-tabs'),
  setActiveTab: (id) => ipcRenderer.invoke('set-active-tab', id),
  navigateTab: (id, url) => ipcRenderer.invoke('navigate-tab', { id, url }),
  goBack: (id) => ipcRenderer.invoke('go-back', id),
  goForward: (id) => ipcRenderer.invoke('go-forward', id),
  reload: (id) => ipcRenderer.invoke('reload', id),
  toggleDevTools: (id) => ipcRenderer.invoke('toggle-devtools', id),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  onTabsUpdated: (cb) => ipcRenderer.on('tabs-updated', (e, data) => cb(data)),
  onPermissionRequest: (cb) => ipcRenderer.on('permission-request', (e, data) => cb(data)),
  sendPermissionResponse: (requestId, allow) => ipcRenderer.send('permission-response', { requestId, allow }),
  onDownloadStart: (cb) => ipcRenderer.on('download-start', (e, d) => cb(d)),
  onDownloadProgress: (cb) => ipcRenderer.on('download-progress', (e, d) => cb(d)),
  onDownloadDone: (cb) => ipcRenderer.on('download-done', (e, d) => cb(d)),
  onShowContentDialog: (cb) => ipcRenderer.on('show-content-dialog', (e, d) => cb(d)),
  sendContentDialogResponse: (id, answer) => ipcRenderer.send(`content-dialog-response-${id}`, { answer })
});
