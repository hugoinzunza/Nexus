import Foundation
import NexusAgentCore

@main
struct NexusAgentCommand {
    private struct ErrorPayload: Encodable {
        let status: String
        let code: String
        let retryable: Bool
    }

    static func main() {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments == ["--self-check"] {
            let result = [
                "agent": "NexusAgent",
                "protocol": agentProtocolVersion,
                "transport": "outbound-wss-only",
                "factory": "disabled",
            ]
            let data = try? JSONSerialization.data(
                withJSONObject: result,
                options: [.sortedKeys]
            )
            if let data, let text = String(data: data, encoding: .utf8) {
                print(text)
                return
            }
        }
        if arguments.count == 2,
           arguments[0] == "--media-state",
           let provider = DesktopMediaProvider(rawValue: arguments[1]) {
            emitMediaState(provider)
            return
        }
        if arguments.count == 3,
           arguments[0] == "--media-command",
           let provider = DesktopMediaProvider(rawValue: arguments[1]) {
            emitMediaCommand(provider, action: arguments[2])
            return
        }
        FileHandle.standardError.write(
            Data(
                "NexusAgent requires paired configuration; no connection started.\n"
                    .utf8
            )
        )
        exit(64)
    }

    private static func emitMediaState(_ provider: DesktopMediaProvider) {
        do {
            let snapshot = try DesktopMediaAccessibilityBridge().snapshot(
                provider: provider
            )
            emit(snapshot)
        } catch {
            emitError(provider: provider.rawValue, error: error)
        }
    }

    private static func emitMediaCommand(
        _ provider: DesktopMediaProvider,
        action: String
    ) {
        do {
            let result = try DesktopMediaAccessibilityBridge().execute(
                provider: provider,
                action: action
            )
            emit(result)
        } catch {
            emitError(provider: provider.rawValue, error: error)
        }
    }

    private static func emit<T: Encodable>(_ value: T) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard let data = try? encoder.encode(value) else { exit(70) }
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    }

    private static func emitError(provider: String, error: Error) {
        let code: String
        switch error {
        case DesktopMediaBridgeError.permissionDenied:
            code = "\(provider).permission-denied"
        case DesktopMediaBridgeError.appNotRunning:
            code = "\(provider).not-running"
        case DesktopMediaBridgeError.playerUnavailable:
            code = "\(provider).player-unavailable"
        case DesktopMediaBridgeError.actionUnavailable:
            code = "\(provider).action-unavailable"
        default:
            code = "\(provider).command-failed"
        }
        emit(ErrorPayload(status: "rejected", code: code, retryable: true))
    }
}
