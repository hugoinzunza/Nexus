import AppKit
import ApplicationServices
import CoreGraphics
import CryptoKit
import Foundation

public enum DesktopMediaProvider: String, Codable, Sendable {
    case qobuz
    case tidal

    var bundleIdentifier: String {
        switch self {
        case .qobuz: "com.qobuz.desktop"
        case .tidal: "com.tidal.desktop"
        }
    }
}

public struct DesktopMediaSnapshot: Codable, Equatable, Sendable {
    public let provider: String
    public let running: Bool
    public let playback: String
    public let track: String?
    public let artist: String?
    public let album: String?
    public let itemRef: String?
    public let progress: Double?
    public let code: String

    enum CodingKeys: String, CodingKey {
        case provider, running, playback, track, artist, album, progress, code
        case itemRef = "item_ref"
    }
}

public struct DesktopMediaCommandResult: Codable, Equatable, Sendable {
    public let provider: String
    public let action: String
    public let status: String
    public let code: String
    public let retryable: Bool
}

public enum DesktopMediaBridgeError: Error {
    case permissionDenied
    case appNotRunning
    case playerUnavailable
    case actionUnavailable
    case commandFailed
}

private struct AccessibleNode {
    let element: AXUIElement
    let role: String
    let label: String
    let value: String
    let numericValue: Double?
    let minimumValue: Double?
    let maximumValue: Double?
    let frame: CGRect?
}

public struct DesktopMediaAccessibilityBridge {
    private static let maximumNodes = 4_000

    public init() {}

    public func snapshot(
        provider: DesktopMediaProvider
    ) throws -> DesktopMediaSnapshot {
        guard let app = runningApplication(provider) else {
            return DesktopMediaSnapshot(
                provider: provider.rawValue,
                running: false,
                playback: "stopped",
                track: nil,
                artist: nil,
                album: nil,
                itemRef: nil,
                progress: nil,
                code: "\(provider.rawValue).not-running"
            )
        }
        guard AXIsProcessTrusted() else {
            throw DesktopMediaBridgeError.permissionDenied
        }
        let player = try accessiblePlayerNodes(for: app, provider: provider)
        let metadata = metadata(for: provider, nodes: player)
        let playback = provider == .qobuz
            ? try qobuzPlayback(initialNodes: player, app: app)
            : playback(for: provider, nodes: player)
        let itemRef = makeItemRef(
            provider: provider,
            track: metadata.track,
            artist: metadata.artist,
            album: metadata.album
        )
        return DesktopMediaSnapshot(
            provider: provider.rawValue,
            running: true,
            playback: playback,
            track: metadata.track,
            artist: metadata.artist,
            album: metadata.album,
            itemRef: itemRef,
            progress: progressFraction(player),
            code: metadata.track == nil
                ? "\(provider.rawValue).player-empty"
                : "\(provider.rawValue).accessible"
        )
    }

    public func execute(
        provider: DesktopMediaProvider,
        action: String,
        knownPlayback: String? = nil
    ) throws -> DesktopMediaCommandResult {
        guard let app = runningApplication(provider) else {
            throw DesktopMediaBridgeError.appNotRunning
        }
        guard AXIsProcessTrusted() else {
            throw DesktopMediaBridgeError.permissionDenied
        }
        let player = try accessiblePlayerNodes(
            for: app,
            provider: provider,
            collapseExpandedQobuz: provider == .qobuz
        )
        switch provider {
        case .tidal:
            try executeTidal(action: action, nodes: player)
        case .qobuz:
            try executeQobuz(
                action: action,
                app: app,
                nodes: player,
                knownPlayback: knownPlayback
            )
        }
        if action == "play" || action == "pause" {
            let expected = action == "play" ? "playing" : "paused"
            var observed = try verifiedPlayback(provider: provider)
            if observed != expected, provider == .qobuz {
                let refreshed = try accessiblePlayerNodes(
                    for: app,
                    provider: provider
                )
                try executeQobuz(
                    action: action,
                    app: app,
                    nodes: refreshed,
                    knownPlayback: observed
                )
                observed = try verifiedPlayback(provider: provider)
            }
            guard observed == expected else {
                throw DesktopMediaBridgeError.commandFailed
            }
        }
        return DesktopMediaCommandResult(
            provider: provider.rawValue,
            action: action,
            status: "applied",
            code: "\(provider.rawValue).applied",
            retryable: false
        )
    }

