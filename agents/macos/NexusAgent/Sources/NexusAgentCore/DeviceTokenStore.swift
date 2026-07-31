import Foundation
import Security

public enum DeviceTokenStoreError: Error, Equatable {
    case invalidIdentifier
    case invalidTokenEncoding
    case keychain(OSStatus)
}

public protocol DeviceTokenStore: Sendable {
    func load(deviceId: String) throws -> String?
    func save(_ token: String, deviceId: String) throws
    func delete(deviceId: String) throws
}

public struct KeychainDeviceTokenStore: DeviceTokenStore, @unchecked Sendable {
    public let service: String

    public init(service: String = "cl.nexux.command-center.agent") {
        self.service = service
    }

    public func load(deviceId: String) throws -> String? {
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
            throw DeviceTokenStoreError.keychain(status)
        }
        guard let data = result as? Data,
              let token = String(data: data, encoding: .utf8) else {
            throw DeviceTokenStoreError.invalidTokenEncoding
        }
        return token
    }

    public func save(_ token: String, deviceId: String) throws {
        try Self.validate(deviceId)
        guard !token.isEmpty, let data = token.data(using: .utf8) else {
            throw DeviceTokenStoreError.invalidTokenEncoding
        }
        let query = baseQuery(deviceId: deviceId)
        let update = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(
            query as CFDictionary,
            update as CFDictionary
        )
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw DeviceTokenStoreError.keychain(updateStatus)
        }
        var item = query
        item[kSecValueData as String] = data
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw DeviceTokenStoreError.keychain(addStatus)
        }
    }

    public func delete(deviceId: String) throws {
        try Self.validate(deviceId)
        let status = SecItemDelete(
            baseQuery(deviceId: deviceId) as CFDictionary
        )
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw DeviceTokenStoreError.keychain(status)
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
        guard !deviceId.isEmpty, deviceId.count <= 128 else {
            throw DeviceTokenStoreError.invalidIdentifier
        }
        let allowed = CharacterSet(
            charactersIn:
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
        )
        guard deviceId.unicodeScalars.allSatisfy(allowed.contains),
              deviceId.first?.isLetterOrNumber == true else {
            throw DeviceTokenStoreError.invalidIdentifier
        }
    }
}

private extension Character {
    var isLetterOrNumber: Bool {
        unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0)
        }
    }
}
