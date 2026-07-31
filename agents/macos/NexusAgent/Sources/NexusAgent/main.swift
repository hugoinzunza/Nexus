import Foundation
import NexusAgentCore

@main
struct NexusAgentCommand {
    static func main() {
        if Array(CommandLine.arguments.dropFirst()) == ["--self-check"] {
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
        FileHandle.standardError.write(
            Data(
                "NexusAgent requires paired configuration; no connection started.\n"
                    .utf8
            )
        )
        exit(64)
    }
}