    private func verifiedPlayback(
        provider: DesktopMediaProvider
    ) throws -> String {
        Thread.sleep(forTimeInterval: 0.22)
        return try snapshot(provider: provider).playback
    }

    private func runningApplication(
        _ provider: DesktopMediaProvider
    ) -> NSRunningApplication? {
        NSRunningApplication.runningApplications(
            withBundleIdentifier: provider.bundleIdentifier
        ).first
    }

    private func accessiblePlayerNodes(
        for app: NSRunningApplication,
        provider: DesktopMediaProvider,
        collapseExpandedQobuz: Bool = false
    ) throws -> [AccessibleNode] {
        let root = accessibilityRoot(for: app)
        AXUIElementSetAttributeValue(
            root,
            "AXManualAccessibility" as CFString,
            kCFBooleanTrue
        )
        AXUIElementSetAttributeValue(
            root,
            "AXEnhancedUserInterface" as CFString,
            kCFBooleanTrue
        )
        for _ in 0..<3 {
            Thread.sleep(forTimeInterval: 0.18)
            let refreshed = accessibilityRoot(for: app)
            if let nodes = findPlayerNodes(
                root: refreshed,
                provider: provider
            ) {
                return nodes
            }
        }
        if provider == .qobuz,
           collapseExpandedQobuz,
           collapseExpandedQobuzPlayer(root: accessibilityRoot(for: app)) {
            Thread.sleep(forTimeInterval: 0.25)
            if let nodes = findPlayerNodes(
                root: accessibilityRoot(for: app),
                provider: provider
            ) {
                return nodes
            }
        }
        throw DesktopMediaBridgeError.playerUnavailable
    }

    private func collapseExpandedQobuzPlayer(root: AXUIElement) -> Bool {
        var queue = [root]
        var index = 0
        while index < queue.count && index < Self.maximumNodes {
            let element = queue[index]
            index += 1
            let role = stringAttribute(element, kAXRoleAttribute)
            let label = firstNonEmpty(
                stringAttribute(element, kAXDescriptionAttribute),
                stringAttribute(element, kAXTitleAttribute),
                stringAttribute(element, kAXHelpAttribute)
            )
            if role == kAXButtonRole as String,
               normalize(label).contains("cerrar el player en modo pantalla completa") {
                return AXUIElementPerformAction(
                    element,
                    kAXPressAction as CFString
                ) == .success
            }
            queue.append(contentsOf: children(element))
        }
        return false
    }

    private func findPlayerNodes(
        root: AXUIElement,
        provider: DesktopMediaProvider
    ) -> [AccessibleNode]? {
        var queue = [root]
        var index = 0
        while index < queue.count && index < Self.maximumNodes {
            let element = queue[index]
            index += 1
            let role = stringAttribute(element, kAXRoleAttribute)
            let label = firstNonEmpty(
                stringAttribute(element, kAXDescriptionAttribute),
                stringAttribute(element, kAXTitleAttribute),
                stringAttribute(element, kAXHelpAttribute)
            )
            let value = stringValue(element, kAXValueAttribute)
            let node = AccessibleNode(
                element: element,
                role: role,
                label: label,
                value: value,
                numericValue: numberAttribute(element, kAXValueAttribute),
                minimumValue: numberAttribute(element, kAXMinValueAttribute),
                maximumValue: numberAttribute(element, kAXMaxValueAttribute),
                frame: frame(element)
            )
            let normalized = normalize(label)
            let isAnchor: Bool
            switch provider {
            case .qobuz:
                isAnchor = normalized == "mute"
                    || role == kAXSliderRole as String
                    || role == kAXProgressIndicatorRole as String
                    || (role == kAXButtonRole as String
                        && ["reproducir", "pausar", "pausa"].contains(normalized))
            case .tidal:
                isAnchor = role == kAXSliderRole as String
                    && normalized == "progress bar"
            }
            if isAnchor, let player = playerRoot(from: node.element) {
                let scoped = descendants(player, limit: 600)
                if scoped.count > 3 { return scoped }
            }
            queue.append(contentsOf: children(element))
        }
        return nil
    }

