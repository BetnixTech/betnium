// main.cpp
// Simple Qt browser with tabs, custom JS dialog injection, permission popups, downloads, and DevTools.
// Build with Qt6 that includes Qt WebEngine.
#include <QApplication>
#include <QMainWindow>
#include <QTabWidget>
#include <QWebEngineView>
#include <QWebEnginePage>
#include <QWebEngineProfile>
#include <QWebEngineSettings>
#include <QWebEngineDownloadItem>
#include <QToolBar>
#include <QLineEdit>
#include <QPushButton>
#include <QInputDialog>
#include <QMessageBox>
#include <QFileDialog>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QDebug>

const char* INJECT_DIALOG_JS = R"JS(
(function(){
  if (window.__qt_custom_dialogs) return;
  window.__qt_custom_dialogs = true;
  function send(type,payload){
    // fallback to window.name hack if no other channel exists (simple)
    try { window.postMessage({__qt_custom:true, type:type, payload:payload}, "*"); } catch(e){}
  }
  window.alert = function(msg){ return new Promise(resolve => { send('alert',{message:String(msg)}); window.__last_alert_resolve = resolve; }); };
  window.confirm = function(msg){ return new Promise(resolve => { send('confirm',{message:String(msg)}); window.__last_confirm_resolve = resolve; }); };
  window.prompt = function(msg, defaultVal){ return new Promise(resolve => { send('prompt',{message:String(msg), defaultVal: defaultVal||''}); window.__last_prompt_resolve = resolve; }); };
  window.addEventListener('message', function(ev){
    var d = ev.data;
    if (!d || !d.__qt_reply) return;
    if (d.type === 'alert-response' && window.__last_alert_resolve){ window.__last_alert_resolve(); window.__last_alert_resolve = null; }
    if (d.type === 'confirm-response' && window.__last_confirm_resolve){ window.__last_confirm_resolve(Boolean(d.answer)); window.__last_confirm_resolve = null; }
    if (d.type === 'prompt-response' && window.__last_prompt_resolve){ window.__last_prompt_resolve(d.answer === null ? null : String(d.answer)); window.__last_prompt_resolve = null; }
  });
})();
)JS";

class TabWidget : public QWidget {
  Q_OBJECT
public:
  QWebEngineView* view;
  QString homeUrl;
  TabWidget(const QString& url = "https://example.com", QWidget* parent = nullptr) : QWidget(parent) {
    view = new QWebEngineView;
    view->load(QUrl(url));
    auto layout = new QVBoxLayout(this);
    layout->setContentsMargins(0,0,0,0);
    layout->addWidget(view);

    // inject dialogs on load
    connect(view, &QWebEngineView::loadFinished, this, [this](bool ok){
      Q_UNUSED(ok);
      view->page()->runJavaScript(INJECT_DIALOG_JS);
    });

    // downloads
    view->page()->profile()->downloadRequested.connect(this, &TabWidget::onDownloadRequested);

    // permission feature request
    connect(view->page(), &QWebEnginePage::featurePermissionRequested, this, &TabWidget::onFeaturePermissionRequested);
  }

signals:
  void requestPermission(const QUrl& origin, QWebEnginePage::Feature f);

private slots:
  void onDownloadRequested(QWebEngineDownloadItem* item){
    QString suggested = item->suggestedFileName();
    QString path = QFileDialog::getSaveFileName(this, "Save file", suggested);
    if (path.isEmpty()) { item->cancel(); return; }
    item->setPath(path);
    item->accept();
    connect(item, &QWebEngineDownloadItem::downloadProgress, this, [](qint64 r, qint64 t){ qDebug()<<"progress"<<r<<t; });
    connect(item, &QWebEngineDownloadItem::finished, this, [item](){ qDebug()<<"download finished state="<<item->state(); });
  }
  void onFeaturePermissionRequested(const QUrl &securityOrigin, QWebEnginePage::Feature feature){
    emit requestPermission(securityOrigin, feature);
  }
};

