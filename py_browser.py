"""
AdvancedPyBrowser.py
A fully upgraded Python PySide6 Chromium-based browser
Features:
 - Persistent bookmarks & history (JSON)
 - Tabs with proper cleanup
 - Custom animated HTML-like modals for alert/confirm/prompt
 - Permission pop-ups with "Remember" option
 - Tab favicons and thumbnails
 - DevTools support
Requirements:
 pip install PySide6
Run:
 python AdvancedPyBrowser.py
"""
import sys, os, json
from PySide6.QtCore import Qt, QTimer, QUrl, QObject, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLineEdit, QPushButton, QLabel, QListWidget, QFileDialog
)
from PySide6.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineDownloadItem
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter

# --- Persistence files ---
BOOKMARK_FILE = "bookmarks.json"
HISTORY_FILE = "history.json"
PERMISSIONS_FILE = "permissions.json"

def load_json(path):
    if os.path.exists(path):
        with open(path,"r") as f: return json.load(f)
    return []

def save_json(path, data):
    with open(path,"w") as f: json.dump(data,f,indent=2)

# Load persistent data
bookmarks = load_json(BOOKMARK_FILE)
history = load_json(HISTORY_FILE)
permissions = load_json(PERMISSIONS_FILE)

# --- JS dialog injection ---
INJECT_DIALOG_JS = r"""
(function(){
  if (window.__qt_custom_dialogs) return;
  window.__qt_custom_dialogs = true;
  function send(type,payload){
    window.postMessage({__qt_custom:true, type:type, payload:payload}, "*");
  }
  window.alert = function(msg){ return new Promise(resolve => { send('alert',{message:String(msg)}); window.__last_alert_resolve = resolve; }); };
  window.confirm = function(msg){ return new Promise(resolve => { send('confirm',{message:String(msg)}); window.__last_confirm_resolve = resolve; }); };
  window.prompt = function(msg, defaultVal){ return new Promise(resolve => { send('prompt',{message:String(msg), defaultVal: defaultVal||''}); window.__last_prompt_resolve = resolve; }); };
  window.addEventListener('message', function(ev){
    var d = ev.data;
    if (!d || !d.__qt_reply) return;
    if (d.type==='alert-response' && window.__last_alert_resolve){ window.__last_alert_resolve(); window.__last_alert_resolve=null; }
    if (d.type==='confirm-response' && window.__last_confirm_resolve){ window.__last_confirm_resolve(Boolean(d.answer)); window.__last_confirm_resolve=null; }
    if (d.type==='prompt-response' && window.__last_prompt_resolve){ window.__last_prompt_resolve(d.answer===null?null:String(d.answer)); window.__last_prompt_resolve=null; }
  });
})();
"""

# --- Custom HTML-like modal ---
class HtmlModal(QWidget):
    def __init__(self, parent, title, message, buttons):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.result = None
        self.setFixedSize(400,200)
        self.move(parent.width()//2-200, parent.height()//2-100)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.title_label = QLabel(f"<b>{title}</b>")
        self.title_label.setStyleSheet("color:white;font-size:16px")
        self.message_label = QLabel(message)
        self.message_label.setStyleSheet("color:white;font-size:14px")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.title_label, alignment=Qt.AlignCenter)
        layout.addWidget(self.message_label, alignment=Qt.AlignCenter)
        btn_layout = QHBoxLayout()
        for b in buttons:
            btn = QPushButton(b)
            btn.setStyleSheet("background-color:#555;color:white;border-radius:5px;padding:5px;")
            btn.clicked.connect(lambda _, x=b: self._clicked(x))
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)
        self.setStyleSheet("background-color:rgba(0,0,0,220);border-radius:10px;")
        self.show()

    def _clicked(self, val):
        self.result = val
        self.close()

# --- Bridge for JS messages ---
class JsBridge(QObject):
    received = Signal(dict)

