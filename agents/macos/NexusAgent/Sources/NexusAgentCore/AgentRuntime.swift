import Foundation

public struct AgentRuntimeStats: Equatable, Sendable {
    public let handled: Int
    public let rejected: Int
    public let unknown: Int
    public let cacheHits: Int
    public let cachedCommands: Int
    public let closed: Bool
}

public actor AgentRuntime {
    private struct CacheEntry: Sendable {
        let fingerprint: Data
        let ack: AgentAck
    }

    private struct InFlightEntry: Sendable {
        let fingerprint: Data
        let task: Task<AgentHandlerResult, Never>
    }

    private let handlers: [AgentCapability: any AgentCapabilityHandler]
    private let clockMs: @Sendable () -> Int64
    private let maxCachedCommands: Int
    private var cache: [String: CacheEntry] = [:]
    private var cacheOrder: [String] = []
    private var inFlight: [String: InFlightEntry] = [:]
    private var handled = 0
    private var rejected = 0
    private var unknown = 0
    private var cacheHits = 0
    private var closed = false

    public init(
        handlers: [any AgentCapabilityHandler],
        maxCachedCommands: Int = 1_024,
        clockMs: @escaping @Sendable () -> Int64 = {
            Int64(Date().timeIntervalSince1970 * 1_000)
        }
    ) throws {
        guard maxCachedCommands > 0 else {
            throw AgentRuntimeError.invalidCacheLimit
        }
        var indexed: [AgentCapability: any AgentCapabilityHandler] = [:]
        for handler in handlers {
            guard indexed[handler.capability] == nil else {
                throw AgentRuntimeError.duplicateCapability(handler.capability)
            }
            indexed[handler.capability] = handler
        }
        self.handlers = indexed
        self.maxCachedCommands = maxCachedCommands
        self.clockMs = clockMs
    }

    public func handle(_ command: AgentCommand) async -> AgentAck {
        let now = clockMs()
        if closed {
            return rejection(
                command,
                now: now,
                code: "agent.closed",
                retryable: false
            )
        }
        if let validationCode = command.validationCode(nowMs: now) {
            return rejection(
                command,
                now: now,
                code: validationCode,
                retryable: false
            )
        }
        let fingerprint: Data
        do {
            fingerprint = try command.fingerprint()
        } catch {
            return rejection(
                command,
                now: now,
                code: "agent.command-unencodable",
                retryable: false
            )
        }
        if let known = cache[command.commandId] {
            guard known.fingerprint == fingerprint else {
                return rejection(
                    command,
                    now: now,
                    code: "agent.command-conflict",
                    retryable: false
                )
            }
            cacheHits += 1
            return known.ack
        }
        if let pending = inFlight[command.commandId] {
            guard pending.fingerprint == fingerprint else {
                return rejection(
                    command,
                    now: now,
                    code: "agent.command-conflict",
                    retryable: false
                )
            }
            let result = await pending.task.value
            if let known = cache[command.commandId] {
                cacheHits += 1
                return known.ack
            }
            inFlight.removeValue(forKey: command.commandId)
            return remember(
                command,
                fingerprint: fingerprint,
                result: result
            )
        }
        guard let handler = handlers[command.capability] else {
            return remember(
                command,
                fingerprint: fingerprint,
                result: AgentHandlerResult(
                    .rejected,
                    code: "agent.capability-not-allowed"
                )
            )
        }
        guard handler.allowedActions.contains(command.action) else {
            return remember(
                command,
                fingerprint: fingerprint,
                result: AgentHandlerResult(
                    .rejected,
                    code: "agent.action-not-allowed"
                )
            )
        }
        let task = Task {
            await handler.execute(command)
        }
        inFlight[command.commandId] = InFlightEntry(
            fingerprint: fingerprint,
            task: task
        )
        let result = await task.value
        if let known = cache[command.commandId] {
            cacheHits += 1
            return known.ack
        }
        inFlight.removeValue(forKey: command.commandId)
        return remember(command, fingerprint: fingerprint, result: result)
    }

    public func stop() {
        closed = true
    }

    public func stats() -> AgentRuntimeStats {
        AgentRuntimeStats(
            handled: handled,
            rejected: rejected,
            unknown: unknown,
            cacheHits: cacheHits,
            cachedCommands: cache.count,
            closed: closed
        )
    }

    private func remember(
        _ command: AgentCommand,
        fingerprint: Data,
        result: AgentHandlerResult
    ) -> AgentAck {
        let ack = AgentAck(
            protocolVersion: agentProtocolVersion,
            commandId: command.commandId,
            capability: command.capability,
            action: command.action,
            status: result.status,
            completedAtMs: clockMs(),
            code: result.code,
            retryable: result.retryable
        )
        cache[command.commandId] = CacheEntry(
            fingerprint: fingerprint,
            ack: ack
        )
        cacheOrder.append(command.commandId)
        while cacheOrder.count > maxCachedCommands {
            let expired = cacheOrder.removeFirst()
            cache.removeValue(forKey: expired)
        }
        handled += 1
        if result.status == .rejected { rejected += 1 }
        if result.status == .unknown { unknown += 1 }
        return ack
    }

    private func rejection(
        _ command: AgentCommand,
        now: Int64,
        code: String,
        retryable: Bool
    ) -> AgentAck {
        rejected += 1
        return AgentAck(
            protocolVersion: agentProtocolVersion,
            commandId: command.commandId,
            capability: command.capability,
            action: command.action,
            status: .rejected,
            completedAtMs: now,
            code: code,
            retryable: retryable
        )
    }
}

public enum AgentRuntimeError: Error, Equatable {
    case invalidCacheLimit
    case duplicateCapability(AgentCapability)
}
