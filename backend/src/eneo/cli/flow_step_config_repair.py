"""Operator cleanup of current Flow step rows, including published flows.

Published snapshots may still contain inactive credentials. This command does
not erase historical credentials. ENEO_OPERATOR_IDENTITY must be populated by
the trusted deployment wrapper when applying repairs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID

from eneo.flows.domain.flow_audit_outbox_limits import (
    FLOW_AUDIT_OUTBOX_OPERATOR_IDENTITY_MAX,
)


def _bounded_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= limit <= 1000:
        raise argparse.ArgumentTypeError("must be between 1 and 1000")
    return limit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eneo-flow-step-config-repair",
        description=(
            "Clean inactive config from current Flow rows. Published snapshots may "
            "still contain inactive credentials; historical credentials are not erased."
        ),
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--tenant", type=UUID)
    scope.add_argument("--all-tenants", action="store_true")
    parser.add_argument(
        "--apply", action="store_true", help="write repairs (default: dry run)"
    )
    parser.add_argument(
        "--limit",
        type=_bounded_limit,
        default=100,
        help="maximum flows to inspect (1-1000; default: 100)",
    )
    parser.add_argument(
        "--after",
        type=UUID,
        help="flow id continuation cursor from the previous report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run_database(args))
    except KeyboardInterrupt:
        _write_json({"outcome": "failed"})
        return 1


async def _run_database(args: argparse.Namespace) -> int:
    from eneo.database.database import sessionmanager
    from eneo.main.config import get_settings

    try:
        sessionmanager.init(get_settings().database_url)
        result = await _run_command(args)
    except (Exception, SystemExit):
        _write_json({"outcome": "failed"})
        result = 1
    finally:
        try:
            await sessionmanager.close()
        except Exception:
            _write_json({"outcome": "failed"})
            result = 1
    return result


async def _run_command(args: argparse.Namespace) -> int:
    from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
    from eneo.database.database import sessionmanager
    from eneo.flows.application.flow_step_config_repair import repair_flow_step_config
    from eneo.flows.infrastructure.flow_repo import FlowRepository

    operator_identity = " ".join(os.environ.get("ENEO_OPERATOR_IDENTITY", "").split())
    if (
        args.apply
        and not 1 <= len(operator_identity) <= FLOW_AUDIT_OUTBOX_OPERATOR_IDENTITY_MAX
    ):
        _write_json({"outcome": "failed"})
        return 1
    counts = dict.fromkeys(
        ("would_change", "unchanged", "repaired", "conflict", "invalid", "failed"), 0
    )
    after = args.after
    exhausted = False
    try:
        for _ in range(args.limit):
            async with sessionmanager.session() as session, session.begin():
                identity = await FlowRepository(session).next_step_config_repair_flow(
                    tenant_id=args.tenant, after=after
                )
            if identity is None:
                exhausted = True
                break
            tenant_id, flow_id = identity
            try:
                async with sessionmanager.session() as session:
                    outcome = await repair_flow_step_config(
                        flow_repo=FlowRepository(session),
                        audit_log_repo=AuditLogRepositoryImpl(session),
                        flow_id=flow_id,
                        tenant_id=tenant_id,
                        apply=args.apply,
                        operator_identity=operator_identity,
                    )
            except Exception:
                outcome = "failed"
            counts[outcome] += 1
            _write_json(
                {
                    "tenant_id": str(tenant_id),
                    "flow_id": str(flow_id),
                    "outcome": outcome,
                }
            )
            after = flow_id
        if not exhausted:
            async with sessionmanager.session() as session, session.begin():
                exhausted = (
                    await FlowRepository(session).next_step_config_repair_flow(
                        tenant_id=args.tenant, after=after
                    )
                    is None
                )
    except Exception:
        counts["failed"] += 1
        _write_json({"outcome": "failed"})
    _write_json(
        {
            "scope": "current_rows",
            "published_snapshots": "unchanged; may still contain inactive credentials",
            "counts": counts,
            "next_cursor": str(after) if after is not None and not exhausted else None,
        }
    )
    return 1 if counts["conflict"] or counts["invalid"] or counts["failed"] else 0


def _write_json(value: dict[str, object]) -> None:
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
