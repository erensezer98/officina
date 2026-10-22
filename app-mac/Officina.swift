// Officina.app — native window around the Officina page (http://127.0.0.1:<port from config.json>).
// Build: ./build.sh   (swiftc -O -o Officina Officina.swift -framework Cocoa -framework WebKit, then an .app bundle)
// Menu shortcuts call the page directly, so they also work while a terminal tab (ttyd iframe) has focus.
import Cocoa
import WebKit

// config: $OFFICINA_HOME/config.json (default ~/.claude/office/config.json): port + team names for the Go menu
let OFFICE_DIR = ProcessInfo.processInfo.environment["OFFICINA_HOME"] ?? (NSHomeDirectory() + "/.claude/office")
let CONFIG: [String: Any] = {
    guard let d = FileManager.default.contents(atPath: OFFICE_DIR + "/config.json"),
          let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return [:] }
    return j
}()
let PORT = (CONFIG["port"] as? Int) ?? 4242
let TEAM_NAMES: [String] = ((CONFIG["team"] as? [[String: Any]]) ?? []).compactMap { $0["name"] as? String }
let HOME_URL = URL(string: "http://127.0.0.1:\(PORT)/")!

// Terminal tabs (xterm.js in ttyd iframes) swallow ⌘-keys; catch the office shortcuts before the web content sees them.
final class OfficeWebView: WKWebView {
    var onShortcut: ((String) -> Bool)?
    override func performKeyEquivalent(with e: NSEvent) -> Bool {
        let mods = e.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if mods == .command, let k = e.charactersIgnoringModifiers?.lowercased(), ["k", "o", "y", "w", "r", "1", "2", "3", "4", "5", "6", "7"].contains(k),
           onShortcut?(k) == true { return true }
        return super.performKeyEquivalent(with: e)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, NSWindowDelegate {
    var window: NSWindow!
    var web: OfficeWebView!

    func applicationDidFinishLaunching(_ n: Notification) {
        let cfg = WKWebViewConfiguration()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = OfficeWebView(frame: .zero, configuration: cfg)
        web.onShortcut = { [weak self] k in
            guard let s = self else { return false }
            switch k {
            case "k": s.search(); case "o": s.artifacts(); case "y": s.history(); case "w": s.closeFile(); case "r": s.reload()
            default: let m = NSMenuItem(); m.tag = (Int(k) ?? 1) - 1; s.person(m)
            }
            return true
        }
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsMagnification = true
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1500, height: 950),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Officina"
        window.contentView = web
        window.setFrameAutosaveName("OfficinaMain")
        if !window.setFrameUsingName("OfficinaMain") { window.center() }
        window.makeKeyAndOrderFront(nil)
        buildMenu()
        web.load(URLRequest(url: HOME_URL))
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }

    // Links that leave the office open in the default browser.
    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = a.request.url, a.navigationType == .linkActivated, a.targetFrame?.isMainFrame ?? false,
           !(u.host == "127.0.0.1" || u.host == "localhost") {
            NSWorkspace.shared.open(u); decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }
    // window.open to the office (e.g. the artifacts pop-out) opens a second Officina window; anything else goes to the browser.
    var extraWindows: [NSWindow] = []
    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for a: WKNavigationAction, windowFeatures f: WKWindowFeatures) -> WKWebView? {
        guard let u = a.request.url else { return nil }
        if u.host == "127.0.0.1" || u.host == "localhost" {
            let v = WKWebView(frame: .zero, configuration: c)
            v.navigationDelegate = self; v.uiDelegate = self; v.allowsMagnification = true
            let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 850),
                               styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            win.title = u.query?.contains("pane=artifacts") == true ? "Officina · Artifacts" : "Officina"
            win.contentView = v; win.isReleasedWhenClosed = false; win.delegate = self
            win.setFrameAutosaveName("OfficinaExtra")
            if !win.setFrameUsingName("OfficinaExtra") { win.center() }
            win.makeKeyAndOrderFront(nil); extraWindows.append(win)
            return v                                         // WebKit loads the URL into it
        }
        NSWorkspace.shared.open(u); return nil
    }
    func webViewDidClose(_ v: WKWebView) { v.window?.close() }
    // Closing a pop-out: tell its page (so it clears its heartbeat) and drop the web view, so window.open can make a new one.
    func windowWillClose(_ n: Notification) {
        guard let w = n.object as? NSWindow, w !== window, let v = w.contentView as? WKWebView else { return }
        v.evaluateJavaScript("try{localStorage.removeItem('officinaPopHeartbeat');window.dispatchEvent(new Event('pagehide'))}catch(e){}", completionHandler: nil)
        v.stopLoading(); w.contentView = nil
        extraWindows.removeAll { $0 === w }
    }

    // ---- menu ----
    func js(_ s: String) { window.makeFirstResponder(web); web.evaluateJavaScript("try{\(s)}catch(e){}", completionHandler: nil) }
    @objc func reload() { web.reload() }
    @objc func search() { js("pal(true)") }
    @objc func artifacts() { js("show('view')") }
    @objc func history() { js("show('hist')") }
    @objc func closeFile() { js("if(cur==='view'&&V.current)vclose(V.current)") }
    @objc func person(_ m: NSMenuItem) { js("{const p=people()[\(m.tag)];if(p)show(p.key)}") }

    func item(_ t: String, _ a: Selector?, _ k: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
        let i = NSMenuItem(title: t, action: a, keyEquivalent: k); i.keyEquivalentModifierMask = mods; i.target = a == nil ? nil : self; return i
    }

    func buildMenu() {
        let main = NSMenu()
        let appM = NSMenu(); let appI = NSMenuItem(); appI.submenu = appM; main.addItem(appI)
        appM.addItem(item("Hide Officina", #selector(NSApplication.hide(_:)), "h", [.command, .option]))
        appM.items.last?.target = NSApp
        appM.addItem(.separator())
        let q = NSMenuItem(title: "Quit Officina", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); appM.addItem(q)

        let editM = NSMenu(title: "Edit"); let editI = NSMenuItem(); editI.submenu = editM; main.addItem(editI)
        editM.addItem(NSMenuItem(title: "Undo", action: Selector(("undo:")), keyEquivalent: "z"))
        editM.addItem(NSMenuItem(title: "Redo", action: Selector(("redo:")), keyEquivalent: "Z"))
        editM.addItem(.separator())
        editM.addItem(NSMenuItem(title: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x"))
        editM.addItem(NSMenuItem(title: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c"))
        editM.addItem(NSMenuItem(title: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v"))
        editM.addItem(NSMenuItem(title: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a"))

        let goM = NSMenu(title: "Go"); let goI = NSMenuItem(); goI.submenu = goM; main.addItem(goI)
        goM.addItem(item("Search / jump…", #selector(search), "k"))
        goM.addItem(.separator())
        for (i, n) in (TEAM_NAMES.isEmpty ? ["Coordinator"] : TEAM_NAMES).prefix(9).enumerated() {
            let m = item(n, #selector(person(_:)), "\(i + 1)"); m.tag = i; goM.addItem(m)
        }
        goM.addItem(.separator())
        goM.addItem(item("Artifacts", #selector(artifacts), "o"))
        goM.addItem(item("History", #selector(history), "y"))
        goM.addItem(item("Close file", #selector(closeFile), "w"))

        let viewM = NSMenu(title: "View"); let viewI = NSMenuItem(); viewI.submenu = viewM; main.addItem(viewI)
        viewM.addItem(item("Reload", #selector(reload), "r"))   // ⌘+ / ⌘− / ⌘0 stay free for the PDF viewer zoom

        let winM = NSMenu(title: "Window"); let winI = NSMenuItem(); winI.submenu = winM; main.addItem(winI)
        winM.addItem(NSMenuItem(title: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m"))
        NSApp.mainMenu = main; NSApp.windowsMenu = winM
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
