import Foundation
import NexusAgentCore

private let now: Int64 = 1_785_430_000_000
private let validCredential = DeviceCredential(
    deviceId: "device-test-1",
    token: "opaque-device-token",
    expiresAtMs: now + 60_000
)

private enum HarnessError: Error {
    case disconnected
    case credentialStore
}

private actor RecordingHandler: AgentCapabilityHandler {
    nonisolated let capability: AgentCapability
    nonisolated let allowedActions: Set<String>
    private var effects = 0
    private let delayNs: UInt64
    private var nextResult = AgentHandlerResult(
        .applied,
        code: "test.applied"
    )

    init(
        capability: AgentCapability = .mediaControl,
        actions: Set<String> = ["pause", "set_volume"],
        delayNs: UInt64 = 0
    ) {
        self.capability = capability
        self.allowedActions = actions
        self.delayNs = delayNs
    }

    func setNext(_ result: AgentHandlerResult) {
        nextResult = result
    }

    func execute(_ command: AgentCommand) async -> AgentHandlerResult {
        if delayNs > 0 {
            try? await Task.sleep(nanoseconds: delayNs)
        }
        effects += 1
        return nextResult
    }

    func effectCount() -> Int { effects }
}

private actor StubTransport: AgentTransport {
    private let incoming: Data
    private var delivered = false
    private var sentPayloads: [Data] = []
    private var connections = 0

    init(incoming: Data) {
        self.incoming = incoming
    }

    func connect() async throws {
        connections += 1
        if connections > 1 {
            throw HarnessError.disconnected
        }
    }

    func send(_ data: Data) async throws {
        sentPayloads.append(data)
    }

    func receive() async throws -> Data {
        guard !delivered else { throw HarnessError.disconnected }
        delivered = true
        return incoming
    }

    func close() async {}

    func sent() -> [Data] { sentPayloads }
}

private final class MemoryCredentialStore:
    DeviceCredentialStore,
    @unchecked Sendable
{
    private let lock = NSLock()
    private let failSave: Bool
    private var credentials: [String: DeviceCredential] = [:]

    init(failSave: Bool = false) {
        self.failSave = failSave
    }

    func load(deviceId: String) throws -> DeviceCredential? {
        lock.lock()
        defer { lock.unlock() }
        return credentials[deviceId]
    }

    func save(_ credential: DeviceCredential) throws {
        if failSave { throw HarnessError.credentialStore }
        lock.lock()
        defer { lock.unlock() }
        credentials[credential.deviceId] = credential
    }

    func delete(deviceId: String) throws {
        lock.lock()
        defer { lock.unlock() }
        credentials.removeValue(forKey: deviceId)
    }
}

private enum FakePairingMode: Sendable {
    case accepted
    case rejected
    case mismatched
    case expiredCredential
}

private actor FakePairingGateway: AgentPairingGateway {
    private let mode: FakePairingMode
    private let nowMs: Int64
    private let delayNs: UInt64
    private var usedCodes: Set<String> = []
    private var calls = 0

    init(
        mode: FakePairingMode = .accepted,
        nowMs: Int64 = now,
        delayNs: UInt64 = 0
    ) {
        self.mode = mode
        self.nowMs = nowMs
        self.delayNs = delayNs
    }

    func pair(
        _ request: AgentPairingRequest
    ) async throws -> AgentPairingResponse {
        calls += 1
        if delayNs > 0 {
            try await Task.sleep(nanoseconds: delayNs)
        }
        if usedCodes.contains(request.pairingCode) {
            return response(
                request,
                status: .rejected,
                code: "pairing.code-consumed"
            )
        }
        usedCodes.insert(request.pairingCode)
        switch mode {
        case .accepted:
            return response(
                request,
                status: .accepted,
                code: "pairing.accepted",
                token: "issued-device-token",
                expiresAtMs: nowMs + 86_400_000
            )
        case .rejected:
            return response(
                request,
                status: .rejected,
                code: "pairing.rejected"
            )
        case .mismatched:
            return AgentPairingResponse(
                requestId: request.requestId,
                deviceId: "other-device",
                nonce: request.nonce,
                status: .accepted,
                code: "pairing.accepted",
                deviceToken: "issued-device-token",
                tokenExpiresAtMs: nowMs + 86_400_000
            )
        case .expiredCredential:
            return response(
                request,
                status: .accepted,
                code: "pairing.accepted",
                token: "issued-device-token",
                expiresAtMs: nowMs - 1
            )
        }
    }

    func callCount() -> Int { calls }

    private func response(
        _ request: AgentPairingRequest,
        status: AgentPairingStatus,
        code: String,
        token: String? = nil,
        expiresAtMs: Int64? = nil
    ) -> AgentPairingResponse {
        AgentPairingResponse(
            requestId: request.requestId,
            deviceId: request.deviceId,
            nonce: request.nonce,
            status: status,
            code: code,
            deviceToken: token,
            tokenExpiresAtMs: expiresAtMs
        )
    }
}