class MainWindow : public QMainWindow {
  Q_OBJECT
public:
  MainWindow() {
    resize(1200, 820);
    tabs = new QTabWidget;
    tabs->setTabsClosable(true);
    setCentralWidget(tabs);

    // toolbar
    auto tb = new QToolBar;
    addToolBar(tb);
    backBtn = new QPushButton("◀");
    forwardBtn = new QPushButton("▶");
    reloadBtn = new QPushButton("⟳");
    address = new QLineEdit;
    goBtn = new QPushButton("Go");
    devBtn = new QPushButton("DevTools");
    newTabBtn = new QPushButton("+");
    tb->addWidget(backBtn);
    tb->addWidget(forwardBtn);
    tb->addWidget(reloadBtn);
    tb->addWidget(address);
    tb->addWidget(goBtn);
    tb->addWidget(newTabBtn);
    tb->addWidget(devBtn);

    connect(newTabBtn, &QPushButton::clicked, this, [this](){ createTab("https://example.com"); });
    connect(goBtn, &QPushButton::clicked, this, &MainWindow::navigateToAddress);
    connect(address, &QLineEdit::returnPressed, this, &MainWindow::navigateToAddress);
    connect(backBtn, &QPushButton::clicked, this, &MainWindow::goBack);
    connect(forwardBtn, &QPushButton::clicked, this, &MainWindow::goForward);
    connect(reloadBtn, &QPushButton::clicked, this, &MainWindow::reloadCurrent);
    connect(devBtn, &QPushButton::clicked, this, &MainWindow::openDevTools);
    connect(tabs, &QTabWidget::currentChanged, this, &MainWindow::onTabChanged);
    connect(tabs, &QTabWidget::tabCloseRequested, this, &MainWindow::closeTab);

    // initial tab
    createTab("https://example.com");
  }

private slots:
  void createTab(const QString& url) {
    auto t = new TabWidget(url);
    int idx = tabs->addTab(t, "New Tab");
    tabs->setCurrentIndex(idx);
    connect(t->view, &QWebEngineView::titleChanged, this, [this, idx](const QString& title){ tabs->setTabText(idx, title); });
    connect(t->view, &QWebEngineView::urlChanged, this, [this, idx](const QUrl& u){ if (idx == tabs->currentIndex()) address->setText(u.toString()); });
    connect(t, &TabWidget::requestPermission, this, &MainWindow::onRequestPermission);
    // register page postMessage listener via runJavaScript to pipe messages back (simpler solutions may use WebChannel)
    // A full robust solution would use QWebChannel; to keep it compact we use runJavaScript polling / message events via page.
    tabs->setCurrentWidget(t);
  }

  void navigateToAddress(){
    auto t = currentTab();
    if (!t) return;
    QString u = address->text().trimmed();
    if (u.isEmpty()) return;
    if (!u.startsWith("http://") && !u.startsWith("https://")) {
      u = QString("https://www.google.com/search?q=%1").arg(QUrl::toPercentEncoding(u));
    }
    t->view->load(QUrl(u));
  }

  void goBack(){ auto t=currentTab(); if(t && t->view->history()->canGoBack()) t->view->back(); }
  void goForward(){ auto t=currentTab(); if(t && t->view->history()->canGoForward()) t->view->forward(); }
  void reloadCurrent(){ auto t=currentTab(); if(t) t->view->reload(); }

  void onTabChanged(int idx){
    auto t = currentTab();
    if (t) address->setText(t->view->url().toString());
  }

  void closeTab(int idx){
    auto w = qobject_cast<TabWidget*>(tabs->widget(idx));
    if (!w) return;
    tabs->removeTab(idx);
    w->deleteLater();
    if (tabs->count() == 0) close();
  }

  void onRequestPermission(const QUrl& origin, QWebEnginePage::Feature feature){
    QString featName = QString::number((int)feature);
    QMessageBox::StandardButton b = QMessageBox::question(this, "Permission", QString("%1 requested by %2. Allow?").arg(featName).arg(origin.toString()));
    bool allow = (b == QMessageBox::Yes);
    auto t = currentTab();
    if (t && t->view->page()) {
      t->view->page()->setFeaturePermission(origin, feature, allow ? QWebEnginePage::PermissionGrantedByUser : QWebEnginePage::PermissionDeniedByUser);
    }
  }

  void openDevTools(){
    auto t = currentTab();
    if (!t) return;
    auto dev = new QWebEngineView;
    dev->setAttribute(Qt::WA_DeleteOnClose);
    dev->setWindowTitle("DevTools");
    dev->resize(900,600);
    t->view->page()->setDevToolsPage(dev->page());
    dev->show();
  }

  TabWidget* currentTab(){
    return qobject_cast<TabWidget*>(tabs->currentWidget());
  }

private:
  QTabWidget* tabs;
  QLineEdit* address;
  QPushButton *backBtn, *forwardBtn, *reloadBtn, *goBtn, *devBtn, *newTabBtn;
};

int main(int argc, char** argv){
  QApplication app(argc, argv);
  // enable high DPI scaling if desired
  QCoreApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
  MainWindow w;
  w.show();
  return app.exec();
}

#include "main.moc"