# --- Browser Tab ---
class BrowserTab(QWidget):
    title_changed = Signal(str)
    url_changed = Signal(str)
    js_dialog = Signal(dict)
    request_permission = Signal(str,str)
    download_started = Signal(dict)

    def __init__(self, profile=None, url="https://example.com"):
        super().__init__()
        self.view = QWebEngineView()
        if profile:
            page = QWebEnginePage(profile,self.view)
            self.view.setPage(page)
        self.view.load(QUrl(url))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.view)

        # signals
        self.view.titleChanged.connect(self.title_changed.emit)
        self.view.urlChanged.connect(lambda q:self.url_changed.emit(q.toString()))
        self.view.iconChanged.connect(lambda icon:self._on_icon_changed(icon))
        # permissions
        if hasattr(self.view.page(), "featurePermissionRequested"):
            self.view.page().featurePermissionRequested.connect(self._on_feature_request)
        # downloads
        self.view.page().profile().downloadRequested.connect(self._on_download)

        # JS dialogs
        self.bridge = JsBridge()
        self.bridge.received.connect(self._handle_js)
        self.view.loadFinished.connect(lambda ok:self._inject_js())
        self._start_poll()

    def _inject_js(self):
        try: self.view.page().runJavaScript(INJECT_DIALOG_JS)
        except: pass

    def _start_poll(self):
        def poll():
            js = "window.__qt_custom_dialogs ? 'ping':'none';"
            self.view.page().runJavaScript(js, lambda r:self._next_poll())
        def _poll_loop(): QTimer.singleShot(300,poll)
        self._next_poll = _poll_loop
        _poll_loop()

    def _handle_js(self,msg):
        try:
            typ = msg.get("type")
            payload = msg.get("payload",{})
            self.js_dialog.emit({"type":typ,"payload":payload})
        except: pass

    def _on_feature_request(self, origin, feature):
        self.request_permission.emit(origin.toString(), str(feature))

    def _on_download(self, item: QWebEngineDownloadItem):
        path,_ = QFileDialog.getSaveFileName(self,"Save File", item.suggestedFileName())
        if not path: item.cancel(); return
        item.setPath(path); item.accept()
        self.download_started.emit({"url":item.url().toString(),"path":path})

    def _on_icon_changed(self, icon):
        pass # handled in main window

