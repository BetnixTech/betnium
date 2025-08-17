"""
py_browser.py
A compact Chromium-based browser using PySide6 (Qt WebEngine).
Features:
 - Tabs (QTabWidget) with QWebEngineView per tab
 - Address bar, Back/Forward/Reload
 - Custom HTML modal replacement for alert/confirm/prompt via JS injection + Qt signals
 - Permission pop-ups (camera/mic/geolocation/notifications)
 - Downloads with save dialog + progress notification
 - DevTools toggle per tab (opens a docked window)
 - Simple in-memory bookmarks + history
Requirements:
  pip install PySide6
Run:
  python py_browser.py
"""
import sys
import json
from PySide6.QtCore import QUrl, Qt, Slot, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QInputDialog, QFileDialog, QMessageBox, QListWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage, QWebEngineDownloadItem

# --- Helpers for injecting dialog overrides ---
INJECT_DIALOG_JS = r"""
(function(){
  if (window.__qt_custom_dialogs) return;
  window.__qt_custom_dialogs = true;
  const send = (type, payload) => {
    // Using postMessage to be forwarded by the page's Qt bridge
    window.postMessage({__qt_custom: true, type: type, payload: payload}, "*");
  };
  window.alert = function(msg){
    return new Promise(resolve => { send('alert',{message:String(msg)}); window.__last_alert_resolve = resolve; });
  };
  window.confirm = function(msg){
    return new Promise(resolve => { send('confirm',{message:String(msg)}); window.__last_confirm_resolve = resolve; });
  };
  window.prompt = function(msg, defaultVal){
    return new Promise(resolve => { send('prompt',{message:String(msg), defaultVal: defaultVal||''}); window.__last_prompt_resolve = resolve; });
  };
  window.addEventListener('message', ev => {
    const d = ev.data;
    if (!d || !d.__qt_reply) return;
    if (d.type === 'alert-response' && window.__last_alert_resolve) { window.__last_alert_resolve(); window.__last_alert_resolve = null; }
    if (d.type === 'confirm-response' && window.__last_confirm_resolve) { window.__last_confirm_resolve(Boolean(d.answer)); window.__last_confirm_resolve = null; }
    if (d.type === 'prompt-response' && window.__last_prompt_resolve) { window.__last_prompt_resolve(d.answer === null ? null : String(d.answer)); window.__last_prompt_resolve = null; }
  });
})();
"""

# --- Bridge object to receive messages from JS via evaluateJavaScript polling trick ---
class JsMessageBridge(QObject):
    received = Signal(dict)

