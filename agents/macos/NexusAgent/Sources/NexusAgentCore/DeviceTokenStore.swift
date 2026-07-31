import Foundation
import Security

public struct DeviceCredential:
    Codable,
    Equatable,
    Sendable,
    CustomStringConvertible,
    CustomDebugStringConvertible
{
    public let deviceId: String
    public let token: String
    public let expiresAtMs: Int64

    public init(deviceId: String, token: String, expiresAtMs: Int64) {
        self.deviceId = deviceId
        self.token = token
        self.expiresAtMs = expiresAtMs
    }

    public func validationCode(nowMs: Int64) -> String? {
        guard AgentIdentity.isCanonicalIdentifier(deviceId) else {
            return "agent.device-id-invalid"
        }
        guard AgentIdentity.isOpaqueSecret(token) else {
            return "agent.device-token-invalid"
        }
        guard expiresAtMs > nowMs else {
            return "agent.device-token-expired"
        }
        return nil
    }

    public var description: String {
        "DeviceCredential(deviceId: \(deviceId), token: <redacted>, "
            + "expiresAtMs: \(expiresAtMs))"
    }

    public var debugDescription: String { description }
}

public enum DeviceCredentialStoreError: Error, Equatable {
    case invalidIdentifier
    case invalidCredential
    case keychain(OSStatus)
}

public protocol DeviceCredentialStore: Sendable {
    func load(deviceId: String) throws -> DeviceCredential?
    func save(_ credential: DeviceCredential) throws
    func delete(deviceId: String) throws
}

public struct KeychainDeviceCredentialStore:
    DeviceCredentialStore,
    @unchecked Sendable
{
    public let service: String

    public init(service: String = "cl.nexux.command-center.agent") {
        self.service = service
    }

    public func load(deviceId: String) throws -> DeviceCredential? {
        try Self.validate(deviceId)
        var query = baseQuery(deviceId: deviceId)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(
            query as CFDictionary,
            &result
        )
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else {
            throw DeviceCredentialStoreError.keychain(status)
        }
        guard let data = result as? Data,
              let credential = try? JSONDecoder().decode(
                  DeviceCredential.self,
                  from: data
              ),
              credential.deviceId == deviceId else {
            throw DeviceCredentialStoreError.invalidCredential
        }
        return credential
    }

    public func save(_ credential: DeviceCredential) throws {
        try Self.validate(credential.deviceId)
        guard credential.validationCode(nowMs: 0) == nil,
              let data = try? JSONEncoder().encode(credential) else {
            throw DeviceCredentialStoreError.invalidCredential
        }
        let query = baseQuery(deviceId: credential.deviceId)
        let update = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(
            query as CFDictionary,
            update as CFDictionary
        )
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw DeviceCredentialStoreError.keychain(updateStatus)
        }
        var item = query
        item[kSecValueData as String] = data
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw DeviceCredentialStoreError.keychain(addStatus)
        }
    }

    public func delete(deviceId: String) throws {
        try Self.validate(deviceId)
        let status = SecItemDelete(
            baseQuery(deviceId: deviceId) as CFDictionary
        )
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw DeviceCredentialStoreError.keychain(status)
        }
    }

    private func baseQuery(deviceId: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: deviceId,
            kSecAttrAccessible as String:
                kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
    }

    private static func validate(_ deviceId: String) throws {
        guard AgentIdentity.isCanonicalIdentifier(deviceId) else {
            throw DeviceCredentialStoreError.invalidIdentifier
        }
    }
}
