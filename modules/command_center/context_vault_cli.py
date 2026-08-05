"""CLI manual para Context Vault; deliberadamente sin scheduler ni activacion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .context_storage import ContextStorageManager
from .context_vault_google_drive import (
    ContextVaultError,
    ContextVaultKeyManager,
    ContextVaultManager,
    GoogleDriveVaultProvider,
    default_google_drive_vault_root,
    run_canary_restore,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexux-context-vault")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("discover-google-drive")

    keygen = commands.add_parser("keygen")
    keygen.add_argument("--key-root", required=True)
    keygen.add_argument("--repo-root", required=True)
    keygen.add_argument("--vault-root")

    provider = commands.add_parser("init-google-drive")
    provider.add_argument("--vault-root", required=True)

    for name in ("backup", "health"):
        command = commands.add_parser(name)
        command.add_argument("--storage-root", required=True)
        command.add_argument("--vault-root", required=True)
        command.add_argument("--public-key-file", required=True)
    commands.choices["backup"].add_argument("--provenance", required=True)

    restore = commands.add_parser("restore")
    restore.add_argument("--storage-root", required=True)
    restore.add_argument("--vault-root", required=True)
    restore.add_argument("--public-key-file", required=True)
    restore.add_argument("--private-key-file", required=True)
    restore.add_argument("--snapshot-artifact", required=True)
    restore.add_argument("--target-root", required=True)
    restore.add_argument("--report-path")

    canary = commands.add_parser("canary")
    canary.add_argument("--vault-root", required=True)
    canary.add_argument("--key-root", required=True)
    canary.add_argument("--workspace-root", required=True)
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _manager(args) -> ContextVaultManager:
    storage = ContextStorageManager.from_existing(args.storage_root)
    provider = GoogleDriveVaultProvider(args.vault_root)
    return ContextVaultManager(
        storage,
        provider,
        public_key_file=args.public_key_file,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "discover-google-drive":
            mounts = GoogleDriveVaultProvider.discover()
            _print(
                {
                    "mounts": [str(path) for path in mounts],
                    "default_vault_root": (
                        str(default_google_drive_vault_root())
                        if default_google_drive_vault_root()
                        else None
                    ),
                }
            )
        elif args.command == "keygen":
            forbidden = (args.vault_root,) if args.vault_root else ()
            _print(
                ContextVaultKeyManager.generate(
                    args.key_root,
                    repo_root=args.repo_root,
                    forbidden_roots=forbidden,
                )
            )
        elif args.command == "init-google-drive":
            _print(GoogleDriveVaultProvider(args.vault_root).initialize())
        elif args.command == "backup":
            _print(_manager(args).backup_incremental(provenance=args.provenance))
        elif args.command == "health":
            _print(_manager(args).health())
        elif args.command == "restore":
            _print(
                _manager(args).restore_snapshot(
                    args.snapshot_artifact,
                    args.target_root,
                    private_key_file=args.private_key_file,
                    report_path=args.report_path,
                )
            )
        elif args.command == "canary":
            _print(
                run_canary_restore(
                    args.vault_root,
                    args.key_root,
                    args.workspace_root,
                )
            )
        return 0
    except (ContextVaultError, OSError, ValueError, KeyError) as exc:
        _print({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
