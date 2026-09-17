"""Read-only model capacity evidence for a trusted deployment shell.

Usage:
    uv run python -m eneo.cli.model_capacity_readiness report [--tenant-id UUID] [--format json|text]

Stored values are declarations, not verification. Exit codes: 0 for all uses
usable, 1 for unusable uses, 2 for usage errors, 3 for an
incomplete report, including invalid settings. Only database reads are
performed; no providers are contacted, and the LiteLLM model catalogue is always
read from the installed package.
Application modules load inside the protected run, so a startup failure exits 3
without printing settings values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Literal, NotRequired, Protocol, TypedDict
from uuid import UUID

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.completion_models.domain.model_capacity import (
        CapacityAvailability,
        CapacityDimension,
    )
    from eneo.flows.domain.flow import FlowRunStatusSnapshot, FlowSparse, FlowVersion
    from eneo.spaces.space import Space
    from eneo.tenants.tenant import TenantInDB

UseKind = Literal["builder", "published_flow", "resumable_run"]


class ReadinessSource(Protocol):
    def tenants(self, tenant_id: UUID | None) -> AsyncIterator[TenantInDB]: ...
    def published_flows(self, owner: TenantInDB) -> AsyncIterator[FlowSparse]: ...
    def runs_for_tenant(
        self, owner: TenantInDB
    ) -> AsyncIterator[FlowRunStatusSnapshot]: ...
    async def get_version(
        self, owner: TenantInDB, flow_id: UUID, number: int
    ) -> FlowVersion: ...
    async def assistant_model(
        self, owner: TenantInDB, assistant_id: UUID
    ) -> CompletionModel: ...
    def builder_spaces(self, owner: TenantInDB) -> AsyncIterator[Space]: ...
    async def active_provider_ids(self, owner: TenantInDB) -> set[UUID]: ...


class Use(TypedDict):
    count: int
    ids: NotRequired[list[str]]


class ModelReadiness(TypedDict):
    model_id: str
    name: str
    provider_id: str | None
    provider_type: str | None
    route: str
    stored: dict[CapacityDimension, int | None]
    uses: dict[str, Use]
    availability: dict[str, CapacityAvailability]
    missing_dimensions: list[CapacityDimension]
    verification: str


class DisabledUse(TypedDict):
    model_id: str
    uses: list[str]


class Summary(TypedDict):
    usable_models: int
    unusable_models: int
    disabled_uses: list[DisabledUse]


class TenantReadiness(TypedDict):
    tenant_id: str
    models: list[ModelReadiness]
    summary: Summary


def add_use(
    records: dict[UUID, ModelReadiness],
    seen: set[tuple[UUID, UseKind, UUID]],
    model: CompletionModel,
    use: UseKind,
    identity: UUID,
    *,
    safety_tokens: int = 0,
) -> None:
    identity_key = (model.id, use, identity)
    if identity_key in seen:
        return
    seen.add(identity_key)
    if model.id not in records:
        records[model.id] = {
            "model_id": str(model.id),
            "name": model.name,
            "provider_id": str(model.provider_id) if model.provider_id else None,
            "provider_type": model.provider_type,
            "route": model.get_model_route(),
            "stored": {
                "max_input_tokens": model.max_input_tokens,
                "max_output_tokens": model.max_output_tokens,
            },
            "uses": {},
            "availability": {},
            "missing_dimensions": list(model.capacity.missing_dimensions()),
            "verification": "unverified",
        }
    record = records[model.id]
    usage = record["uses"].setdefault(use, {"count": 0, "ids": []})
    usage.setdefault("ids", []).append(str(identity))
    usage["count"] += 1
    record["availability"][use] = model.capacity.availability(
        safety_tokens=safety_tokens
    )


async def report_tenant(source: ReadinessSource, owner: TenantInDB) -> TenantReadiness:
    from eneo.flows.ai_builder.ai_builder_context import eligible_planner_models
    from eneo.flows.ai_builder.ai_builder_settings import (
        resolve_ai_builder_budget_policy,
    )
    from eneo.flows.enums import (
        flow_output_mode_uses_completion_model,
        is_terminal_flow_run_status,
    )
    from eneo.flows.published_definition import parse_verified_published_definition

    records: dict[UUID, ModelReadiness] = {}
    seen: set[tuple[UUID, UseKind, UUID]] = set()
    safety = resolve_ai_builder_budget_policy(
        owner.flow_settings
    ).conversation_safety_buffer_tokens
    active = await source.active_provider_ids(owner)
    async for space in source.builder_spaces(owner):
        if space.id is None or space.tenant_id != owner.id:
            raise ValueError("Invalid space ownership")
        for model in eligible_planner_models(space, active_provider_ids=active):
            add_use(records, seen, model, "builder", space.id, safety_tokens=safety)

    async def add_version(
        flow_id: UUID, number: int, use: UseKind, identity: UUID
    ) -> None:
        version = await source.get_version(owner, flow_id, number)
        if version.tenant_id != owner.id:
            raise ValueError("Invalid version ownership")
        definition = parse_verified_published_definition(
            version.definition_json,
            expected_flow_id=flow_id,
            expected_checksum=version.definition_checksum,
            flow_version=version.version,
        )
        assistant_ids = {
            step.assistant_id
            for step in definition.runtime_steps()
            if flow_output_mode_uses_completion_model(step.output_mode)
        }
        for assistant_id in sorted(assistant_ids):
            # A completion step runs its assistant's model; one that resolves to
            # none leaves the report incomplete rather than silently shorter.
            model = await source.assistant_model(owner, assistant_id)
            if model.tenant_id not in (None, owner.id):
                raise ValueError("Invalid model ownership")
            add_use(records, seen, model, use, identity)

    async for flow in source.published_flows(owner):
        if flow.tenant_id != owner.id:
            raise ValueError("Invalid flow ownership")
        if flow.published_version is not None:
            flow_id = flow.require_persisted_id()
            await add_version(
                flow_id, flow.published_version, "published_flow", flow_id
            )
    async for run in source.runs_for_tenant(owner):
        if run.tenant_id != owner.id:
            raise ValueError("Invalid run ownership")
        if not is_terminal_flow_run_status(run.status):
            await add_version(run.flow_id, run.flow_version, "resumable_run", run.id)
    models = sorted(records.values(), key=lambda item: item["model_id"])
    disabled: list[DisabledUse] = []
    for record in models:
        for usage in record["uses"].values():
            usage.get("ids", []).sort()
        if "builder" in record["uses"]:
            del record["uses"]["builder"]["ids"]
        unusable_uses = [
            use
            for use, availability in record["availability"].items()
            if availability != "ready"
        ]
        if unusable_uses:
            disabled.append({"model_id": record["model_id"], "uses": unusable_uses})
    return {
        "tenant_id": str(owner.id),
        "models": models,
        "summary": {
            "usable_models": len(models) - len(disabled),
            "unusable_models": len(disabled),
            "disabled_uses": disabled,
        },
    }


EXIT_OK = 0
EXIT_MISSING = 1
EXIT_USAGE = 2
EXIT_FAILURE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eneo-model-capacity-readiness")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser(
        "report", help="report stored and missing model capacity"
    )
    report.add_argument("--tenant-id", type=UUID)
    report.add_argument("--format", choices=("json", "text"), default="json")
    return parser


async def run_report(
    source: ReadinessSource, *, tenant_id: UUID | None, output_format: str
) -> int:
    missing = False
    count = 0
    # Buffer output on disk so an incomplete scan cannot look like a successful
    # empty report, without retaining every tenant's report in memory.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        if output_format == "json":
            output.write('{"tenants":[')
        async for owner in source.tenants(tenant_id):
            result = await report_tenant(source, owner)
            missing |= bool(result["summary"]["unusable_models"])
            if output_format == "json":
                if count:
                    output.write(",")
                json.dump(result, output, sort_keys=True)
            else:
                output.write(format_text(result))
            count += 1
        if tenant_id is not None and count == 0:
            print(json.dumps({"error": "tenant not found"}), file=sys.stderr)
            return EXIT_USAGE
        if output_format == "json":
            output.write("]}\n")
        output.seek(0)
        shutil.copyfileobj(output, sys.stdout)
    return EXIT_MISSING if missing else EXIT_OK


def format_text(report: TenantReadiness) -> str:
    summary = report["summary"]
    lines = [
        f"Tenant {report['tenant_id']}",
        f"  Usable models: {summary['usable_models']}",
        f"  Unusable models: {summary['unusable_models']}",
    ]
    for record in report["models"]:
        lines.append(f"  Model {record['model_id']} {json.dumps(record['name'])}")
        lines.append(
            f"    Provider: {record['provider_id']} {json.dumps(record['provider_type'])}"
        )
        lines.append(f"    Route: {json.dumps(record['route'])}")
        lines.append(f"    Stored: {json.dumps(record['stored'], sort_keys=True)}")
        lines.append("    Verification: unverified")
        lines.append(
            f"    Missing: {', '.join(record['missing_dimensions']) or 'none'}"
        )
        for use, usage in record["uses"].items():
            lines.append(
                f"    {use}: {usage['count']}"
                + (f" ids={','.join(usage['ids'])}" if "ids" in usage else "")
            )
            lines.append(f"      Availability: {record['availability'][use]}")
    for disabled in summary["disabled_uses"]:
        lines.append(
            f"  Would disable {disabled['model_id']}: {', '.join(disabled['uses'])}"
        )
    return "\n".join(lines) + "\n"


async def _run_database(args: argparse.Namespace) -> int:
    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return await _read_database(args)
    except (Exception, SystemExit):
        print(
            json.dumps({"error": "capacity readiness report failed"}), file=sys.stderr
        )
        return EXIT_FAILURE
    finally:
        logging.disable(previous_logging_disable)


async def _read_database(args: argparse.Namespace) -> int:
    from eneo.cli.model_capacity_readiness_repo import ModelCapacityReadinessRepository
    from eneo.database.database import sessionmanager
    from eneo.main.config import get_settings

    result = EXIT_FAILURE
    try:
        sessionmanager.init(get_settings().database_url)
        async with sessionmanager.session() as session, session.begin():
            await session.connection(
                execution_options={
                    "isolation_level": "REPEATABLE READ",
                    "postgresql_readonly": True,
                }
            )
            result = await run_report(
                ModelCapacityReadinessRepository(session),
                tenant_id=args.tenant_id,
                output_format=args.format,
            )
    except (Exception, SystemExit):
        result = EXIT_FAILURE
        print(
            json.dumps({"error": "capacity readiness report failed"}), file=sys.stderr
        )
    finally:
        try:
            await sessionmanager.close()
        except Exception:
            print(json.dumps({"error": "database cleanup failed"}), file=sys.stderr)
            result = EXIT_FAILURE
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Importing LiteLLM fetches its model catalogue over the network unless
    # told to use the packaged copy; this command promises no network access,
    # whatever the inherited environment says.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    try:
        return asyncio.run(_run_database(args))
    except KeyboardInterrupt:
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
