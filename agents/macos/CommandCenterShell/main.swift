import AppKit
import EventKit
import WebKit

final class CommandCenterWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

final class CommandCenterDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    private var window: NSWindow?
    private var tvWebView: WKWebView?
    private var streamingProcesses: [String: Process] = [:]
    private var eventMonitor: Any?
    private var screenObserver: NSObjectProtocol?
    private var screenRetry: DispatchWorkItem?
    private var screenRetriesRemaining = 60
    private let calendarStore = EKEventStore()

    private var streamingProfileRoot: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/NexUX/StreamingChrome", isDirectory: true)
    }

    private func stopOrphanedStreamingProcesses() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        process.arguments = ["-f", "\(streamingProfileRoot.path)/"]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try? process.run()
        process.waitUntilExit()
    }

    private func configure(_ webView: WKWebView) {
        webView.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            + "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15"
        webView.navigationDelegate = self
        webView.uiDelegate = self
    }

    private func arzopaScreen() -> NSScreen? {
        NSScreen.screens.first(where: {
            $0.localizedName.uppercased().contains("ARZOPA")
        })
    }

    private func initialScreen() -> NSScreen? {
        arzopaScreen() ?? NSScreen.screens.first(where: {
            Int($0.frame.width) == 1920 && Int($0.frame.height) == 1080
        }) ?? NSScreen.screens.first(where: { $0 != NSScreen.main }) ?? NSScreen.main
    }

    private func displayID(_ screen: NSScreen?) -> NSNumber? {
        screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber
    }

    private func moveWindowToArzopaWhenAvailable() {
        guard let window else { return }
        if let screen = arzopaScreen() {
            screenRetry?.cancel()
            screenRetry = nil
            screenRetriesRemaining = 0
            if displayID(window.screen) != displayID(screen) || window.frame != screen.frame {
                window.setFrame(screen.frame, display: true, animate: false)
                window.makeKeyAndOrderFront(nil)
                window.orderFrontRegardless()
            }
            return
        }
        guard screenRetriesRemaining > 0, screenRetry == nil else { return }
        screenRetriesRemaining -= 1
        let retry = DispatchWorkItem { [weak self] in
            self?.screenRetry = nil
            self?.moveWindowToArzopaWhenAvailable()
        }
        screenRetry = retry
        DispatchQueue.main.asyncAfter(deadline: .now() + 1, execute: retry)
    }

    private func monitorScreenConfiguration() {
        screenObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.screenRetriesRemaining = 60
            self?.screenRetry?.cancel()
            self?.screenRetry = nil
            self?.moveWindowToArzopaWhenAvailable()
        }
        moveWindowToArzopaWhenAvailable()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        stopOrphanedStreamingProcesses()
        let configuration = WKWebViewConfiguration()
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(self, name: "commandCenter")
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: "window.__nexuxNativeShell = true;",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        let webView = WKWebView(frame: .zero, configuration: configuration)
        configure(webView)

        let targetScreen = initialScreen()
        guard let screen = targetScreen else {
            NSApp.terminate(nil)
            return
        }

        let window = CommandCenterWindow(
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
        window.initialFirstResponder = webView
        window.setFrame(screen.frame, display: true)
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(webView)
        window.orderFrontRegardless()
        self.window = window
        monitorScreenConfiguration()

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
            window.makeKey()
            window.makeFirstResponder(webView)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        screenRetry?.cancel()
        if let screenObserver {
            NotificationCenter.default.removeObserver(screenObserver)
        }
        if let eventMonitor {
            NSEvent.removeMonitor(eventMonitor)
        }
        tvWebView?.removeFromSuperview()
    }

    private func showTV(rect: [String: Any]) {
        guard let parent = window,
              let x = rect["x"] as? NSNumber,
              let y = rect["y"] as? NSNumber,
              let width = rect["width"] as? NSNumber,
              let height = rect["height"] as? NSNumber else { return }

        guard let contentView = parent.contentView else { return }
        let scale = parent.screen?.backingScaleFactor ?? 1
        let align = { (value: CGFloat) in round(value * scale) / scale }
        let top = CGFloat(truncating: y)
        let viewHeight = CGFloat(truncating: height)
        let originY = contentView.isFlipped
            ? top
            : contentView.bounds.maxY - top - viewHeight
        let frame = NSRect(
            x: align(CGFloat(truncating: x)),
            y: align(originY),
            width: align(CGFloat(truncating: width)),
            height: align(viewHeight)
        )

        if tvWebView == nil {
            let configuration = WKWebViewConfiguration()
            configuration.mediaTypesRequiringUserActionForPlayback = []
            configuration.preferences.javaScriptCanOpenWindowsAutomatically = true
            configuration.websiteDataStore = .default()
            let webView = WKWebView(frame: .zero, configuration: configuration)
            configure(webView)
            webView.wantsLayer = true
            webView.layer?.backgroundColor = NSColor.black.cgColor
            contentView.addSubview(webView, positioned: .above, relativeTo: nil)
            tvWebView = webView
            webView.load(URLRequest(url: URL(string: "https://app.zapping.com/")!))
        }

        tvWebView?.frame = frame
        tvWebView?.isHidden = false
        parent.makeFirstResponder(tvWebView)
    }

    private func restoreCommandCenterFocus() {
        NSApp.setActivationPolicy(.regular)
        window?.level = .floating
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
        if let window {
            window.makeFirstResponder(window.contentView)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            guard let self else { return }
            NSApp.presentationOptions = [.hideMenuBar, .hideDock]
            self.window?.makeKeyAndOrderFront(nil)
        }
    }

    private func hideTV() {
        tvWebView?.isHidden = true
        restoreCommandCenterFocus()
    }

    private func closeStreamingProcesses() {
        for process in streamingProcesses.values where process.isRunning {
            process.terminate()
        }
    }

    private var hasActiveStreamingProcess: Bool {
        streamingProcesses.values.contains(where: \.isRunning)
    }

    private func bringStreamingToFront(_ process: Process) {
        window?.level = .normal
        NSApp.setActivationPolicy(.accessory)
        let activate: () -> Void = {
            guard let application = NSRunningApplication(
                processIdentifier: process.processIdentifier
            ) else { return }
            application.unhide()
            _ = application.activate(options: [.activateAllWindows])
        }
        activate()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: activate)
    }

    private func launchChromeApp(_ url: URL, provider: String, rect: [String: Any]) {
        guard let screen = window?.screen ?? NSScreen.screens.first(where: {
            $0.localizedName.uppercased().contains("ARZOPA")
        }),
              let x = rect["x"] as? NSNumber,
              let y = rect["y"] as? NSNumber,
              let width = rect["width"] as? NSNumber,
              let height = rect["height"] as? NSNumber else {
            NSWorkspace.shared.open(url)
            return
        }
        let desktopTop = NSScreen.screens.first?.frame.maxY ?? screen.frame.maxY
        let chromeX = Int((screen.frame.minX + CGFloat(truncating: x)).rounded())
        let chromeY = Int(
            (desktopTop - screen.frame.maxY + CGFloat(truncating: y)).rounded()
        )
        let chromeWidth = Int(CGFloat(truncating: width).rounded())
        let chromeHeight = Int(CGFloat(truncating: height).rounded())
        let chromeExecutable = URL(
            fileURLWithPath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        )
        guard FileManager.default.fileExists(atPath: chromeExecutable.path) else {
            NSWorkspace.shared.open(url)
            return
        }
        if let existing = streamingProcesses[provider], existing.isRunning {
            bringStreamingToFront(existing)
            return
        }
        let profileDirectory = streamingProfileRoot
            .appendingPathComponent(provider, isDirectory: true)
        do {
            try FileManager.default.createDirectory(
                at: profileDirectory,
                withIntermediateDirectories: true
            )
        } catch {
            NSWorkspace.shared.open(url)
            return
        }
        let process = Process()
        process.executableURL = chromeExecutable
        process.arguments = [
            "--user-data-dir=\(profileDirectory.path)",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            "--app=\(url.absoluteString)",
            "--window-position=\(chromeX),\(chromeY)",
            "--window-size=\(chromeWidth),\(chromeHeight)",
        ]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            window?.level = .normal
            NSApp.setActivationPolicy(.accessory)
            process.terminationHandler = { [weak self] finished in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.streamingProcesses.removeValue(forKey: provider)
                    self.restoreCommandCenterFocus()
                }
            }
            try process.run()
            streamingProcesses[provider] = process
            bringStreamingToFront(process)
        } catch {
            NSApp.setActivationPolicy(.regular)
            NSWorkspace.shared.open(url)
        }
    }

    private func openStreaming(_ provider: String, rect: [String: Any]) {
        hideTV()
        switch provider {
        case "apple_tv":
            launchChromeApp(URL(string: "https://tv.apple.com/")!, provider: provider, rect: rect)
        case "disney":
            launchChromeApp(URL(string: "https://www.disneyplus.com/")!, provider: provider, rect: rect)
        case "max":
            launchChromeApp(URL(string: "https://www.hbomax.com/")!, provider: provider, rect: rect)
        case "youtube":
            launchChromeApp(URL(string: "https://www.youtube.com/")!, provider: provider, rect: rect)
        default:
            return
        }
    }

    private func sendCalendarPayload(_ payload: [String: Any]) {
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else { return }
        DispatchQueue.main.async { [weak self] in
            (self?.window?.contentView as? WKWebView)?.evaluateJavaScript(
                "window.__nexuxCalendarReceive(\(json));"
            )
        }
    }

    private func calendarMonth(year: Int, month: Int) {
        guard (1...12).contains(month), (2001...2100).contains(year) else { return }
        let deliver: (Bool) -> Void = { [weak self] allowed in
            guard let self else { return }
            DispatchQueue.main.async {
                if !self.hasActiveStreamingProcess {
                    self.window?.level = .floating
                }
                NSApp.presentationOptions = [.hideMenuBar, .hideDock]
            }
            guard allowed else {
                self.sendCalendarPayload([
                    "status": "denied", "year": year, "month": month,
                    "events": [], "message": "Autoriza Calendar en Privacidad",
                ])
                return
            }
            var components = DateComponents()
            components.calendar = Calendar(identifier: .gregorian)
            components.timeZone = .current
            components.year = year
            components.month = month
            components.day = 1
            guard let start = components.date,
                  let end = Calendar.current.date(byAdding: .month, value: 1, to: start) else {
                return
            }
            let events = self.calendarStore.events(
                matching: self.calendarStore.predicateForEvents(
                    withStart: start, end: end, calendars: nil
                )
            ).map { event -> [String: Any] in
                [
                    "id": event.eventIdentifier ?? UUID().uuidString,
                    "title": event.title ?? "Evento",
                    "start_ms": Int(event.startDate.timeIntervalSince1970 * 1000),
                    "end_ms": Int(event.endDate.timeIntervalSince1970 * 1000),
                    "all_day": event.isAllDay,
                ]
            }
            self.sendCalendarPayload([
                "status": "ready", "year": year, "month": month, "events": events,
            ])
        }
        let status = EKEventStore.authorizationStatus(for: .event)
        if status == .notDetermined {
            window?.level = .normal
            NSApp.presentationOptions = []
            NSApp.activate(ignoringOtherApps: true)
            window?.makeKeyAndOrderFront(nil)
        }
        if #available(macOS 14.0, *) {
            if status == .fullAccess {
                deliver(true)
            } else if status == .denied || status == .restricted {
                deliver(false)
            } else {
                calendarStore.requestFullAccessToEvents { granted, _ in deliver(granted) }
            }
        } else {
            if status == .authorized {
                deliver(true)
            } else if status == .denied || status == .restricted {
                deliver(false)
            } else {
                calendarStore.requestAccess(to: .event) { granted, _ in deliver(granted) }
            }
        }
    }

    private func moveCalendarToTCL() {
        let screen = NSScreen.screens.first(where: {
            $0.localizedName.uppercased().contains("TCL")
        }) ?? NSScreen.screens.first(where: {
            !$0.localizedName.uppercased().contains("ARZOPA")
        }) ?? NSScreen.main
        guard let screen else { return }
        let desktopTop = NSScreen.screens.map(\.frame.maxY).max() ?? screen.frame.maxY
        let x = Int(screen.visibleFrame.minX.rounded())
        let y = Int((desktopTop - screen.visibleFrame.maxY).rounded())
        let width = Int(screen.visibleFrame.width.rounded())
        let height = Int(screen.visibleFrame.height.rounded())
        let script = """
        tell application "System Events"
          if exists (first application process whose bundle identifier is "com.apple.iCal") then
            tell (first application process whose bundle identifier is "com.apple.iCal")
              if exists front window then
                set position of front window to {\(x), \(y)}
                set size of front window to {\(width), \(height)}
              end if
            end tell
          end if
        end tell
        """
        DispatchQueue.global(qos: .userInitiated).async {
            NSAppleScript(source: script)?.executeAndReturnError(nil)
        }
    }

    private func openCalendar(timestampMs: Double) {
        let date = Date(timeIntervalSince1970: timestampMs / 1000)
        let components = Calendar.current.dateComponents([.year, .month, .day], from: date)
        guard let year = components.year,
              let month = components.month,
              let day = components.day else { return }
        let script = """
        tell application "Calendar"
          activate
          set targetDate to current date
          set year of targetDate to \(year)
          set month of targetDate to \(month)
          set day of targetDate to \(day)
          set hours of targetDate to 12
          set minutes of targetDate to 0
          set seconds of targetDate to 0
          switch view to month view
          view calendar at targetDate
        end tell
        """
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var error: NSDictionary?
            NSAppleScript(source: script)?.executeAndReturnError(&error)
            if error != nil,
               let applicationURL = NSWorkspace.shared.urlForApplication(
                   withBundleIdentifier: "com.apple.iCal"
               ) {
                NSWorkspace.shared.openApplication(
                    at: applicationURL,
                    configuration: NSWorkspace.OpenConfiguration()
                )
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                self?.moveCalendarToTCL()
            }
        }
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard message.name == "commandCenter",
              let body = message.body as? [String: Any],
              let type = body["type"] as? String else { return }
        if type == "primaryView", let view = body["view"] as? String {
            closeStreamingProcesses()
            if view == "tv", let rect = body["rect"] as? [String: Any] {
                showTV(rect: rect)
            } else {
                hideTV()
            }
        } else if type == "openStreaming",
                  let provider = body["provider"] as? String,
                  let rect = body["rect"] as? [String: Any] {
            openStreaming(provider, rect: rect)
        } else if type == "calendarMonth",
                  let year = body["year"] as? NSNumber,
                  let month = body["month"] as? NSNumber {
            calendarMonth(year: year.intValue, month: month.intValue)
        } else if type == "openCalendar",
                  let timestamp = body["timestampMs"] as? NSNumber {
            openCalendar(timestampMs: timestamp.doubleValue)
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
application.applicationIconImage = NSImage(size: NSSize(width: 1, height: 1))
let mainMenu = NSMenu()
let applicationMenuItem = NSMenuItem()
let applicationMenu = NSMenu()
applicationMenu.addItem(
    withTitle: "Salir de NexUX Command Center",
    action: #selector(NSApplication.terminate(_:)),
    keyEquivalent: "q"
)
applicationMenuItem.submenu = applicationMenu
mainMenu.addItem(applicationMenuItem)
application.mainMenu = mainMenu
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
