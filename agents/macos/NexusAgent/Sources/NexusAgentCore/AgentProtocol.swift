import Foundation

public let agentProtocolVersion = "nexux.agent.v1"
public let agentClockToleranceMs: Int64 = 30_000
public let agentMaximumCommandLifetimeMs: Int64 = 60_000
public let agentMaximumMessageBytes = 65_536

public enum AgentIdentity {
    public static func isCanonicalIdentifier(
        _ value: String,
        maxLength: Int = 128
    ) -> Bool {
        guard !value.isEmpty, value.count <= maxLength else { return false }
        let allowed = CharacterSet(
            charactersIn:
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
        )
        return value.unicodeScalars.allSatisfy(allowed.contains)
            && value.first?.isLetterOrNumber == true
    }

    public static func isOpaqueSecret(_ value: String) -> Bool {
        !value.isEmpty
            && value.utf8.count <= 4_096
            && !value.unicodeScalars.contains(
                where: CharacterSet.whitespacesAndNewlines.contains
            )
    }
}

public enum JSONValue: Codable, Hashable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "unsupported JSON value"
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }
}

public enum AgentCapability: String, Codable, CaseIterable, Sendable {
    case mediaRead = "media.read"
    case mediaControl = "media.control"
    case systemRead = "system.read"
}

public struct AgentCommand: Codable, Hashable, Sendable {
    public let protocolVersion: String
    public let commandId: String
    public let capability: AgentCapability
    public let action: String
    public let issuedAtMs: Int64
    public let deadlineAtMs: Int64
    public let arguments: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case protocolVersion = "v"
        case commandId = "command_id"
        case capability
        case action
        case issuedAtMs = "issued_at_ms"
        case deadlineAtMs = "deadline_at_ms"
        case arguments
    }

    public init(
        protocolVersion: String = agentProtocolVersion,
        commandId: String,
        capability: AgentCapability,
        action: String,
        issuedAtMs: Int64,
        deadlineAtMs: Int64,
        arguments: [String: JSONValue] = [:]
    ) {
        self.protocolVersion = protocolVersion
        self.commandId = commandId
        self.capability = capability
        self.action = action
        self.issuedAtMs = issuedAtMs
        self.deadlineAtMs = deadlineAtMs
        self.arguments = arguments
    }

    public func validationCode(nowMs: Int64) -> String? {
        guard protocolVersion == agentProtocolVersion else {
            return "agent.protocol-unsupported"
        }
        guard AgentIdentity.isCanonicalIdentifier(commandId) else {
            return "agent.command-id-invalid"
        }
        guard AgentIdentity.isCanonicalIdentifier(action, maxLength: 96) else {
            return "agent.action-invalid"
        }
        guard issuedAtMs >= 0, deadlineAtMs >= issuedAtMs else {
            return "agent.time-invalid"
        }
        guard issuedAtMs <= nowMs + agentClockToleranceMs,
              deadlineAtMs - issuedAtMs <= agentMaximumCommandLifetimeMs else {
            return "agent.time-invalid"
        }
        guard nowMs <= deadlineAtMs else {
            return "agent.command-expired"
        }
        return nil
    }

    public func fingerprint() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(self)
    }

}

extension Character {
    var isLetterOrNumber: Bool {
        unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0)
        }
    }
}

public enum AgentAckStatus: String, Codable, Sendable {
    case applied
    case rejected
    case unknown
}

public struct AgentAck: Codable, Equatable, Sendable {
    public let protocolVersion: String
    public let commandId: String
    public let capability: AgentCapability
    public let action: String
    public let status: AgentAckStatus
    public let completedAtMs: Int64
    public let code: String
    public let retryable: Bool

    enum CodingKeys: String, CodingKey {
        case protocolVersion = "v"
        case commandId = "command_id"
        case capability
        case action
        case status
        case completedAtMs = "completed_at_ms"
        case code
        case retryable
    }
}

public struct AgentHandlerResult: Equatable, Sendable {
    public let status: AgentAckStatus
    public let code: String
    public let retryable: Bool

    public init(
        _ status: AgentAckStatus,
        code: String,
        retryable: Bool = false
    ) {
        self.status = status
        self.code = code
        self.retryable = retryable
    }
}

public protocol AgentCapabilityHandler: Sendable {
    var capability: AgentCapability { get }
    var allowedActions: Set<String> { get }
    func execute(_ command: AgentCommand) async -> AgentHandlerResult
}
