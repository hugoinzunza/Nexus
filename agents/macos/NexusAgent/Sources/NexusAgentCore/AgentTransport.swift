import Foundation

public enum AgentTransportError: Error, Equatable {
    case invalidEndpoint
    case missingDeviceToken
    case alreadyConnected
    case notConnected
    case unsupportedMessage
}

public protocol AgentTransport: Sendable {
    func connect() async throws
    func send(_ data: Data) async throws
    func receive() async throws -> Data
    func close() async
}

public actor URLSessionWebSocketTransport: AgentTransport {
    private let endpoint: URL
    private let deviceToken: String
    private let session: URLSession
    private var task: URLSessionWebSocketTask?

    public init(
        endpoint: URL,
        deviceToken: String,
        session: URLSession = .shared
    ) throws {
        guard endpoint.scheme?.lowercased() == "wss",
              endpoint.host != nil else {
            throw AgentTransportError.invalidEndpoint
        }
        guard !deviceToken.isEmpty,
              deviceToken.utf8.count <= 4_096,
              !deviceToken.unicodeScalars.contains(
                  where: CharacterSet.whitespacesAndNewlines.contains
              ) else {
            throw AgentTransportError.missingDeviceToken
        }
        self.endpoint = endpoint
        self.deviceToken = deviceToken
        self.session = session
    }

    public func connect() async throws {
        guard task == nil else {
            throw AgentTransportError.alreadyConnected
        }
        var request = URLRequest(url: endpoint)
        request.setValue(
            "Bearer \(deviceToken)",
            forHTTPHeaderField: "Authorization"
        )
        request.setValue(
            agentProtocolVersion,
            forHTTPHeaderField: "X-Nexux-Agent-Version"
        )
        let socket = session.webSocketTask(with: request)
        task = socket
        socket.resume()
    }

    public func send(_ data: Data) async throws {
        guard let task else { throw AgentTransportError.notConnected }
        try await task.send(.data(data))
    }

    public func receive() async throws -> Data {
        guard let task else { throw AgentTransportError.notConnected }
        switch try await task.receive() {
        case .data(let data):
            return data
        case .string(let text):
            guard let data = text.data(using: .utf8) else {
                throw AgentTransportError.unsupportedMessage
            }
            return data
        @unknown default:
            throw AgentTransportError.unsupportedMessage
        }
    }

    public func close() async {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
    }
}

public struct ReconnectPolicy: Equatable, Sendable {
    public let initialDelayMs: UInt64
    public let maximumDelayMs: UInt64
    public let multiplier: UInt64

    public init(
        initialDelayMs: UInt64 = 500,
        maximumDelayMs: UInt64 = 30_000,
        multiplier: UInt64 = 2
    ) {
        precondition(initialDelayMs > 0)
        precondition(maximumDelayMs >= initialDelayMs)
        precondition(multiplier >= 1)
        self.initialDelayMs = initialDelayMs
        self.maximumDelayMs = maximumDelayMs
        self.multiplier = multiplier
    }

    public func delayMs(forAttempt attempt: Int) -> UInt64 {
        guard attempt > 0 else { return 0 }
        var delay = initialDelayMs
        for _ in 1..<attempt {
            let multiplied = delay.multipliedReportingOverflow(
                by: multiplier
            )
            if multiplied.overflow {
                return maximumDelayMs
            }
            delay = min(maximumDelayMs, multiplied.partialValue)
        }
        return delay
    }
}

public actor AgentConnectionLoop {
    public typealias TransportFactory =
        @Sendable () throws -> any AgentTransport

    private let runtime: AgentRuntime
    private let factory: TransportFactory
    private let reconnectPolicy: ReconnectPolicy
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()
    private var activeTransport: (any AgentTransport)?
    private var stopped = false
    private var connectionAttempts = 0
    private var reconnects = 0
    private var decodeFailures = 0

    public init(
        runtime: AgentRuntime,
        reconnectPolicy: ReconnectPolicy = ReconnectPolicy(),
        factory: @escaping TransportFactory
    ) {
        self.runtime = runtime
        self.reconnectPolicy = reconnectPolicy
        self.factory = factory
        encoder.outputFormatting = [.sortedKeys]
    }

    public func run() async {
        var attempt = 0
        while !stopped && !Task.isCancelled {
            do {
                let transport = try factory()
                activeTransport = transport
                connectionAttempts += 1
                try await transport.connect()
                attempt = 0
                try await consume(transport)
            } catch is CancellationError {
                break
            } catch {
                if stopped || Task.isCancelled { break }
                attempt += 1
                reconnects += 1
                let delay = reconnectPolicy.delayMs(forAttempt: attempt)
                try? await Task.sleep(
                    nanoseconds: delay * 1_000_000
                )
            }
            await activeTransport?.close()
            activeTransport = nil
        }
    }

    public func stop() async {
        stopped = true
        await activeTransport?.close()
        activeTransport = nil
        await runtime.stop()
    }

    public func stats() -> (
        connectionAttempts: Int,
        reconnects: Int,
        decodeFailures: Int,
        stopped: Bool
    ) {
        (connectionAttempts, reconnects, decodeFailures, stopped)
    }

    private func consume(_ transport: any AgentTransport) async throws {
        while !stopped && !Task.isCancelled {
            let payload = try await transport.receive()
            guard payload.count <= agentMaximumMessageBytes else {
                decodeFailures += 1
                continue
            }
            let command: AgentCommand
            do {
                command = try decoder.decode(AgentCommand.self, from: payload)
            } catch {
                decodeFailures += 1
                continue
            }
            let ack = await runtime.handle(command)
            try await transport.send(try encoder.encode(ack))
        }
    }
}
