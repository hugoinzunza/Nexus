"""Herramientas offline para preparar y verificar Context Storage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .context_storage import ContextStorageError, ContextStorageManager


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexux-context-storage")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser("init")
    init.add_argument("--root", required=True)
    init.add_argument("--repo-root")
    init.add_argument("--retention-days", type=int, default=90)
    init.add_argument("--max-segment-mib", type=int, default=64)
    init.add_argument("--max-segment-hours", type=int, default=24)
    init.add_argument("--minimum-free-gib", type=int, default=2)

    for name in ("audit", "snapshot", "retention"):
        command = subcommands.add_parser(name)
        command.add_argument("--root", required=True)

    rotate = subcommands.add_parser("rotate")
    rotate.add_argument("--root", required=True)
    rotate.add_argument("--force", action="store_true")

    backup = subcommands.add_parser("backup")
    backup.add_argument("--root", required=True)
    backup.add_argument("--destination", required=True)
    backup.add_argument("--public-key-file", required=True)

    restore = subcommands.add_parser("restore")
    restore.add_argument("--vault-dir", required=True)
    restore.add_argument("--target", required=True)
    restore.add_argument("--private-key-file", required=True)

    verify = subcommands.add_parser("verify-restore")
    verify.add_argument("--root", required=True)
    verify.add_argument("--restored-root", required=True)

    drill = subcommands.add_parser("record-isolated-drill")
    drill.add_argument("--root", required=True)
    drill.add_argument("--drill-source-root", required=True)
    drill.add_argument("--drill-restored-root", required=True)

    recover = subcommands.add_parser("recover-tail")
    recover.add_argument("--root", required=True)
    recover.add_argument(
        "--confirm-truncate-incomplete-tail",
        action="store_true",
    )
    return parser


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            manager = ContextStorageManager(
                args.root,
                repo_root=args.repo_root,
                retention_days=args.retention_days,
                max_segment_bytes=args.max_segment_mib * 1024 * 1024,
                max_segment_age_ms=args.max_segment_hours * 60 * 60_000,
                min_free_bytes=args.minimum_free_gib * 1024 * 1024 * 1024,
            )
            _print(manager.initialize())
            return 0
        if args.command == "restore":
            vaults = sorted(Path(args.vault_dir).glob("segment-*.vault.json"))
            private_pem = Path(args.private_key_file).read_text(encoding="utf-8")
            manager = ContextStorageManager.restore_vaults(
                vaults,
                args.target,
                private_pem,
            )
            _print(manager.health())
            return 0

        manager = ContextStorageManager.from_existing(args.root)
        if args.command == "audit":
            _print(manager.audit())
        elif args.command == "snapshot":
            _print({"snapshot": str(manager.create_consistency_snapshot())})
        elif args.command == "retention":
            _print({"candidates": manager.retention_candidates()})
        elif args.command == "rotate":
            _print({"manifest": manager.rotate_if_needed(force=args.force)})
        elif args.command == "backup":
            public_pem = Path(args.public_key_file).read_text(encoding="utf-8")
            _print(
                {
                    "receipts": manager.backup_closed_segments(
                        args.destination,
                        public_pem,
                    )
                }
            )
        elif args.command == "verify-restore":
            _print(manager.verify_restore_drill(args.restored_root))
        elif args.command == "record-isolated-drill":
            _print(
                manager.record_isolated_restore_drill(
                    args.drill_source_root,
                    args.drill_restored_root,
                )
            )
        elif args.command == "recover-tail":
            if not args.confirm_truncate_incomplete_tail:
                raise ContextStorageError(
                    "tail recovery requires explicit confirmation"
                )
            _print({"recovery": manager.recover_incomplete_tail()})
        return 0
    except (ContextStorageError, OSError, ValueError, KeyError) as exc:
        _print({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
