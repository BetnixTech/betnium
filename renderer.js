const api = window.browserAPI;
let currentTabs = [];
let activeTab = null;

const tabsEl = document.getElementById('tabs');
const addressEl = document.getElementById('address');
document.getElementById('go').addEventListener('click', doNavigate);
document.getElementById('address').addEventListener('keydown', (e)=>{ if(e.key==='Enter') doNavigate(); });
document.getElementById('newtab').addEventListener('click', async ()=> {
  const id = await api.createTab('https://example.com');
  refreshTabs();
});
document.getElementById('back').addEventListener('click', ()=> api.goBack(activeTab));
document.getElementById('forward').addEventListener('click', ()=> api.goForward(activeTab));
document.getElementById('reload').addEventListener('click', ()=> api.reload(activeTab));
document.getElementById('devtools').addEventListener('click', ()=> api.toggleDevTools(activeTab));
document.getElementById('openext').addEventListener('click', ()=> api.openExternal(addressEl.value));

api.onTabsUpdated((data)=> {
  currentTabs = data.tabs;
  activeTab = data.activeTabId;
  renderTabs();
  const active = currentTabs.find(t => t.id === activeTab);
  if (active) addressEl.value = active.url;
});

api.onPermissionRequest((data) => {
  showPermissionPopup(data);
});

api.onDownloadStart((d) => {
  showDownloadToast(`Downloading ${d.filename}`);
});
api.onDownloadProgress((d) => {
  showDownloadToast(`Progress: ${Math.round((d.received/d.total)*100)}%`);
});
api.onDownloadDone((d) => {
  showDownloadToast(`Download ${d.state}: ${d.savePath}`);
});

// content dialogs (alert/confirm/prompt) triggered by page injection
api.onShowContentDialog((d) => {
  showContentDialog(d);
});

async function refreshTabs() {
  const tabs = await api.getTabs();
  currentTabs = tabs;
  renderTabs();
}
function renderTabs() {
  tabsEl.innerHTML = '';
  currentTabs.forEach(t => {
    const el = document.createElement('div');
    el.className = 'tab' + (t.id === activeTab ? ' active' : '');
    el.innerHTML = `<span class="title">${escapeHtml(t.title || t.url)}</span><span class="close" data-id="${t.id}">✕</span>`;
    el.addEventListener('click', () => api.setActiveTab(t.id));
    el.querySelector('.close').addEventListener('click', (e) => {
      e.stopPropagation();
      // naive close: just remove tab from UI (main process currently doesn't implement close)
      el.remove();
    });
    tabsEl.appendChild(el);
  });
}
function escapeHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function doNavigate(){
  let u = addressEl.value.trim();
  if (!u) return;
  if (!/^https?:\/\//i.test(u)) {
    // treat as search
    u = 'https://www.google.com/search?q=' + encodeURIComponent(u);
  }
  api.navigateTab(activeTab, u);
}

function showPermissionPopup({ requestId, permission, origin }) {
  const mod = document.createElement('div');
  mod.className = 'modal';
  mod.innerHTML = `<h4>Permission request</h4>
    <div><strong>${permission}</strong> requested by <em>${origin}</em></div>
    <div class="buttons">
      <button id="deny">Deny</button>
      <button id="allow">Allow</button>
    </div>`;
  document.getElementById('modals').appendChild(mod);
  mod.querySelector('#allow').addEventListener('click', () => {
    api.sendPermissionResponse(requestId, true);
    mod.remove();
  });
  mod.querySelector('#deny').addEventListener('click', () => {
    api.sendPermissionResponse(requestId, false);
    mod.remove();
  });
}

function showDownloadToast(msg){
  const el = document.createElement('div');
  el.className = 'modal';
  el.style.top = 'auto';
  el.style.bottom = '20px';
  el.innerHTML = `<div>${escapeHtml(msg)}</div><div style="text-align:right;margin-top:8px;"><button onclick="this.parentElement.parentElement.remove()">Close</button></div>`;
  document.getElementById('modals').appendChild(el);
  setTimeout(()=>{ try{ el.remove(); }catch(e){} }, 10000);
}

/* content dialogs */
function showContentDialog(data){
  // data: { id, type:'alert'|'confirm'|'prompt', payload: { message, defaultVal? } }
  const id = data.id;
  const type = data.type;
  const p = data.payload || {};
  const mod = document.createElement('div');
  mod.className = 'modal';
  let html = `<h4>${type}</h4><div>${escapeHtml(p.message || '')}</div>`;
  if (type === 'prompt') {
    html += `<div style="margin-top:8px;"><input id="prompt-input" value="${escapeHtml(p.defaultVal||'')}" style="width:100%;padding:6px;border:1px solid #ccc;border-radius:4px;"></div>`;
  }
  html += `<div class="buttons">`;
  if (type === 'alert') html += `<button id="ok">OK</button>`;
  else html += `<button id="cancel">Cancel</button><button id="ok">OK</button>`;
  html += `</div>`;
  mod.innerHTML = html;
  document.getElementById('modals').appendChild(mod);
  mod.querySelector('#ok').addEventListener('click', () => {
    const answer = (type === 'prompt') ? document.getElementById('prompt-input').value : true;
    api.sendContentDialogResponse(id, answer);
    mod.remove();
  });
  const cancelBtn = mod.querySelector('#cancel');
  if (cancelBtn) cancelBtn.addEventListener('click', () => {
    api.sendContentDialogResponse(id, false);
    mod.remove();
  });
}

refreshTabs();
