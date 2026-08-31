"""Operator recovery for one dead-lettered Flow lifecycle audit row.

This command is intended for a trusted deployment shell or Kubernetes
operations wrapper. It deliberately has no tenant-facing authentication or
bulk operation surface.

Usage:
    uv run python -m eneo.cli.flow_audit_outbox list
    uv run python -m eneo.cli.flow_audit_outbox dry-run OUTBOX_ID \
        --expected-dead-lettered-at TIMESTAMP
    uv run python -m eneo.cli.flow_audit_outbox redrive OUTBOX_ID \
        --expected-dead-lettered-at TIMESTAMP --reason "Storage recovered"

The redrive operator identity is read from ``ENEO_OPERATOR_IDENTITY``. The
deployment wrapper must populate that value from its trusted identity source;
it is not accepted as an arbitrary command-line label.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.flows.domain.flow_audit_outbox_limits import (
    FLOW_AUDIT_OUTBOX_OPERATOR_IDENTITY_MAX,
    FLOW_AUDIT_OUTBOX_OPERATOR_LIST_MAX,
    FLOW_AUDIT_OUTBOX_OPERATOR_REASON_MAX,
)

if TYPE_CHECKING:
    from eneo.flows.application.flow_run_audit_outbox_delivery import (
        FlowRunAuditOutboxDeliveryService,
    )
    from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
        FlowRunAuditOutboxDeadLetterRow,
    )


OPERATOR_IDENTITY_ENV = "ENEO_OPERATOR_IDENTITY"

EXIT_OK = 0
EXIT_NOT_FOUND = 10
EXIT_STATE_CONFLICT = 11
EXIT_GENERATION_CONFLICT = 12
EXIT_BOOTSTRAP_FAILURE = 20
EXIT_AUDIT_SINK_FAILURE = 21


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eneo-flow-audit-outbox",
        description="Inspect and redrive one Flow audit outbox dead letter.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser(
        "list", help="list a bounded oldest-first page of dead letters"
    )
    list_parser.add_argument(
        "--limit",
        type=_bounded_limit,
        default=50,
        help=f"rows to return (1-{FLOW_AUDIT_OUTBOX_OPERATOR_LIST_MAX}; default: 50)",
    )
    for command, help_text in (
        ("dry-run", "show the transition for one dead letter without changing it"),
        ("redrive", "redrive one dead letter through the normal delivery worker"),
    ):
        command_parser = commands.add_parser(command, help=help_text)
        command_parser.add_argument("outbox_id", type=_uuid)
        command_parser.add_argument(
            "--expected-dead-lettered-at",
            required=True,
            type=_aware_datetime,
            help="exact generation token returned by list",
        )
        if command == "redrive":
            command_parser.add_argument(
                "--reason",
                required=True,
                type=_bounded_reason,
                help=(
                    "bounded operator diagnosis "
                    f"(1-{FLOW_AUDIT_OUTBOX_OPERATOR_REASON_MAX} characters)"
                ),
            )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run_with_database(args)
    except KeyboardInterrupt:
        return EXIT_BOOTSTRAP_FAILURE


def _run_with_database(args: argparse.Namespace) -> int:
    """Bootstrap settings/database and guarantee engine cleanup."""
    try:
        return asyncio.run(_run_database(args))
    except KeyboardInterrupt:
        return EXIT_BOOTSTRAP_FAILURE


async def _run_database(args: argparse.Namespace) -> int:
    from eneo.database.database import sessionmanager
    from eneo.main.config import get_settings

    try:
        settings = get_settings()
        sessionmanager.init(settings.database_url)
    except (Exception, SystemExit):
        _write_error("database/configuration bootstrap failed")
        try:
            await sessionmanager.close()
        except Exception:
            _write_error("database cleanup failed")
        return EXIT_BOOTSTRAP_FAILURE

    try:
        result = await _run_command(args)
    except BaseException:
        try:
            await sessionmanager.close()
        except Exception:
            _write_error("database cleanup failed")
        raise
    try:
        await sessionmanager.close()
    except Exception:
        _write_error("database cleanup failed")
        return EXIT_BOOTSTRAP_FAILURE
    return result


async def _run_command(args: argparse.Namespace) -> int:
    from dependency_injector import providers

    from eneo.database.database import sessionmanager
    from eneo.flows.application.flow_run_audit_outbox_delivery import (
        FlowRunAuditOutboxGenerationConflictError,
        FlowRunAuditOutboxNotFoundError,
        FlowRunAuditOutboxStateConflictError,
    )
    from eneo.main.container.container import Container

    try:
        async with sessionmanager.session() as session, session.begin():
            container = Container(session=providers.Object(session))
            service = container.flow_run_audit_outbox_delivery_service()
            if args.command == "list":
                return await _list_dead_letters(service, args)
            if args.command == "dry-run":
                return await _dry_run(service, args)
            if args.command == "redrive":
                return await _redrive(service, args)
            _write_error("unsupported command")
            return EXIT_BOOTSTRAP_FAILURE
    except FlowRunAuditOutboxNotFoundError:
        _write_error("audit outbox row not found")
        return EXIT_NOT_FOUND
    except FlowRunAuditOutboxStateConflictError:
        _write_error("audit outbox row is not dead-lettered")
        return EXIT_STATE_CONFLICT
    except FlowRunAuditOutboxGenerationConflictError:
        _write_error("audit outbox dead-letter generation changed; list again")
        return EXIT_GENERATION_CONFLICT
    except ValueError as exc:
        _write_error(str(exc))
        return EXIT_BOOTSTRAP_FAILURE
    except (Exception, SystemExit):
        _write_error("audit outbox operation failed; inspect the audit sink")
        return EXIT_AUDIT_SINK_FAILURE


async def _list_dead_letters(
    service: FlowRunAuditOutboxDeliveryService,
    args: argparse.Namespace,
) -> int:
    page = await service.list_dead_letters(limit=args.limit, offset=0)
    _write_json(
        {
            "items": [_dead_letter_json(row) for row in page.items],
            "has_more": page.has_more,
            "limit": args.limit,
        }
    )
    return EXIT_OK


async def _dry_run(
    service: FlowRunAuditOutboxDeliveryService,
    args: argparse.Namespace,
) -> int:
    inspection = await service.inspect_redrive(
        outbox_id=args.outbox_id,
        expected_dead_lettered_at=args.expected_dead_lettered_at,
    )
    _write_json(
        {
            "action": "redrive",
            "dry_run": True,
            "outbox_id": str(inspection.outbox_id),
            "delivery_status": "dead_lettered",
            "expected_dead_lettered_at": inspection.dead_lettered_at.isoformat(),
        }
    )
    return EXIT_OK


async def _redrive(
    service: FlowRunAuditOutboxDeliveryService,
    args: argparse.Namespace,
) -> int:
    operator_identity = _trusted_operator_identity()
    result = await service.redrive_dead_lettered(
        outbox_id=args.outbox_id,
        expected_dead_lettered_at=args.expected_dead_lettered_at,
        reason=args.reason,
        operator_identity=operator_identity,
        now=datetime.now(timezone.utc),
    )
    _write_json(
        {
            "action": "redrive",
            "dry_run": False,
            "outbox_id": str(result.outbox_id),
            "flow_run_id": str(result.flow_run_id),
            "delivery_status": result.delivery_status,
            "delivery_attempts": result.delivery_attempts,
            "next_delivery_at": result.next_delivery_at.isoformat(),
            "operator_audit_id": str(result.operator_audit_id),
        }
    )
    return EXIT_OK


def _trusted_operator_identity() -> str:
    value = os.environ.get(OPERATOR_IDENTITY_ENV, "")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{OPERATOR_IDENTITY_ENV} must be configured")
    if len(normalized) > FLOW_AUDIT_OUTBOX_OPERATOR_IDENTITY_MAX:
        raise ValueError(
            f"{OPERATOR_IDENTITY_ENV} must not exceed "
            f"{FLOW_AUDIT_OUTBOX_OPERATOR_IDENTITY_MAX} characters"
        )
    return normalized


def _dead_letter_json(row: FlowRunAuditOutboxDeadLetterRow) -> dict[str, object]:
    # The service returns a typed row and strips persisted diagnostics. Keep
    # this explicit allowlist so payloads can never enter operator stdout.
    return {
        "outbox_id": str(row.outbox_id),
        "tenant_id": str(row.tenant_id),
        "flow_id": str(row.flow_id),
        "flow_run_id": str(row.flow_run_id),
        "action": row.action,
        "source": row.source,
        "delivery_attempts": row.delivery_attempts,
        "dead_lettered_at": row.dead_lettered_at.isoformat(),
        "delivery_last_error": row.delivery_last_error,
        "created_at": row.created_at.isoformat(),
    }


def _write_json(value: dict[str, object]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _write_error(message: str) -> None:
    print(json.dumps({"error": message}, sort_keys=True), file=sys.stderr)


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a UUID") from exc


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _bounded_limit(value: str) -> int:
    parsed = _non_negative_integer(value)
    if not 1 <= parsed <= FLOW_AUDIT_OUTBOX_OPERATOR_LIST_MAX:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {FLOW_AUDIT_OUTBOX_OPERATOR_LIST_MAX}"
        )
    return parsed


def _non_negative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _bounded_reason(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > FLOW_AUDIT_OUTBOX_OPERATOR_REASON_MAX:
        raise argparse.ArgumentTypeError(
            f"must be between 1 and {FLOW_AUDIT_OUTBOX_OPERATOR_REASON_MAX} characters"
        )
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