private struct Harness {
    private(set) var checks = 0

    mutating func expect(
        _ condition: @autoclosure () -> Bool,
        _ message: String
    ) throws {
        checks += 1
        guard condition() else {
            throw Failure(message: message)
        }
    }

    mutating func expectThrows(
        _ message: String,
        _ operation: () throws -> Void
    ) throws {
        checks += 1
        do {
            try operation()
        } catch {
            return
        }
        throw Failure(message: message)
    }

    struct Failure: Error, CustomStringConvertible {
        let message: String
        var description: String { message }
    }
}

private func command(
    id: String = "cmd-1",
    capability: AgentCapability = .mediaControl,
    action: String = "pause",
    deadline: Int64 = now + 5_000,
    arguments: [String: JSONValue] = [:]
) -> AgentCommand {
    AgentCommand(
        commandId: id,
        capability: capability,
        action: action,
        issuedAtMs: now,
        deadlineAtMs: deadline,
        arguments: arguments
    )
}

@main
private struct NexusAgentTestHarness {
    static func main() async {
        var harness = Harness()
        do {
            try await run(&harness)
            print("NexusAgent native harness: \(harness.checks) checks passed")
        } catch {
            FileHandle.standardError.write(
                Data("NexusAgent native harness failed: \(error)\n".utf8)
            )
            exit(1)
        }
    }

