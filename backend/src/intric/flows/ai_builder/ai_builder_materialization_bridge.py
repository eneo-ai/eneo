"""Materialization Bridge — single seam between AI Builder and the
flows-domain write surface.

This module is the **only** place inside ``intric.flows.ai_builder``
that is permitted to import from the ``intric.flows.api`` package — its
DTOs (``flow_models``), assemblers (``flow_assembler``), and routers
(``flow_router``). Every other AI Builder module must route write-surface
type usage through this bridge so the plugin package stays independent
of the flows-domain topology as DTOs, assemblers, and routers evolve.

The boundary is enforced by ``TestRule6MaterializationBridgeAcl`` in
``tests/unittests/flows/ai_builder/test_ai_builder_importlinter_rules.py``,
which scans the plugin package for any module importing from
``intric.flows.api.*`` and fails if anything other than this bridge
appears in the offender set.

Call surface:

- ``materialize(*, architecture_commit, draft_plan, flow_name, ...)``
  is pure — takes the orchestrator v2 planner output (an immutable
  ``ArchitectureCommit`` + the strict-envelope ``DraftPlanEnvelope``)
  and produces a ``MaterializedDraft`` carrying the canonical
  ``FlowDraftSpecCore`` plus the already-compiled ``FlowChangeSet``.
  Drift between envelope and commit (mismatched step count or tuple
  at any index) is a hard ``MaterializationError`` — the commit is
  authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_materializer import compile_changeset
from intric.flows.ai_builder.ai_builder_models import FlowChangeSet, FlowDraftSpecCore
from intric.flows.ai_builder.ai_builder_orchestrator import DraftPlanEnvelope
from intric.flows.ai_builder.planning_state import ArchitectureCommit
from intric.flows.domain.flow import Flow


class MaterializationError(ValueError):
    """Raised when the draft envelope cannot be materialized against the commit.

    Distinct from generic ``ValueError`` so callers can differentiate
    bridge-detected drift (step-count mismatch, per-step tuple divergence,
    envelope-shape hallucination) from unrelated value errors raised by
    downstream compilers.
    """


@dataclass(frozen=True, slots=True)
class MaterializedDraft:
    """Bridge output: the canonical spec plus its compiled changeset.

    Callers that only need the spec (e.g. to render a preview) can ignore
    ``changeset``; callers that intend to apply the draft get the
    already-compiled changeset so execution skips re-compilation.
    """

    spec: FlowDraftSpecCore
    changeset: FlowChangeSet


def materialize(
    *,
    architecture_commit: ArchitectureCommit,
    draft_plan: DraftPlanEnvelope,
    flow_name: str,
    flow_description: str | None = None,
    plan_rationale: str,
    current_flow: Flow | None = None,
) -> MaterializedDraft:
    """Translate an orchestrator v2 planner output into flows-domain types.

    The architecture commit is authoritative: the envelope must carry
    exactly as many steps as ``tuples_chain`` and each step's declared
    ``input_type`` / ``output_type`` must match the commit's tuple at
    that index. ``output_mode`` is derived by the create compiler from
    per-step fields; the post-compile check enforces that derivation
    lands on the commit's expected mode.
    """
    _validate_step_count(architecture_commit, draft_plan)

    try:
        draft = FlowCreateDraft.model_validate(
            {
                "flow_name": flow_name,
                "flow_description": flow_description,
                "plan_rationale": plan_rationale,
                "assumptions": [],
                "form_fields": list(draft_plan.form_fields),
                "steps": list(draft_plan.steps),
            }
        )
    except ValidationError as exc:
        raise MaterializationError(
            f"Draft envelope failed strict validation: {exc}"
        ) from exc

    _validate_pre_compile_tuples(architecture_commit, draft)

    spec = compile_create_draft(draft)

    _validate_post_compile_output_modes(architecture_commit, spec)

    changeset = compile_changeset(spec, current_flow)
    return MaterializedDraft(spec=spec, changeset=changeset)


def _validate_step_count(
    commit: ArchitectureCommit,
    envelope: DraftPlanEnvelope,
) -> None:
    expected = len(commit.tuples_chain)
    actual = len(envelope.steps)
    if expected != actual:
        raise MaterializationError(
            f"draft_plan step count {actual} does not match "
            f"architecture_commit.tuples_chain length {expected}"
        )


def _validate_pre_compile_tuples(
    commit: ArchitectureCommit,
    draft: FlowCreateDraft,
) -> None:
    for index, (triple, step) in enumerate(zip(commit.tuples_chain, draft.steps)):
        if step.input_type.value != triple.input_type:
            raise MaterializationError(
                _tuple_mismatch_message(
                    index=index,
                    axis="input_type",
                    expected=triple.input_type,
                    actual=step.input_type.value,
                )
            )
        if step.output_type.value != triple.output_type:
            raise MaterializationError(
                _tuple_mismatch_message(
                    index=index,
                    axis="output_type",
                    expected=triple.output_type,
                    actual=step.output_type.value,
                )
            )


def _validate_post_compile_output_modes(
    commit: ArchitectureCommit,
    spec: FlowDraftSpecCore,
) -> None:
    for index, (triple, step) in enumerate(zip(commit.tuples_chain, spec.steps)):
        if step.output_mode.value != triple.output_mode:
            raise MaterializationError(
                _tuple_mismatch_message(
                    index=index,
                    axis="output_mode",
                    expected=triple.output_mode,
                    actual=step.output_mode.value,
                )
            )


def _tuple_mismatch_message(
    *,
    index: int,
    axis: str,
    expected: str,
    actual: str,
) -> str:
    return (
        f"step[{index}] {axis} {actual!r} does not match "
        f"architecture_commit.tuples_chain[{index}].{axis} {expected!r}"
    )


__all__: list[str] = [
    "MaterializationError",
    "MaterializedDraft",
    "materialize",
]
