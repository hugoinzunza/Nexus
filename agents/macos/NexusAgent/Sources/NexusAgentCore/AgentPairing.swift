import Foundation

public let agentPairingProtocolVersion = "nexux.agent-pairing.v1"
public let agentPairingLifetimeMs: Int64 = 60_000

public enum AgentPairingStatus: String, Codable, Sendable {
    case accepted
    case rejected
}

public struct AgentPairingRequest:
    Codable,
    Equatable,
    Sendable,
    CustomStringConvertible,
    CustomDebugStringConvertible
{
    public let protocolVersion: String
    public let requestId: String
    public let deviceId: String
    public let pairingCode: String
    public let nonce: String
    public let capabilities: [AgentCapability]
    public let issuedAtMs: Int64
    public let deadlineAtMs: Int64

    enum CodingKeys: String, CodingKey {
        case protocolVersion = "v"
        case requestId = "request_id"
        case deviceId = "device_id"
        case pairingCode = "pairing_code"
        case nonce
        case capabilities
        case issuedAtMs = "issued_at_ms"
        case deadlineAtMs = "deadline_at_ms"
    }

    public init(
        protocolVersion: String = agentPairingProtocolVersion,
        requestId: String,
        deviceId: String,
        pairingCode: String,
        nonce: String,
        capabilities: [AgentCapability],
        issuedAtMs: Int64,
        deadlineAtMs: Int64
    ) {
        self.protocolVersion = protocolVersion
        self.requestId = requestId
        self.deviceId = deviceId
        self.pairingCode = pairingCode
        self.nonce = nonce
        self.capabilities = capabilities
        self.issuedAtMs = issuedAtMs
        self.deadlineAtMs = deadlineAtMs
    }

    public func validationCode(nowMs: Int64) -> String? {
        guard protocolVersion == agentPairingProtocolVersion else {
            return "pairing.protocol-unsupported"
        }
        guard AgentIdentity.isCanonicalIdentifier(requestId),
              AgentIdentity.isCanonicalIdentifier(deviceId),
              AgentIdentity.isCanonicalIdentifier(nonce) else {
            return "pairing.identity-invalid"
        }
        guard Self.isCanonicalPairingCode(pairingCode) else {
            return "pairing.code-invalid"
        }
        guard !capabilities.isEmpty,
              capabilities.count <= AgentCapability.allCases.count,
              Set(capabilities).count == capabilities.count,
              capabilities == capabilities.sorted(
                  by: { $0.rawValue < $1.rawValue }
              ) else {
            return "pairing.capabilities-invalid"
        }
        guard issuedAtMs >= 0,
              deadlineAtMs >= issuedAtMs,
              issuedAtMs <= nowMs + agentClockToleranceMs,
              deadlineAtMs - issuedAtMs <= agentPairingLifetimeMs else {
            return "pairing.time-invalid"
        }
        guard nowMs <= deadlineAtMs else {
            return "pairing.expired"
        }
        return nil
    }

    public static func isCanonicalPairingCode(_ value: String) -> Bool {
        guard (6...32).contains(value.count) else { return false }
        let allowed = CharacterSet(
            charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        )
        return value.unicodeScalars.allSatisfy(allowed.contains)
            && value.first?.isLetterOrNumber == true
            && value.last?.isLetterOrNumber == true
    }

    public var description: String {
        "AgentPairingRequest(requestId: \(requestId), "
            + "deviceId: \(deviceId), pairingCode: <redacted>, "
            + "nonce: \(nonce), capabilities: \(capabilities.count))"
    }

    public var debugDescription: String { description }
}

public struct AgentPairingResponse:
    Codable,
    Equatable,
    Sendable,
    CustomStringConvertible,
    CustomDebugStringConvertible
{
    public let protocolVersion: String
    public let requestId: String
    public let deviceId: String
    public let nonce: String
    public let status: AgentPairingStatus
    public let code: String
    public let deviceToken: String?
    public let tokenExpiresAtMs: Int64?

    enum CodingKeys: String, CodingKey {
        case protocolVersion = "v"
        case requestId = "request_id"
        case deviceId = "device_id"
        case nonce
        case status
        case code
        case deviceToken = "device_token"
        case tokenExpiresAtMs = "token_expires_at_ms"
    }

    public init(
        protocolVersion: String = agentPairingProtocolVersion,
        requestId: String,
        deviceId: String,
        nonce: String,
        status: AgentPairingStatus,
        code: String,
        deviceToken: String? = nil,
        tokenExpiresAtMs: Int64? = nil
    ) {
        self.protocolVersion = protocolVersion
        self.requestId = requestId
        self.deviceId = deviceId
        self.nonce = nonce
        self.status = status
        self.code = code
        self.deviceToken = deviceToken
        self.tokenExpiresAtMs = tokenExpiresAtMs
    }

    public func credential(
        matching request: AgentPairingRequest,
        nowMs: Int64
    ) throws -> DeviceCredential {
        if request.validationCode(nowMs: nowMs) == "pairing.expired" {
            throw AgentPairingError.timeout
        }
        guard request.validationCode(nowMs: nowMs) == nil else {
            throw AgentPairingError.invalidResponse
        }
        guard protocolVersion == agentPairingProtocolVersion else {
            throw AgentPairingError.protocolMismatch
        }
        guard requestId == request.requestId,
              deviceId == request.deviceId,
              nonce == request.nonce else {
            throw AgentPairingError.responseMismatch
        }
        guard status == .accepted else {
            throw AgentPairingError.rejected
        }
        guard code == "pairing.accepted",
              let deviceToken,
              let tokenExpiresAtMs else {
            throw AgentPairingError.invalidResponse
        }
        let credential = DeviceCredential(
            deviceId: deviceId,
            token: deviceToken,
            expiresAtMs: tokenExpiresAtMs
        )
        guard credential.validationCode(nowMs: nowMs) == nil else {
            throw AgentPairingError.invalidCredential
        }
        return credential
    }

    public var description: String {
        "AgentPairingResponse(requestId: \(requestId), "
            + "deviceId: \(deviceId), status: \(status.rawValue), "
            + "deviceToken: <redacted>)"
    }

    public var debugDescription: String { description }
}