# --- Browser Tab Widget (encapsulates a QWebEngineView + UI helpers) ---
class BrowserTab(QWidget):
    title_changed = Signal(str)
    url_changed = Signal(str)
    request_permission = Signal(str, str)  # origin, permission
    js_dialog = Signal(dict)  # {type, payload}
    download_started = Signal(dict)  # info

    def __init__(self, profile=None, url="https://example.com"):
        super().__init__()
        self.view = QWebEngineView()
        if profile:
            # create a page with profile to share downloads/cookies
            page = QWebEnginePage(profile, self.view)
            self.view.setPage(page)
        self.view.load(QUrl(url))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.view)

        # connect signals
        self.view.titleChanged.connect(self.title_changed.emit)
        self.view.urlChanged.connect(lambda q: self.url_changed.emit(q.toString()))
        # permission handling (page feature requests)
        if hasattr(self.view.page(), "featurePermissionRequested"):
            self.view.page().featurePermissionRequested.connect(self._on_feature_request)
        # downloads
        profile = self.view.page().profile()
        profile.downloadRequested.connect(self._on_download)

        # inject JS to override alert/confirm/prompt after load
        self.view.loadFinished.connect(self._inject_dialog_js)

        # intercept postMessage from page: we will poll window.__last_message to catch our message
        self.bridge = JsMessageBridge()
        self.bridge.received.connect(self._handle_incoming_message)
        # start a short timer approach via evaluateJavaScript repeated polling
        self.view.loadFinished.connect(lambda ok: self._start_poll_messages())

    def _start_poll_messages(self):
        # simple polling loop: check window.__qt_message_queue (if present)
        poll_js = r"""
        (function(){
          try{
            const q = window.__qt_message_queue || (function(){
              if (window.__qt_custom_dialogs) {
                window.__qt_message_queue = [];
                window.addEventListener('message', function(ev){
                  const d = ev.data;
                  if (d && d.__from_page_to_qt) window.__qt_message_queue.push(d);
                });
                return window.__qt_message_queue;
              }
              return [];
            })();
            if (q && q.length) {
              const out = JSON.stringify(q.splice(0, q.length));
              out;
            } else { ''; }
          }catch(e){ ''; }
        })();
        """
        # We will run repeatedly using QTimer singleShot style through JS callback chaining
        def poll_once():
            self.view.page().runJavaScript(poll_js, lambda res: self._on_poll_result(res, poll_once))
        poll_once()

    def _on_poll_result(self, res, next_call):
        if res:
            try:
                arr = json.loads(res)
                for item in arr:
                    # our JS above uses window.postMessage; but the safest is to parse item
                    self.bridge.received.emit(item)
            except Exception:
                pass
        # schedule another poll
        from PySide6.QtCore import QTimer
        QTimer.singleShot(300, next_call)

    def _inject_dialog_js(self):
        # First place a small helper on the page to forward messages via queue
        forwarder = r"""
        (function(){
          if (window.__qt_custom_forwarder_installed) return;
          window.__qt_custom_forwarder_installed = true;
          window.__qt_message_queue = [];
          window.addEventListener('message', function(ev){
            const d = ev.data;
            if (d && d.__qt_custom) {
              // push into local queue so host can poll
              window.__qt_message_queue.push(d);
            }
          });
        })();
        """
        self.view.page().runJavaScript(forwarder)
        # Install the dialog overrides
        try:
            self.view.page().runJavaScript(INJECT_DIALOG_JS)
        except Exception:
            pass

    def _handle_incoming_message(self, msg):
        # msg shape: { __qt_custom: true, type: 'alert'|'confirm'|'prompt', payload: {...} }
        try:
            if not msg.get("__qt_custom"): return
            typ = msg.get("type")
            payload = msg.get("payload", {})
            self.js_dialog.emit({"type": typ, "payload": payload})
        except Exception:
            pass

    def _on_feature_request(self, security_origin, feature):
        # security_origin is QUrl, feature is QWebEnginePage.Feature
        origin = security_origin.toString()
        name = str(feature)
        # map to readable
        # emit cross to be handled by main UI
        self.request_permission.emit(origin, feature.name if hasattr(feature, 'name') else str(feature))

    def _on_download(self, download_item: QWebEngineDownloadItem):
        info = {"url": download_item.url().toString(), "total": download_item.totalBytes(), "filename": download_item.path() or download_item.suggestedFileName()}
        self.download_started.emit(info)
        # ask where to save
        suggested = download_item.suggestedFileName()
        path, _ = QFileDialog.getSaveFileName(self, "Save file", suggested)
        if not path:
            download_item.cancel()
            return
        download_item.setPath(path)
        download_item.accept()
        # connect progress
        download_item.downloadProgress.connect(lambda recv, total: print("DL progress", recv, total))
        download_item.finished.connect(lambda: print("DL finished", download_item.state()))