    private static func run(_ harness: inout Harness) async throws {
        try harness.expect(
            command().validationCode(nowMs: now) == nil,
            "valid command was rejected"
        )
        try harness.expect(
            command(id: "bad id").validationCode(nowMs: now)
                == "agent.command-id-invalid",
            "non-canonical command id was accepted"
        )
        try harness.expect(
            command(action: "bad action").validationCode(nowMs: now)
                == "agent.action-invalid",
            "non-canonical action was accepted"
        )
        try harness.expect(
            command(deadline: now - 1).validationCode(nowMs: now)
                == "agent.time-invalid",
            "invalid command time was accepted"
        )
        let futureCommand = AgentCommand(
            commandId: "future",
            capability: .mediaRead,
            action: "current_state",
            issuedAtMs: now + agentClockToleranceMs + 1,
            deadlineAtMs: now + agentClockToleranceMs + 2
        )
        try harness.expect(
            futureCommand.validationCode(nowMs: now) == "agent.time-invalid",
            "future command exceeded clock tolerance"
        )
        let longCommand = AgentCommand(
            commandId: "long",
            capability: .mediaRead,
            action: "current_state",
            issuedAtMs: now,
            deadlineAtMs: now + agentMaximumCommandLifetimeMs + 1
        )
        try harness.expect(
            longCommand.validationCode(nowMs: now) == "agent.time-invalid",
            "overlong command lifetime was accepted"
        )

        let handler = RecordingHandler()
        let runtime = try AgentRuntime(
            handlers: [handler],
            clockMs: { now }
        )
        let missing = await runtime.handle(
            command(id: "missing", capability: .systemRead)
        )
        try harness.expect(
            missing.code == "agent.capability-not-allowed",
            "capability allowlist was bypassed"
        )
        let forbidden = await runtime.handle(
            command(id: "forbidden", action: "play")
        )
        try harness.expect(
            forbidden.code == "agent.action-not-allowed",
            "action allowlist was bypassed"
        )

        let first = await runtime.handle(command())
        let retry = await runtime.handle(command())
        try harness.expect(first == retry, "retry was not idempotent")
        let effectCount = await handler.effectCount()
        try harness.expect(
            effectCount == 1,
            "idempotent retry repeated a side effect"
        )
        let conflict = await runtime.handle(
            command(
                action: "set_volume",
                arguments: ["volume": .number(0.5)]
            )
        )
        try harness.expect(
            conflict.code == "agent.command-conflict",
            "command id conflict did not fail closed"
        )

        let concurrentHandler = RecordingHandler(delayNs: 5_000_000)
        let concurrentRuntime = try AgentRuntime(
            handlers: [concurrentHandler],
            clockMs: { now }
        )
        async let concurrentFirst = concurrentRuntime.handle(
            command(id: "concurrent")
        )
        async let concurrentSecond = concurrentRuntime.handle(
            command(id: "concurrent")
        )
        let concurrentResults = await (
            concurrentFirst,
            concurrentSecond
        )
        let concurrentEffects = await concurrentHandler.effectCount()
        try harness.expect(
            concurrentResults.0 == concurrentResults.1,
            "concurrent retries returned different ACKs"
        )
        try harness.expect(
            concurrentEffects == 1,
            "concurrent retry repeated a side effect"
        )

        let conflictHandler = RecordingHandler(delayNs: 5_000_000)
        let conflictRuntime = try AgentRuntime(
            handlers: [conflictHandler],
            clockMs: { now }
        )
        async let conflictFirst = conflictRuntime.handle(
            command(id: "inflight-conflict")
        )
        async let conflictSecond = conflictRuntime.handle(
            command(
                id: "inflight-conflict",
                action: "set_volume",
                arguments: ["volume": .number(0.25)]
            )
        )
        let conflictResults = await (conflictFirst, conflictSecond)
        let conflictCodes = Set(
            [conflictResults.0.code, conflictResults.1.code]
        )
        let conflictEffects = await conflictHandler.effectCount()
        try harness.expect(
            conflictCodes.contains("agent.command-conflict"),
            "concurrent command id conflict did not fail closed"
        )
        try harness.expect(
            conflictEffects == 1,
            "concurrent command id conflict repeated a side effect"
        )

        let unknownHandler = RecordingHandler()
        await unknownHandler.setNext(
            AgentHandlerResult(
                .unknown,
                code: "test.timeout",
                retryable: true
            )
        )
        let unknownRuntime = try AgentRuntime(
            handlers: [unknownHandler],
            clockMs: { now }
        )
        let unknown = await unknownRuntime.handle(command(id: "unknown"))
        let unknownRetry = await unknownRuntime.handle(command(id: "unknown"))
        try harness.expect(
            unknown == unknownRetry && unknown.status == .unknown,
            "unknown result was not reconciled idempotently"
        )
        let unknownEffectCount = await unknownHandler.effectCount()
        try harness.expect(
            unknownEffectCount == 1,
            "unknown retry repeated a side effect"
        )

        await runtime.stop()
        let stopped = await runtime.handle(command(id: "after-stop"))
        try harness.expect(
            stopped.code == "agent.closed",
            "stopped runtime accepted a command"
        )
        try harness.expectThrows("duplicate capability was accepted") {
            _ = try AgentRuntime(
                handlers: [RecordingHandler(), RecordingHandler()]
            )
        }

        try harness.expectThrows("insecure ws endpoint was accepted") {
            _ = try URLSessionWebSocketTransport(
                endpoint: URL(string: "ws://localhost/agent")!,
                credential: validCredential,
                nowMs: now
            )
        }
        try harness.expectThrows("empty device token was accepted") {
            _ = try URLSessionWebSocketTransport(
                endpoint: URL(string: "wss://nexux.cl/agent")!,
                credential: DeviceCredential(
                    deviceId: "device-test-1",
                    token: "",
                    expiresAtMs: now + 60_000
                ),
                nowMs: now
            )
        }
        try harness.expectThrows("whitespace device token was accepted") {
            _ = try URLSessionWebSocketTransport(
                endpoint: URL(string: "wss://nexux.cl/agent")!,
                credential: DeviceCredential(
                    deviceId: "device-test-1",
                    token: "bad token",
                    expiresAtMs: now + 60_000
                ),
                nowMs: now
            )
        }
        _ = try URLSessionWebSocketTransport(
            endpoint: URL(string: "wss://nexux.cl/agent")!,
            credential: validCredential,
            nowMs: now
        )
        try harness.expect(true, "valid WSS transport failed")

        let policy = ReconnectPolicy(
            initialDelayMs: 1,
            maximumDelayMs: 8,
            multiplier: 2
        )
        try harness.expect(
            policy.delayMs(forAttempt: 0) == 0
                && policy.delayMs(forAttempt: 4) == 8
                && policy.delayMs(forAttempt: 100) == 8,
            "reconnect backoff was not bounded"
        )

        let roundTrip = command(
            id: "roundtrip-1",
            capability: .mediaRead,
            action: "current_state"
        )
        let data = try JSONEncoder().encode(roundTrip)
        let decoded = try JSONDecoder().decode(
            AgentCommand.self,
            from: data
        )
        try harness.expect(
            decoded == roundTrip,
            "command protocol did not round trip"
        )
        let text = String(decoding: data, as: UTF8.self)
        try harness.expect(
            !text.contains("token") && !text.contains("email"),
            "command envelope leaked identity or token fields"
        )

        let store = KeychainDeviceCredentialStore(service: "cl.nexux.test")
        try harness.expectThrows("empty Keychain device id was accepted") {
            _ = try store.load(deviceId: "")
        }
        try harness.expectThrows("non-canonical Keychain id was accepted") {
            _ = try store.load(deviceId: "bad device")
        }

        let loopHandler = RecordingHandler(
            capability: .mediaRead,
            actions: ["current_state"]
        )
        let loopRuntime = try AgentRuntime(
            handlers: [loopHandler],
            clockMs: { now }
        )
        let transport = StubTransport(
            incoming: try JSONEncoder().encode(roundTrip)
        )
        let loop = AgentConnectionLoop(
            runtime: loopRuntime,
            reconnectPolicy: policy,
            factory: { transport }
        )
        let task = Task { await loop.run() }
        try? await Task.sleep(nanoseconds: 25_000_000)
        await loop.stop()
        task.cancel()
        _ = await task.result
        let sent = await transport.sent()
        try harness.expect(sent.count == 1, "connection loop omitted ACK")
        let ack = try JSONDecoder().decode(AgentAck.self, from: sent[0])
        try harness.expect(
            ack.status == .applied
                && ack.commandId == roundTrip.commandId,
            "connection loop returned an invalid ACK"
        )
        let loopStats = await loop.stats()
        try harness.expect(
            loopStats.reconnects >= 1,
            "connection loop did not attempt recovery"
        )

        let oversizedRuntime = try AgentRuntime(
            handlers: [loopHandler],
            clockMs: { now }
        )
        let oversizedTransport = StubTransport(
            incoming: Data(repeating: 0x41, count: agentMaximumMessageBytes + 1)
        )
        let oversizedLoop = AgentConnectionLoop(
            runtime: oversizedRuntime,
            reconnectPolicy: policy,
            factory: { oversizedTransport }
        )
        let oversizedTask = Task { await oversizedLoop.run() }
        try? await Task.sleep(nanoseconds: 25_000_000)
        await oversizedLoop.stop()
        oversizedTask.cancel()
        _ = await oversizedTask.result
        let oversizedStats = await oversizedLoop.stats()
        try harness.expect(
            oversizedStats.decodeFailures == 1,
            "oversized command was not rejected before decode"
        )
        let oversizedSent = await oversizedTransport.sent()
        try harness.expect(
            oversizedSent.isEmpty,
            "oversized command produced an ACK"
        )

        try await verifyPairing(&harness)
    }