    private func accessibilityRoot(
        for app: NSRunningApplication
    ) -> AXUIElement {
        AXUIElementCreateApplication(app.processIdentifier)
    }

    private func playerRoot(from anchor: AXUIElement) -> AXUIElement? {
        var current: AXUIElement? = anchor
        var candidate: AXUIElement?
        var structuralCandidate: AXUIElement?
        for _ in 0..<14 {
            guard let element = current else { break }
            if let bounds = frame(element),
               bounds.width >= 400,
               bounds.height >= 40,
               bounds.height <= 240 {
                candidate = element
            }
            if structuralCandidate == nil {
                let scoped = descendants(element, limit: 121)
                let hasProgress = scoped.contains {
                    $0.role == kAXSliderRole as String
                        || $0.role == kAXProgressIndicatorRole as String
                }
                let metadataLinks = scoped.filter {
                    $0.role == "AXLink" && isMetadata($0.label)
                }.count
                let hasPlaybackControl = scoped.contains {
                    guard $0.role == kAXButtonRole as String else {
                        return false
                    }
                    return ["reproducir", "pausar", "pausa", "mute"]
                        .contains(normalize($0.label))
                }
                if scoped.count > 3,
                   scoped.count < 121,
                   hasProgress,
                   metadataLinks >= 2,
                   hasPlaybackControl {
                    structuralCandidate = element
                }
            }
            current = elementAttribute(element, kAXParentAttribute)
        }
        return candidate ?? structuralCandidate
    }

    private func descendants(
        _ root: AXUIElement,
        limit: Int
    ) -> [AccessibleNode] {
        var queue = [root]
        var result: [AccessibleNode] = []
        var index = 0
        while index < queue.count && result.count < limit {
            let element = queue[index]
            index += 1
            result.append(
                AccessibleNode(
                    element: element,
                    role: stringAttribute(element, kAXRoleAttribute),
                    label: firstNonEmpty(
                        stringAttribute(element, kAXDescriptionAttribute),
                        stringAttribute(element, kAXTitleAttribute),
                        stringAttribute(element, kAXHelpAttribute)
                    ),
                    value: stringValue(element, kAXValueAttribute),
                    numericValue: numberAttribute(element, kAXValueAttribute),
                    minimumValue: numberAttribute(element, kAXMinValueAttribute),
                    maximumValue: numberAttribute(element, kAXMaxValueAttribute),
                    frame: frame(element)
                )
            )
            queue.append(contentsOf: children(element))
        }
        return result
    }

    private func metadata(
        for provider: DesktopMediaProvider,
        nodes: [AccessibleNode]
    ) -> (track: String?, artist: String?, album: String?) {
        let links = nodes
            .filter { $0.role == "AXLink" }
            .filter { isMetadata($0.label) }
            .sorted {
                let left = $0.frame ?? .zero
                let right = $1.frame ?? .zero
                if abs(left.midY - right.midY) > 3 {
                    return left.midY < right.midY
                }
                return left.minX < right.minX
            }
            .map(\.label)
        switch provider {
        case .qobuz:
            return (
                links.first,
                links.count > 1 ? links[1] : nil,
                links.count > 2 ? links[2] : nil
            )
        case .tidal:
            return (
                links.first,
                links.count > 1 ? links[1] : nil,
                links.count > 2 ? links[2] : nil
            )
        }
    }

    private func playback(
        for provider: DesktopMediaProvider,
        nodes: [AccessibleNode]
    ) -> String {
        let labels = nodes.map { normalize($0.label) }
        if labels.contains("pausar") || labels.contains("pausa") {
            return "playing"
        }
        if labels.contains("reproducir") { return "paused" }
        if provider == .qobuz,
           nodes.contains(where: {
               $0.role == kAXProgressIndicatorRole as String
                   || $0.role == kAXSliderRole as String
           }) {
            return "unknown"
        }
        return "stopped"
    }