# --- Main Window ---
class BrowserMain(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyBrowser (Qt WebEngine)")
        self.resize(1100, 800)

        # share a profile to have consistent downloads/cookies across views
        self.profile = QWebEngineProfile.defaultProfile()

        # top controls
        nav = QWidget()
        nav_layout = QHBoxLayout(nav)
        self.back_btn = QPushButton("◀")
        self.forward_btn = QPushButton("▶")
        self.reload_btn = QPushButton("⟳")
        self.address = QLineEdit()
        self.go_btn = QPushButton("Go")
        self.bookmark_btn = QPushButton("★")
        self.dev_btn = QPushButton("DevTools")
        nav_layout.addWidget(self.back_btn)
        nav_layout.addWidget(self.forward_btn)
        nav_layout.addWidget(self.reload_btn)
        nav_layout.addWidget(self.address)
        nav_layout.addWidget(self.go_btn)
        nav_layout.addWidget(self.bookmark_btn)
        nav_layout.addWidget(self.dev_btn)

        # tabs
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # bookmarks/history simple lists
        self.bookmarks = []
        self.history = []

        # central layout
        central = QWidget()
        v = QVBoxLayout(central)
        v.addWidget(nav)
        v.addWidget(self.tabs)
        self.setCentralWidget(central)

        # wire up controls
        self.back_btn.clicked.connect(self.go_back)
        self.forward_btn.clicked.connect(self.go_forward)
        self.reload_btn.clicked.connect(self.reload)
        self.go_btn.clicked.connect(self.navigate_to)
        self.address.returnPressed.connect(self.navigate_to)
        self.bookmark_btn.clicked.connect(self.add_bookmark)
        self.dev_btn.clicked.connect(self.toggle_devtools)

        # create initial tab
        self.create_tab("https://example.com")

    def create_tab(self, url="https://example.com"):
        tab = BrowserTab(profile=self.profile, url=url)
        idx = self.tabs.addTab(tab, "New Tab")
        self.tabs.setCurrentIndex(idx)
        tab.title_changed.connect(lambda t, i=idx: self.tabs.setTabText(i, t))
        tab.url_changed.connect(lambda u, i=idx: self._sync_address(i, u))
        tab.js_dialog.connect(self._on_js_dialog)
        tab.request_permission.connect(lambda origin, feature: self._on_permission_request(tab, origin, feature))
        tab.download_started.connect(lambda info: QMessageBox.information(self, "Download started", f"{info['filename']}"))
        # keep history/bookmarks updates
        tab.url_changed.connect(lambda u: self.history.append(u))
        return tab

    def close_tab(self, index):
        widget = self.tabs.widget(index)
        if widget:
            widget.view.deleteLater()
            widget.deleteLater()
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.close()

    def _on_tab_changed(self, index):
        w = self.tabs.widget(index)
        if not w: return
        # update address bar
        self.address.setText(w.view.url().toString())

    def _sync_address(self, tab_index, url):
        current_index = self.tabs.currentIndex()
        # if same tab update bar
        if tab_index == current_index:
            self.address.setText(url)

    def go_back(self):
        w = self.current_tab()
        if w and w.view.history().canGoBack():
            w.view.back()

    def go_forward(self):
        w = self.current_tab()
        if w and w.view.history().canGoForward():
            w.view.forward()

    def reload(self):
        w = self.current_tab()
        if w:
            w.view.reload()

    def navigate_to(self):
        w = self.current_tab()
        if not w: return
        u = self.address.text().strip()
        if not u:
            return
        if not (u.startswith("http://") or u.startswith("https://")):
            # search
            u = "https://www.google.com/search?q=" + QUrl.toPercentEncoding(u).data().decode()
        w.view.load(QUrl(u))

    def add_bookmark(self):
        w = self.current_tab()
        if not w: return
        url = w.view.url().toString()
        self.bookmarks.append(url)
        QMessageBox.information(self, "Bookmark", f"Bookmarked {url}")

    def toggle_devtools(self):
        w = self.current_tab()
        if not w: return
        # open a new QWebEngineView as devtools target and tell page to inspect
        dev = QWebEngineView()
        dev.setWindowTitle("DevTools")
        dev.resize(900,600)
        w.view.page().setDevToolsPage(dev.page())
        dev.show()

    def current_tab(self) -> BrowserTab:
        return self.tabs.currentWidget()

    def _on_js_dialog(self, data):
        # data: {type, payload}
        typ = data.get("type")
        payload = data.get("payload", {})
        if typ == "alert":
            QMessageBox.information(self, "Alert", payload.get("message",""))
            # send response back to page
            self._post_dialog_response('alert-response', None)
        elif typ == "confirm":
            ok = QMessageBox.question(self, "Confirm", payload.get("message","")) == QMessageBox.StandardButton.Yes
            self._post_dialog_response('confirm-response', ok)
        elif typ == "prompt":
            text, ok = QInputDialog.getText(self, "Prompt", payload.get("message",""), text=payload.get("defaultVal",""))
            self._post_dialog_response('prompt-response', text if ok else None)

    def _post_dialog_response(self, typ, answer):
        # call JS to postMessage back with the response. We post to all frames; pages ignore if not relevant
        script = f'window.postMessage({{"__qt_reply":true, "type":"{typ}", "answer": {json.dumps(answer)} }}, "*");'
        # run on current tab's view
        w = self.current_tab()
        if w:
            w.view.page().runJavaScript(script)

    def _on_permission_request(self, tab, origin, feature):
        # present a dialog to the user
        res = QMessageBox.question(self, "Permission Request", f"{feature} requested by {origin} — Allow?")
        allow = (res == QMessageBox.StandardButton.Yes)
        # instruct the page: Qt QtWebEngine uses featurePermission on page, but we can't access the exact callback here in this simplified demo.
        # In a fuller implementation you'd call page.setFeaturePermission(origin, feature, allow? QWebEnginePage.PermissionGrantedByUser : PermissionDeniedByUser)
        try:
            # try to set permission for the page
            if hasattr(tab.view.page(), "setFeaturePermission"):
                from PySide6.QtWebEngineWidgets import QWebEnginePage
                tab.view.page().setFeaturePermission(QUrl(origin), feature, QWebEnginePage.PermissionGrantedByUser if allow else QWebEnginePage.PermissionDeniedByUser)
        except Exception:
            pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = BrowserMain()
    win.show()
    sys.exit(app.exec())