    private static func verifyPairing(
        _ harness: inout Harness
    ) async throws {
        let store = MemoryCredentialStore()
        let gateway = FakePairingGateway()
        let coordinator = AgentPairingCoordinator(
            gateway: gateway,
            store: store,
            clockMs: { now }
        )
        let credential = try await coordinator.pair(
            deviceId: "device-pairing-1",
            pairingCode: "ABC123",
            capabilities: [.mediaRead, .mediaControl]
        )
        try harness.expect(
            credential.deviceId == "device-pairing-1"
                && credential.token == "issued-device-token",
            "accepted pairing returned the wrong credential"
        )
        try harness.expect(
            !String(describing: credential).contains("issued-device-token"),
            "credential description leaked its token"
        )
        let persisted = try await coordinator.credential(
            deviceId: "device-pairing-1"
        )
        try harness.expect(
            persisted == credential,
            "accepted pairing was not persisted"
        )
        let acceptedStats = await coordinator.stats()
        try harness.expect(
            acceptedStats.attempts == 1
                && acceptedStats.accepted == 1
                && !acceptedStats.inProgress,
            "pairing stats exposed an invalid state"
        )
        let capturedRequest = AgentPairingRequest(
            requestId: "request-redaction",
            deviceId: "device-pairing-1",
            pairingCode: "SECRET1",
            nonce: "nonce-redaction",
            capabilities: [.mediaRead],
            issuedAtMs: now,
            deadlineAtMs: now + 1_000
        )
        let capturedResponse = AgentPairingResponse(
            requestId: capturedRequest.requestId,
            deviceId: capturedRequest.deviceId,
            nonce: capturedRequest.nonce,
            status: .accepted,
            code: "pairing.accepted",
            deviceToken: "response-secret",
            tokenExpiresAtMs: now + 60_000
        )
        try harness.expect(
            !String(describing: capturedRequest).contains("SECRET1"),
            "pairing request description leaked its code"
        )
        try harness.expect(
            !String(describing: capturedResponse).contains("response-secret"),
            "pairing response description leaked its token"
        )

        do {
            _ = try await coordinator.pair(
                deviceId: "device-pairing-1",
                pairingCode: "ABC123",
                capabilities: [.mediaRead]
            )
            try harness.expect(false, "consumed pairing code was reused")
        } catch let error as AgentPairingError {
            try harness.expect(
                error == .rejected,
                "consumed pairing code did not fail as rejected"
            )
        }

        let mismatchStore = MemoryCredentialStore()
        let mismatchCoordinator = AgentPairingCoordinator(
            gateway: FakePairingGateway(mode: .mismatched),
            store: mismatchStore,
            clockMs: { now }
        )
        do {
            _ = try await mismatchCoordinator.pair(
                deviceId: "device-pairing-2",
                pairingCode: "DEF456",
                capabilities: [.mediaRead]
            )
            try harness.expect(false, "mismatched device was accepted")
        } catch let error as AgentPairingError {
            try harness.expect(
                error == .responseMismatch,
                "mismatched response returned the wrong error"
            )
        }
        let mismatchedCredential = try mismatchStore.load(
            deviceId: "device-pairing-2"
        )
        try harness.expect(
            mismatchedCredential == nil,
            "mismatched response persisted a credential"
        )

        let expiredStore = MemoryCredentialStore()
        let expiredCoordinator = AgentPairingCoordinator(
            gateway: FakePairingGateway(mode: .expiredCredential),
            store: expiredStore,
            clockMs: { now }
        )
        do {
            _ = try await expiredCoordinator.pair(
                deviceId: "device-pairing-3",
                pairingCode: "GHI789",
                capabilities: [.mediaRead]
            )
            try harness.expect(false, "expired credential was accepted")
        } catch let error as AgentPairingError {
            try harness.expect(
                error == .invalidCredential,
                "expired credential returned the wrong error"
            )
        }

        let delayedGateway = FakePairingGateway(delayNs: 10_000_000)
        let concurrentCoordinator = AgentPairingCoordinator(
            gateway: delayedGateway,
            store: MemoryCredentialStore(),
            clockMs: { now },
            pairingLifetimeMs: 50
        )
        let firstPairing = Task {
            try await concurrentCoordinator.pair(
                deviceId: "device-pairing-4",
                pairingCode: "JKL012",
                capabilities: [.mediaRead]
            )
        }
        try? await Task.sleep(nanoseconds: 1_000_000)
        do {
            _ = try await concurrentCoordinator.pair(
                deviceId: "device-pairing-4",
                pairingCode: "MNO345",
                capabilities: [.mediaRead]
            )
            try harness.expect(false, "concurrent pairing was accepted")
        } catch let error as AgentPairingError {
            try harness.expect(
                error == .alreadyInProgress,
                "concurrent pairing returned the wrong error"
            )
        }
        _ = try await firstPairing.value

        let timeoutCoordinator = AgentPairingCoordinator(
            gateway: FakePairingGateway(delayNs: 20_000_000),
            store: MemoryCredentialStore(),
            clockMs: { now },
            pairingLifetimeMs: 2
        )
        do {
            _ = try await timeoutCoordinator.pair(
                deviceId: "device-pairing-5",
                pairingCode: "PQR678",
                capabilities: [.mediaRead]
            )
            try harness.expect(false, "pairing timeout was accepted")
        } catch let error as AgentPairingError {
            try harness.expect(
                error == .timeout,
                "pairing timeout returned the wrong error"
            )
        }

        let failingStoreCoordinator = AgentPairingCoordinator(
            gateway: FakePairingGateway(),
            store: MemoryCredentialStore(failSave: true),
            clockMs: { now }
        )
        do {
            _ = try await failingStoreCoordinator.pair(
                deviceId: "device-pairing-6",
                pairingCode: "STU901",
                capabilities: [.mediaRead]
            )
            try harness.expect(false, "credential store failure was ignored")
        } catch let error as AgentPairingError {
            try harness.expect(
                error == .credentialStore,
                "credential store returned the wrong error"
            )
        }
        let failingStats = await failingStoreCoordinator.stats()
        try harness.expect(
            failingStats.failures == 1,
            "credential store failure was counted more than once"
        )

        try await coordinator.revoke(deviceId: "device-pairing-1")
        let revoked = try await coordinator.credential(
            deviceId: "device-pairing-1"
        )
        try harness.expect(revoked == nil, "revoked credential remained stored")
    }
}