    private func qobuzPlayback(
        initialNodes: [AccessibleNode],
        app: NSRunningApplication
    ) throws -> String {
        guard let first = progressValue(initialNodes) else {
            return playback(for: .qobuz, nodes: initialNodes)
        }
        // Qobuz actualiza el progreso aproximadamente una vez por segundo.
        Thread.sleep(forTimeInterval: 1.10)
        let secondNodes = try accessiblePlayerNodes(for: app, provider: .qobuz)
        guard let second = progressValue(secondNodes) else { return "unknown" }
        return abs(second - first) > 0.001 ? "playing" : "paused"
    }

    private func progressValue(_ nodes: [AccessibleNode]) -> Double? {
        nodes.first(where: {
            $0.role == kAXSliderRole as String
                || $0.role == kAXProgressIndicatorRole as String
        }).flatMap { $0.numericValue ?? Double($0.value) }
    }

    private func progressFraction(_ nodes: [AccessibleNode]) -> Double? {
        guard let node = nodes.first(where: {
            $0.role == kAXSliderRole as String
                || $0.role == kAXProgressIndicatorRole as String
        }), let value = node.numericValue ?? Double(node.value) else {
            return nil
        }
        if let minimum = node.minimumValue,
           let maximum = node.maximumValue,
           maximum > minimum {
            return min(1, max(0, (value - minimum) / (maximum - minimum)))
        }
        return (0...1).contains(value) ? value : nil
    }

    private func executeTidal(
        action: String,
        nodes: [AccessibleNode]
    ) throws {
        let target: String
        switch action {
        case "play":
            if nodes.contains(where: { normalize($0.label) == "pausar" }) {
                return
            }
            target = "reproducir"
        case "pause":
            if nodes.contains(where: { normalize($0.label) == "reproducir" }) {
                return
            }
            target = "pausar"
        case "next": target = "siguiente"
        case "previous": target = "anterior"
        default: throw DesktopMediaBridgeError.actionUnavailable
        }
        guard let button = nodes.first(where: {
            $0.role == kAXButtonRole as String
                && normalize($0.label) == target
        }) else {
            throw DesktopMediaBridgeError.actionUnavailable
        }
        guard AXUIElementPerformAction(
            button.element,
            kAXPressAction as CFString
        ) == .success else {
            throw DesktopMediaBridgeError.commandFailed
        }
    }

    private func executeQobuz(
        action: String,
        app: NSRunningApplication,
        nodes: [AccessibleNode],
        knownPlayback: String?
    ) throws {
        let current: String
        if let knownPlayback,
           knownPlayback == "playing" || knownPlayback == "paused" {
            current = knownPlayback
        } else {
            current = try qobuzPlayback(initialNodes: nodes, app: app)
        }
        let pid = app.processIdentifier
        switch action {
        case "play" where current == "playing": return
        case "pause" where current == "paused": return
        case "play", "pause":
            let expectedLabels = action == "play"
                ? ["reproducir"]
                : ["pausar", "pausa"]
            let button = nodes.first(where: {
                $0.role == kAXButtonRole as String
                    && expectedLabels.contains(normalize($0.label))
            }) ?? nodes.first(where: {
                guard $0.role == kAXButtonRole as String,
                      $0.label.isEmpty,
                      let frame = $0.frame else { return false }
                return frame.width >= 56 && frame.height >= 56
                    && abs(frame.width - frame.height) <= 8
            }) ?? qobuzGlobalPlaybackButton(
                app: app,
                labels: expectedLabels
            )
            guard let button else {
                throw DesktopMediaBridgeError.actionUnavailable
            }
            guard AXUIElementPerformAction(
                button.element,
                kAXPressAction as CFString
            ) == .success else {
                throw DesktopMediaBridgeError.commandFailed
            }
        case "next":
            try postKey(code: 124, flags: .maskCommand, pid: pid)
        case "previous":
            try postKey(code: 123, flags: .maskCommand, pid: pid)
        default:
            throw DesktopMediaBridgeError.actionUnavailable
        }
    }

