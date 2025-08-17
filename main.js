const { app, BrowserWindow, BrowserView, ipcMain, shell, dialog, session } = require('electron');
const path = require('path');

let win;
let tabs = []; // {id, view, url, title}
let activeTabId = null;
let nextTabId = 1;

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 820,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      enableRemoteModule: false
    }
  });

  win.loadFile('index.html');

  // Permission handling (show UI in renderer via IPC)
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    // forward to renderer to show permission pop-up and wait for response
    const requestId = Math.random().toString(36).slice(2);
    const origin = details.requestingUrl || webContents.getURL();
    win.webContents.send('permission-request', { requestId, permission, origin });
    ipcMain.once(`permission-response-${requestId}`, (e, { allow }) => {
      callback(allow);
    });
  });

  // Download handling
  session.defaultSession.on('will-download', (event, item, webContents) => {
    const url = item.getURL();
    const total = item.getTotalBytes();
    const filename = item.getFilename();
    // ask user where to save
    const savePath = dialog.showSaveDialogSync(win, { defaultPath: filename });
    if (!savePath) { item.cancel(); return; }
    item.setSavePath(savePath);
    // notify renderer
    const downloadId = Math.random().toString(36).slice(2);
    win.webContents.send('download-start', { downloadId, filename, url, total, savePath });
    item.on('updated', (ev, state) => {
      if (state === 'progressing') {
        win.webContents.send('download-progress', { downloadId, received: item.getReceivedBytes(), total });
      }
    });
    item.once('done', (ev, state) => {
      win.webContents.send('download-done', { downloadId, state, savePath });
    });
  });

  // handle open-external requests
  ipcMain.handle('open-external', (_, url) => {
    return shell.openExternal(url);
  });

  // create first tab
  createTab('https://example.com');
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => app.quit());

/* Tab management */
function createTab(url = 'https://example.com') {
  const id = nextTabId++;
  const view = new BrowserView({
    webPreferences: {
      preload: path.join(__dirname, 'tab-preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  // attach to window but hidden until set active
  win.addBrowserView(view);
  resizeView(view);

  view.webContents.loadURL(url);
  view.webContents.on('page-title-updated', (e, title) => {
    tabs = tabs.map(t => t.id === id ? { ...t, title } : t);
    sendTabsUpdate();
  });

  // intercept new-window / target=_blank
  view.webContents.setWindowOpenHandler(({ url }) => {
    // open in a new tab
    createTab(url);
    return { action: 'deny' };
  });

  // inject overrides for dialogs when page loads
  view.webContents.on('did-finish-load', async () => {
    try {
      await view.webContents.executeJavaScript(`
        (function(){
          if (window.__custom_dialogs_installed) return;
          window.__custom_dialogs_installed = true;
          const send = (type, payload) => {
            window.postMessage({ __fromBrowserHost: true, type, payload }, '*');
          };
          window.alert = function(msg){ return new Promise(resolve => { send('alert', { message: String(msg) }); window.__last_alert_resolve = resolve; }); };
          window.confirm = function(msg){ return new Promise(resolve => { send('confirm', { message: String(msg) }); window.__last_confirm_resolve = resolve; }); };
          window.prompt = function(msg, defaultVal=''){ return new Promise(resolve => { send('prompt', { message: String(msg), defaultVal: String(defaultVal) }); window.__last_prompt_resolve = resolve; }); };
          // receive answers from host
          window.addEventListener('message', (ev) => {
            const d = ev.data;
            if (!d || !d.__toContent) return;
            if (d.type === 'alert-response' && window.__last_alert_resolve) { window.__last_alert_resolve(); window.__last_alert_resolve = null; }
            if (d.type === 'confirm-response' && window.__last_confirm_resolve) { window.__last_confirm_resolve(!!d.answer); window.__last_confirm_resolve = null; }
            if (d.type === 'prompt-response' && window.__last_prompt_resolve) { window.__last_prompt_resolve(d.answer ?? null); window.__last_prompt_resolve = null; }
          });
        })();
      `);
    } catch (err) {
      // injection may fail on some pages due to CSP, ignore
      console.warn('dialog injection failed', err.message);
    }
  });

  // forward content messages to main window (renderer) via IPC
  view.webContents.on('console-message', (e, level, message, line, sourceId) => {
    // optional: forward console to main UI
  });

  view.webContents.on('ipc-message', (event, channel, args) => {
    // not used
  });

  tabs.push({ id, view, url, title: url });
  setActiveTab(id);
  sendTabsUpdate();
  return id;
}

function resizeView(view) {
  const [w, h] = win.getContentSize();
  // top UI height in index.html is 72px
  view.setBounds({ x: 0, y: 72, width: w, height: h - 72 });
  view.setAutoResize({ width: true, height: true });
}

function setActiveTab(id) {
  activeTabId = id;
  // reorder so active view is on top (bringToFront simulated)
  tabs.forEach(t => {
    if (t.id === id) {
      win.addBrowserView(t.view);
      resizeView(t.view);
    } else {
      // leave them attached but behind; keep them all attached for simplicity
      // alternatively we could removeBrowserView to improve perf
    }
  });
  sendTabsUpdate();
}

/* IPC from renderer UI */
ipcMain.handle('create-tab', (_, url) => createTab(url));
ipcMain.handle('navigate-tab', (_, { id, url }) => {
  const t = tabs.find(x => x.id === id);
  if (!t) return false;
  t.view.webContents.loadURL(url);
  return true;
});
ipcMain.handle('get-tabs', () => tabs.map(t => ({ id: t.id, url: t.view.webContents.getURL(), title: t.title })));
ipcMain.handle('set-active-tab', (_, id) => { setActiveTab(id); });
ipcMain.handle('go-back', (_, id) => { const t = tabs.find(x=>x.id===id); if (t && t.view.webContents.canGoBack()) t.view.webContents.goBack(); });
ipcMain.handle('go-forward', (_, id) => { const t = tabs.find(x=>x.id===id); if (t && t.view.webContents.canGoForward()) t.view.webContents.goForward(); });
ipcMain.handle('reload', (_, id) => { const t = tabs.find(x=>x.id===id); if (t) t.view.webContents.reload(); });
ipcMain.handle('toggle-devtools', (_, id) => { const t = tabs.find(x=>x.id===id); if (t) t.view.webContents.toggleDevTools(); });

/* forward postMessage-style dialog events from BrowserView content to renderer UI */
ipcMain.on('content-dialog', (e, data) => {
  // forward to UI to show a modal and get user response
  const id = Math.random().toString(36).slice(2);
  win.webContents.send('show-content-dialog', { id, ...data });
  ipcMain.once(`content-dialog-response-${id}`, (ev, resp) => {
    // identify which BrowserView to send to (use focused webContents)
    const focused = BrowserWindow.getAllWindows()[0].getBrowserView(); // may be naive
    // instead send to all views — they ignore if not matching
    tabs.forEach(t => {
      try {
        t.view.webContents.executeJavaScript(`window.postMessage({ __toContent: true, type: "${data.type}-response", answer: ${JSON.stringify(resp.answer)} }, "*");`);
      } catch (err) {}
    });
  });
});

/* helper: notify renderer about tabs */
function sendTabsUpdate() {
  const publicTabs = tabs.map(t => ({ id: t.id, url: t.view.webContents.getURL(), title: t.title }));
  win.webContents.send('tabs-updated', { tabs: publicTabs, activeTabId });
}

/* handle permission response from renderer */
ipcMain.on('permission-response', (e, { requestId, allow }) => {
  ipcMain.emit(`permission-response-${requestId}`, null, { allow });
});
