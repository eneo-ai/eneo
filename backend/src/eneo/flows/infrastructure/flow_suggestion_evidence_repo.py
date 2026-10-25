"""Content-free run evidence for flow suggestions.

Reads what recent runs of one flow measured, tenant-scoped, as the domain's
``RunEvidence`` pieces: per step result, its status and failure code, its
current attempt's resolved input edges (binding, producer, selector, size,
hash) and that attempt's completion calls (reason, tokens, edge indexes,
mapped index). Never a prompt, an output or an input value: the edge
aggregate holds hashes and sizes only, and it is projected here before
anything leaves. A published version's steps leave as their
``StepDefinitionFacts`` (a hash, a model id, an output type), never as the
definition with its prompts.

The caller decides which runs the user may see evidence for: it lists the
candidates (``list_recent_runs``), filters them with the run access policy
and reads the evidence of the rest (``read_attempts``) in one statement.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import (
    FlowProviderCalls,
    FlowRuns,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
    FlowVersions,
)
from eneo.database.tables.users_table import Users
from eneo.flows.domain.flow import FlowRunStatusSnapshot
from eneo.flows.domain.flow_suggestion_evidence import (
    COUNTED_RUN_STATUSES,
    EvidenceAttempt,
    EvidenceCall,
    EvidenceEdge,
    StepDefinitionFacts,
    step_definition_facts,
)
from eneo.flows.domain.provider_call import ProviderCallKind
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputFlowInputSource,
    FlowResolvedInputHashedSelection,
    FlowResolvedInputRuntimeSource,
    FlowResolvedInputStepResultSource,
    parse_resolved_input_edges,
)

_RUN_STATUS_COLUMNS = tuple(
    getattr(FlowRuns, name) for name in FlowRunStatusSnapshot.model_fields
)


class FlowSuggestionEvidenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_recent_runs(
        self, *, flow_id: UUID, tenant_id: UUID, limit: int
    ) -> list[FlowRunStatusSnapshot]:
        """The flow's last ``limit`` finished runs (``COUNTED_RUN_STATUSES``)
        in which at least one step ran, newest first, as the status
        snapshots the run access policy judges."""
        if limit <= 0:
            return []
        step_ran = (
            sa.select(FlowStepAttempts.id)
            .where(FlowStepAttempts.flow_run_id == FlowRuns.id)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .exists()
        )
        stmt = (
            sa.select(*_RUN_STATUS_COLUMNS)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.status.in_(COUNTED_RUN_STATUSES))
            .where(step_ran)
            .order_by(FlowRuns.created_at.desc(), FlowRuns.id.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [FlowRunStatusSnapshot.model_validate(row) for row in rows]

    async def read_attempts(
        self, *, flow_id: UUID, run_ids: Sequence[UUID], tenant_id: UUID
    ) -> dict[UUID, tuple[EvidenceAttempt, ...]]:
        """The current attempt of every step result of ``run_ids``, by run,
        in step order: one statement. The completion calls of each attempt
        come aggregated in it, as plain numbers and reasons."""
        if not run_ids:
            return {}
        call = sa.func.jsonb_build_object(
            "status",
            FlowProviderCalls.status,
            "call_reason",
            FlowProviderCalls.call_reason,
            "num_tokens_input",
            FlowProviderCalls.num_tokens_input,
            "num_tokens_output",
            FlowProviderCalls.num_tokens_output,
            "edge_indexes",
            FlowProviderCalls.resolved_input_edge_indexes,
            "mapped_index",
            sa.func.coalesce(
                FlowProviderCalls.mapped_item_index,
                FlowProviderCalls.mapped_source_index,
            ),
        )
        calls = (
            sa.select(
                sa.func.coalesce(
                    sa.func.jsonb_agg(
                        aggregate_order_by(call, FlowProviderCalls.ordinal)
                    ),
                    sa.cast(sa.literal("[]"), JSONB),
                )
            )
            .where(FlowProviderCalls.flow_step_attempt_id == FlowStepAttempts.id)
            .where(FlowProviderCalls.call_kind == ProviderCallKind.COMPLETION.value)
            .correlate(FlowStepAttempts)
            .scalar_subquery()
        )
        stmt = (
            sa.select(
                FlowStepResults.flow_run_id,
                FlowStepResults.step_id,
                FlowStepResults.step_order,
                FlowStepResults.status,
                FlowStepResults.error_code,
                FlowStepAttemptResolvedInputs.resolved_input_edges_jsonb.label("edges"),
                calls.label("calls"),
            )
            .select_from(FlowStepResults)
            .outerjoin(
                FlowStepAttempts,
                sa.and_(
                    FlowStepAttempts.flow_run_id == FlowStepResults.flow_run_id,
                    FlowStepAttempts.flow_id == FlowStepResults.flow_id,
                    FlowStepAttempts.step_id == FlowStepResults.step_id,
                    FlowStepAttempts.attempt_no == FlowStepResults.current_attempt_no,
                    FlowStepAttempts.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                FlowStepAttemptResolvedInputs,
                FlowStepAttemptResolvedInputs.flow_step_attempt_id
                == FlowStepAttempts.id,
            )
            .where(FlowStepResults.flow_run_id.in_(tuple(run_ids)))
            .where(FlowStepResults.flow_id == flow_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .order_by(FlowStepResults.flow_run_id, FlowStepResults.step_order)
        )
        by_run: dict[UUID, list[EvidenceAttempt]] = {}
        for row in (await self.session.execute(stmt)).all():
            by_run.setdefault(row.flow_run_id, []).append(
                EvidenceAttempt(
                    step_id=row.step_id,
                    step_order=row.step_order,
                    status=row.status,
                    error_code=row.error_code,
                    edges=_edges(row.edges),
                    calls=_calls(row.calls),
                )
            )
        return {run_id: tuple(attempts) for run_id, attempts in by_run.items()}

    async def published_step_facts(
        self, *, flow_id: UUID, versions: Collection[int], tenant_id: UUID
    ) -> dict[tuple[int, UUID], StepDefinitionFacts]:
        """The facts of each step of each of the flow's ``versions``, by
        version and step id. The definitions are read here and only their
        facts leave."""
        if not versions:
            return {}
        rows = (
            await self.session.execute(
                sa.select(FlowVersions.version, FlowVersions.definition_json)
                .where(FlowVersions.flow_id == flow_id)
                .where(FlowVersions.tenant_id == tenant_id)
                .where(FlowVersions.version.in_(sorted(versions)))
            )
        ).all()
        facts: dict[tuple[int, UUID], StepDefinitionFacts] = {}
        for version, definition in rows:
            steps = _mapping(definition).get("steps")
            for item in cast(list[object], steps) if isinstance(steps, list) else []:
                parsed = _published_step(item)
                if parsed is not None:
                    facts[(version, parsed[0])] = parsed[1]
        return facts

    async def assistant_completion_models(
        self, *, assistant_ids: Collection[UUID], tenant_id: UUID
    ) -> dict[UUID, UUID | None]:
        """The completion model each assistant uses now, tenant-scoped."""
        if not assistant_ids:
            return {}
        rows = (
            await self.session.execute(
                sa.select(Assistants.id, Assistants.completion_model_id)
                .join(Users, Users.id == Assistants.user_id)
                .where(Assistants.id.in_(tuple(assistant_ids)))
                .where(Users.tenant_id == tenant_id)
            )
        ).all()
        return {row.id: row.completion_model_id for row in rows}

    async def model_input_limits(
        self, *, model_ids: Collection[UUID], tenant_id: UUID
    ) -> dict[UUID, int]:
        """The input token limit (``CompletionModel.token_limit``) of each
        model the tenant may use that the catalogue knows one for."""
        if not model_ids:
            return {}
        rows = (
            await self.session.execute(
                sa.select(CompletionModels.id, CompletionModels.max_input_tokens)
                .where(CompletionModels.id.in_(tuple(model_ids)))
                .where(CompletionModels.deleted_at.is_(None))
                .where(
                    sa.or_(
                        CompletionModels.tenant_id.is_(None),
                        CompletionModels.tenant_id == tenant_id,
                    )
                )
            )
        ).all()
        return {
            row.id: int(row.max_input_tokens)
            for row in rows
            if row.max_input_tokens is not None
        }


def _edges(raw: object) -> tuple[EvidenceEdge, ...]:
    """The attempt's edges without their values: an aggregate that is not
    tracked or cannot be read gives none."""
    parsed = parse_resolved_input_edges(raw)
    if parsed.aggregate is None:
        return ()
    edges: list[EvidenceEdge] = []
    for edge in parsed.aggregate.edges:
        source = edge.source
        selection = edge.selection
        hashed = isinstance(selection, FlowResolvedInputHashedSelection)
        selector = getattr(source, "selector", None)
        edges.append(
            EvidenceEdge(
                binding_ref=edge.binding_ref,
                source_step_id=(
                    source.source_step_id
                    if isinstance(source, FlowResolvedInputStepResultSource)
                    else None
                ),
                selector=(
                    tuple(str(segment) for segment in selector.path)
                    if selector is not None
                    else ()
                ),
                byte_size=selection.byte_size if hashed else None,
                sha256=selection.sha256 if hashed else None,
                run_input=isinstance(
                    source,
                    (FlowResolvedInputFlowInputSource, FlowResolvedInputRuntimeSource),
                ),
            )
        )
    return tuple(edges)


def _calls(raw: object) -> tuple[EvidenceCall, ...]:
    if not isinstance(raw, list):
        return ()
    calls: list[EvidenceCall] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            continue
        call = cast(dict[str, Any], item)
        calls.append(
            EvidenceCall(
                status=str(call.get("status")),
                call_reason=str(call.get("call_reason")),
                num_tokens_input=_int_or_none(call.get("num_tokens_input")),
                num_tokens_output=_int_or_none(call.get("num_tokens_output")),
                edge_indexes=tuple(
                    int(index)
                    for index in cast(list[object], call.get("edge_indexes") or [])
                    if isinstance(index, int)
                ),
                mapped_index=_int_or_none(call.get("mapped_index")),
            )
        )
    return tuple(calls)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _published_step(item: object) -> tuple[UUID, StepDefinitionFacts] | None:
    """A version's step as its id and facts; None for a step without a
    readable id."""
    if not isinstance(item, dict):
        return None
    step = cast(dict[str, Any], item)
    try:
        step_id = UUID(str(step.get("step_id")))
    except ValueError:
        return None
    snapshot = _mapping(step.get("assistant_snapshot"))
    model = _mapping(snapshot.get("completion_model"))
    try:
        model_id = UUID(str(model["model_id"])) if model.get("model_id") else None
    except ValueError:
        model_id = None
    instructions = snapshot.get("instructions")
    return step_id, step_definition_facts(
        input_source=str(step.get("input_source")),
        input_type=str(step.get("input_type")),
        input_contract=_mapping_or_none(step.get("input_contract")),
        input_bindings=_mapping_or_none(step.get("input_bindings")),
        input_config=_mapping_or_none(step.get("input_config")),
        output_mode=str(step.get("output_mode")),
        output_type=str(step.get("output_type")),
        output_contract=_mapping_or_none(step.get("output_contract")),
        output_config=_mapping_or_none(step.get("output_config")),
        prompt_text=instructions if isinstance(instructions, str) else None,
        completion_model_id=model_id,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, dict) else None


__all__ = ["FlowSuggestionEvidenceRepository"]
