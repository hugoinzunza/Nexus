// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "NexusAgent",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "NexusAgentCore", targets: ["NexusAgentCore"]),
        .executable(name: "nexus-agent", targets: ["NexusAgent"]),
        .executable(
            name: "nexus-agent-tests",
            targets: ["NexusAgentTestHarness"]
        ),
    ],
    targets: [
        .target(name: "NexusAgentCore"),
        .executableTarget(
            name: "NexusAgent",
            dependencies: ["NexusAgentCore"]
        ),
        .executableTarget(
            name: "NexusAgentTestHarness",
            dependencies: ["NexusAgentCore"]
        ),
    ]
)