public protocol AgentPairingGateway: Sendable {
    func pair(_ request: AgentPairingRequest) async throws
        -> AgentPairingResponse
}

public enum AgentPairingError: Error, Equatable {
    case invalidRequest(String)
    case alreadyInProgress
    case timeout
    case protocolMismatch
    case responseMismatch
    case rejected
    case gatewayUnavailable
    case invalidResponse
    case invalidCredential
    case credentialStore
}

public struct AgentPairingStats: Equatable, Sendable {
    public let attempts: Int
    public let accepted: Int
    public let rejected: Int
    public let failures: Int
    public let inProgress: Bool
}

public actor AgentPairingCoordinator {
    public typealias IdentifierFactory = @Sendable () -> String

    private let gateway: any AgentPairingGateway
    private let store: any DeviceCredentialStore
    private let clockMs: @Sendable () -> Int64
    private let identifierFactory: IdentifierFactory
    private let pairingLifetimeMs: Int64
    private var attempts = 0
    private var accepted = 0
    private var rejected = 0
    private var failures = 0
    private var inProgress = false

    public init(
        gateway: any AgentPairingGateway,
        store: any DeviceCredentialStore,
        clockMs: @escaping @Sendable () -> Int64 = {
            Int64(Date().timeIntervalSince1970 * 1_000)
        },
        pairingLifetimeMs: Int64 = agentPairingLifetimeMs,
        identifierFactory: @escaping IdentifierFactory = {
            UUID().uuidString.lowercased()
        }
    ) {
        precondition(pairingLifetimeMs > 0)
        precondition(pairingLifetimeMs <= agentPairingLifetimeMs)
        self.gateway = gateway
        self.store = store
        self.clockMs = clockMs
        self.pairingLifetimeMs = pairingLifetimeMs
        self.identifierFactory = identifierFactory
    }

    public func pair(
        deviceId: String,
        pairingCode: String,
        capabilities: Set<AgentCapability>
    ) async throws -> DeviceCredential {
        guard !inProgress else {
            throw AgentPairingError.alreadyInProgress
        }
        inProgress = true
        attempts += 1
        defer { inProgress = false }

        let now = clockMs()
        let request = AgentPairingRequest(
            requestId: identifierFactory(),
            deviceId: deviceId,
            pairingCode: pairingCode,
            nonce: identifierFactory(),
            capabilities: capabilities.sorted {
                $0.rawValue < $1.rawValue
            },
            issuedAtMs: now,
            deadlineAtMs: now + pairingLifetimeMs
        )
        if let code = request.validationCode(nowMs: now) {
            failures += 1
            throw AgentPairingError.invalidRequest(code)
        }

        let response: AgentPairingResponse
        do {
            response = try await exchange(request)
        } catch is CancellationError {
            failures += 1
            throw AgentPairingError.timeout
        } catch AgentPairingError.timeout {
            failures += 1
            throw AgentPairingError.timeout
        } catch {
            failures += 1
            throw AgentPairingError.gatewayUnavailable
        }

        do {
            let credential = try response.credential(
                matching: request,
                nowMs: clockMs()
            )
            do {
                try store.save(credential)
            } catch {
                throw AgentPairingError.credentialStore
            }
            accepted += 1
            return credential
        } catch AgentPairingError.rejected {
            rejected += 1
            throw AgentPairingError.rejected
        } catch {
            failures += 1
            throw error
        }
    }

    public func credential(deviceId: String) throws -> DeviceCredential? {
        do {
            guard let credential = try store.load(deviceId: deviceId) else {
                return nil
            }
            guard credential.validationCode(nowMs: clockMs()) == nil else {
                try? store.delete(deviceId: deviceId)
                return nil
            }
            return credential
        } catch {
            throw AgentPairingError.credentialStore
        }
    }

    public func revoke(deviceId: String) throws {
        do {
            try store.delete(deviceId: deviceId)
        } catch {
            throw AgentPairingError.credentialStore
        }
    }

    public func stats() -> AgentPairingStats {
        AgentPairingStats(
            attempts: attempts,
            accepted: accepted,
            rejected: rejected,
            failures: failures,
            inProgress: inProgress
        )
    }

    private func exchange(
        _ request: AgentPairingRequest
    ) async throws -> AgentPairingResponse {
        let gateway = gateway
        let timeoutNs = UInt64(pairingLifetimeMs) * 1_000_000
        return try await withThrowingTaskGroup(
            of: AgentPairingResponse.self
        ) { group in
            group.addTask {
                try await gateway.pair(request)
            }
            group.addTask {
                try await Task.sleep(nanoseconds: timeoutNs)
                throw AgentPairingError.timeout
            }
            guard let first = try await group.next() else {
                throw AgentPairingError.gatewayUnavailable
            }
            group.cancelAll()
            return first
        }
    }
}
