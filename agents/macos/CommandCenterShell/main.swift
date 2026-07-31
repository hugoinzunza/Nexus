import AppKit
import WebKit

final class CommandCenterDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private var window: NSWindow?
    private var eventMonitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let configuration = WKWebViewConfiguration()
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        configuration.websiteDataStore = .default()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            + "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15"
        webView.navigationDelegate = self
        webView.uiDelegate = self

        let targetScreen = NSScreen.screens.first(where: {
            $0.localizedName.uppercased().contains("ARZOPA")
        }) ?? NSScreen.screens.first(where: {
            Int($0.frame.width) == 1920 && Int($0.frame.height) == 1080
        }) ?? NSScreen.screens.first(where: { $0 != NSScreen.main }) ?? NSScreen.main
        guard let screen = targetScreen else {
            NSApp.terminate(nil)
            return
        }

        let window = NSWindow(
            contentRect: screen.frame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false,
            screen: screen
        )
        window.backgroundColor = .black
        window.level = .floating
        window.collectionBehavior = [.fullScreenPrimary, .stationary]
        window.contentView = webView
        window.setFrame(screen.frame, display: true)
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        self.window = window

        let rawURL = CommandLine.arguments.dropFirst().first
            ?? "http://127.0.0.1:8812/m/command-center/"
        if let url = URL(string: rawURL) {
            webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        }
        eventMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53 || (
                event.modifierFlags.contains(.command)
                    && event.charactersIgnoringModifiers?.lowercased() == "q"
            ) {
                NSApp.terminate(nil)
                return nil
            }
            return event
        }
        NSApp.activate(ignoringOtherApps: true)
        DispatchQueue.main.async {
            NSApp.presentationOptions = [.hideMenuBar, .hideDock]
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let eventMonitor {
            NSEvent.removeMonitor(eventMonitor)
        }
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url {
            NSWorkspace.shared.open(url)
        }
        return nil
    }
}

let application = NSApplication.shared
let delegate = CommandCenterDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