    private func qobuzGlobalPlaybackButton(
        app: NSRunningApplication,
        labels: [String]
    ) -> AccessibleNode? {
        let candidates = descendants(
            accessibilityRoot(for: app),
            limit: Self.maximumNodes
        ).filter {
            $0.role == kAXButtonRole as String
                && labels.contains(normalize($0.label))
        }
        return candidates.max {
            let leftY = $0.frame?.midY ?? -.greatestFiniteMagnitude
            let rightY = $1.frame?.midY ?? -.greatestFiniteMagnitude
            return leftY < rightY
        } ?? candidates.last
    }

    private func postKey(
        code: CGKeyCode,
        flags: CGEventFlags,
        pid: pid_t
    ) throws {
        guard let down = CGEvent(
            keyboardEventSource: nil,
            virtualKey: code,
            keyDown: true
        ), let up = CGEvent(
            keyboardEventSource: nil,
            virtualKey: code,
            keyDown: false
        ) else {
            throw DesktopMediaBridgeError.commandFailed
        }
        down.flags = flags
        up.flags = flags
        down.postToPid(pid)
        up.postToPid(pid)
    }

    private func children(_ element: AXUIElement) -> [AXUIElement] {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            kAXChildrenAttribute as CFString,
            &value
        ) == .success else { return [] }
        return value as? [AXUIElement] ?? []
    }

    private func elementAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> AXUIElement? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            attribute as CFString,
            &value
        ) == .success else { return nil }
        return value as! AXUIElement?
    }

    private func stringAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> String {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            attribute as CFString,
            &value
        ) == .success else { return "" }
        return (value as? String)?.trimmingCharacters(
            in: .whitespacesAndNewlines
        ) ?? ""
    }

    private func stringValue(
        _ element: AXUIElement,
        _ attribute: String
    ) -> String {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            attribute as CFString,
            &value
        ) == .success, let value else { return "" }
        if let text = value as? String { return text }
        if let number = value as? NSNumber { return number.stringValue }
        return ""
    }

    private func numberAttribute(
        _ element: AXUIElement,
        _ attribute: String
    ) -> Double? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            attribute as CFString,
            &value
        ) == .success, let number = value as? NSNumber else { return nil }
        return number.doubleValue
    }

    private func frame(_ element: AXUIElement) -> CGRect? {
        var positionValue: CFTypeRef?
        var sizeValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            element,
            kAXPositionAttribute as CFString,
            &positionValue
        ) == .success,
        AXUIElementCopyAttributeValue(
            element,
            kAXSizeAttribute as CFString,
            &sizeValue
        ) == .success,
        let positionValue, let sizeValue,
        CFGetTypeID(positionValue) == AXValueGetTypeID(),
        CFGetTypeID(sizeValue) == AXValueGetTypeID() else { return nil }
        var point = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(
            positionValue as! AXValue,
            .cgPoint,
            &point
        ), AXValueGetValue(
            sizeValue as! AXValue,
            .cgSize,
            &size
        ) else { return nil }
        return CGRect(origin: point, size: size)
    }

    private func firstNonEmpty(_ values: String...) -> String {
        values.first(where: { !$0.isEmpty }) ?? ""
    }

    private func normalize(_ value: String) -> String {
        value.folding(
            options: [.diacriticInsensitive, .caseInsensitive],
            locale: Locale(identifier: "es")
        ).trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private func isMetadata(_ value: String) -> Bool {
        let normalized = normalize(value)
        return !normalized.isEmpty
            && !normalized.contains("ver todo")
            && !normalized.contains("ajustes")
            && !normalized.contains("salida de sonido")
    }

    private func makeItemRef(
        provider: DesktopMediaProvider,
        track: String?,
        artist: String?,
        album: String?
    ) -> String? {
        guard let track, !track.isEmpty else { return nil }
        let source = [provider.rawValue, track, artist ?? "", album ?? ""]
            .joined(separator: "\u{1f}")
        let digest = SHA256.hash(data: Data(source.utf8))
        return "\(provider.rawValue):" + digest.map {
            String(format: "%02x", $0)
        }.joined().prefix(24)
    }
}