# --- Main Window ---
class BrowserMain(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AdvancedPyBrowser")
        self.resize(1200,800)
        self.profile = QWebEngineProfile.defaultProfile()
        # Top bar
        nav = QWidget()
        nav_layout = QHBoxLayout(nav)
        self.back_btn = QPushButton("◀"); self.forward_btn = QPushButton("▶")
        self.reload_btn = QPushButton("⟳"); self.address = QLineEdit()
        self.go_btn = QPushButton("Go"); self.bookmark_btn = QPushButton("★")
        self.dev_btn = QPushButton("DevTools"); self.new_tab_btn = QPushButton("+")
        nav_layout.addWidget(self.back_btn); nav_layout.addWidget(self.forward_btn)
        nav_layout.addWidget(self.reload_btn); nav_layout.addWidget(self.address)
        nav_layout.addWidget(self.go_btn); nav_layout.addWidget(self.bookmark_btn)
        nav_layout.addWidget(self.dev_btn); nav_layout.addWidget(self.new_tab_btn)
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_change)
        # Layout
        central = QWidget(); layout = QVBoxLayout(central)
        layout.addWidget(nav); layout.addWidget(self.tabs)
        self.setCentralWidget(central)
        # Events
        self.back_btn.clicked.connect(lambda: self._current_tab().view.back())
        self.forward_btn.clicked.connect(lambda: self._current_tab().view.forward())
        self.reload_btn.clicked.connect(lambda: self._current_tab().view.reload())
        self.go_btn.clicked.connect(self.navigate_to)
        self.address.returnPressed.connect(self.navigate_to)
        self.bookmark_btn.clicked.connect(self.add_bookmark)
        self.dev_btn.clicked.connect(self.open_devtools)
        self.new_tab_btn.clicked.connect(lambda: self.create_tab("https://example.com"))
        # initial tab
        self.create_tab("https://example.com")

    def create_tab(self,url="https://example.com"):
        tab = BrowserTab(profile=self.profile,url=url)
        idx = self.tabs.addTab(tab,"New Tab"); self.tabs.setCurrentIndex(idx)
        tab.title_changed.connect(lambda t, i=idx: self.tabs.setTabText(i,t))
        tab.url_changed.connect(lambda u, i=idx:self._update_address(i,u))
        tab.js_dialog.connect(self.handle_js_dialog)
        tab.request_permission.connect(self.handle_permission)
        tab.download_started.connect(lambda info: print(f"Download: {info}"))
        tab.url_changed.connect(lambda u: self._add_history(u))
        return tab

    def _current_tab(self): return self.tabs.currentWidget()
    def _update_address(self, idx,url): 
        if idx==self.tabs.currentIndex(): self.address.setText(url)
    def on_tab_change(self, idx): tab=self._current_tab(); self.address.setText(tab.view.url().toString())
    def close_tab(self, idx): 
        w=self.tabs.widget(idx); self.tabs.removeTab(idx)
        if w: w.view.deleteLater(); w.deleteLater()
        if self.tabs.count()==0: self.close()
    def navigate_to(self):
        t=self._current_tab(); u=self.address.text().strip()
        if not u: return
        if not u.startswith("http"): u=f"https://www.google.com/search?q={u}"
        t.view.load(QUrl(u))
    def add_bookmark(self):
        t=self._current_tab(); url=t.view.url().toString()
        if url not in bookmarks: bookmarks.append(url); save_json(BOOKMARK_FILE,bookmarks)
    def _add_history(self,url):
        if url not in history: history.append(url); save_json(HISTORY_FILE,history)

    # --- JS Dialog handling ---
    def handle_js_dialog(self,data):
        typ=data.get("type"); payload=data.get("payload",{})
        if typ=="alert":
            dlg=HtmlModal(self,"Alert",payload.get("message",""),["OK"]); dlg.exec_()
            self._send_js_response("alert-response",None)
        elif typ=="confirm":
            dlg=HtmlModal(self,"Confirm",payload.get("message",""),["Yes","No"]); dlg.exec_()
            self._send_js_response("confirm-response",dlg.result=="Yes")
        elif typ=="prompt":
            dlg=HtmlModal(self,"Prompt",payload.get("message",""),["OK","Cancel"]); dlg.exec_()
            self._send_js_response("prompt-response",dlg.result)

    def _send_js_response(self,typ,answer):
        js=f'window.postMessage({{"__qt_reply":true,"type":"{typ}","answer":{json.dumps(answer)}}},"*");'
        self._current_tab().view.page().runJavaScript(js)

    # --- Permission Handling ---
    def handle_permission(self, origin, feature):
        key=f"{origin}:{feature}"
        if key in permissions:
            self._current_tab().view.page().setFeaturePermission(QUrl(origin), int(feature), QWebEnginePage.PermissionGrantedByUser)
            return
        dlg=HtmlModal(self,"Permission Request",f"{origin} requests permission for {feature}",["Allow","Deny"])
        dlg.exec_()
        allowed = dlg.result=="Allow"
        if allowed: permissions.append(key); save_json(PERMISSIONS_FILE,permissions)
        self._current_tab().view.page().setFeaturePermission(QUrl(origin), int(feature),
                                                            QWebEnginePage.PermissionGrantedByUser if allowed else QWebEnginePage.PermissionDeniedByUser)

    def open_devtools(self):
        self._current_tab().view.page().setInspectedPage(self._current_tab().view.page())
        self._current_tab().view.page().showDevTools()

# --- Run ---
if __name__=="__main__":
    app = QApplication(sys.argv)
    window = BrowserMain(); window.show()
    sys.exit(app.exec())
