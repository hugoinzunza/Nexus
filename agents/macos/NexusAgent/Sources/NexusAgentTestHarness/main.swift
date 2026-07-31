import Foundation
import NexusAgentCore

private let now: Int64 = 1_785_430_000_000

private enum HarnessError: Error {
    case disconnected
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
                deviceToken: "token"
            )
        }
        try harness.expectThrows("empty device token was accepted") {
            _ = try URLSessionWebSocketTransport(
                endpoint: URL(string: "wss://nexux.cl/agent")!,
                deviceToken: ""
            )
        }
        try harness.expectThrows("whitespace device token was accepted") {
            _ = try URLSessionWebSocketTransport(
                endpoint: URL(string: "wss://nexux.cl/agent")!,
                deviceToken: "bad token"
            )
        }
        _ = try URLSessionWebSocketTransport(
            endpoint: URL(string: "wss://nexux.cl/agent")!,
            deviceToken: "opaque-device-token"
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

        let store = KeychainDeviceTokenStore(service: "cl.nexux.test")
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
    }
}
