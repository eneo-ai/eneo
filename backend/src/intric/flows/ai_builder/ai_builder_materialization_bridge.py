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
  Drift between envelope and commit (primary runtime input, terminal
  output, unsupported output_mode) and semantic errors surfaced by the
  create-draft validator (``first_step_invalid_source``,
  ``file_flow_input_requires_runtime_upload``, form-field reference
  errors, etc.) are hard ``MaterializationError``s — the commit plus
  the existing create-path contract are both authoritative. After
  compile, the bridge also runs the proposal-processor's compiled-spec
  acceptance gate (``prepare_compiled_spec_for_session`` →
  ``validate_spec``) so duplicate step names, chaining-rule violations,
  and other hard errors block materialization instead of silently
  producing a spec the write surface would reject.

  This seam is create-only. Edit-mode materialization (carrying a
  ``current_flow`` through) will add an explicit ``target_kind`` /
  ``current_flow`` entry point alongside edit-specific validation.

- ``apply_to_draft(*, repo, session_id, tenant_id, materialized,
  plan_rationale, ...)`` is the write path. It wraps the materialized
  spec in a ``PlannerPlanEnvelope`` (the post-acceptance shape the
  ``builder_plans`` row stores) and delegates persistence to
  ``AIBuilderRepository.create_plan``. The helper is deliberately
  thin: no retry policy, no catalog resolution, no conversation-turn
  composition. Callers orchestrate those; the bridge owns only the
  create-path shape translation and the persistence call.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_draft_mechanics,
)
from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_create_validator import validate_create_draft
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    PlannerPlanEnvelope,
)
from intric.flows.ai_builder.ai_builder_draft_plan import DraftPlanEnvelope
from intric.flows.ai_builder.ai_builder_materializer import compile_changeset
from intric.flows.ai_builder.ai_builder_models import (
    FlowChangeSet,
    FlowDraftSpecCore,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.planning_state import ArchitectureCommit


class MaterializationError(ValueError):
    """Raised when the draft envelope cannot be materialized against the commit.

    Distinct from generic ``ValueError`` so callers can differentiate
    bridge-detected drift (step-count mismatch, per-step tuple divergence,
    envelope-shape hallucination, unsupported commit output_mode, or
    semantic rejection from ``validate_create_draft``) from unrelated
    value errors raised by downstream compilers.
    """


@dataclass(frozen=True, slots=True)
class MaterializedDraft:
    """Bridge output: the canonical spec plus its compiled changeset.

    Callers that only need the spec (e.g. to render a preview) can ignore
    ``changeset``; callers that intend to apply the draft get the
    already-compiled changeset so execution skips re-compilation.

    ``plan_rationale`` rides with the materialized output so the write
    path cannot persist a rationale that drifted from what was validated
    during ``materialize()``. Without this, a caller could validate one
    rationale through the bridge's semantic gate and then hand a
    different string to ``apply_to_draft`` — the two would diverge
    silently. Pinning the validated value to the dataclass collapses
    the API to one source of truth.
    """

    spec: FlowDraftSpecCore
    changeset: FlowChangeSet
    plan_rationale: str


# Output modes the create-draft compile path cannot realise. Orchestrator
# v2's StepTriple accepts a broader set (e.g. ``http_post``) because the
# planner emits it, but the create compiler has no branch to produce
# those modes from (input_type, output_type, document_delivery_mode).
# Rejecting them up-front gives a clear error instead of a confusing
# "post-compile output_mode mismatch" message.
_CREATE_UNSUPPORTED_OUTPUT_MODES: frozenset[str] = frozenset({"http_post"})


def materialize(
    *,
    architecture_commit: ArchitectureCommit,
    draft_plan: DraftPlanEnvelope,
    flow_name: str,
    flow_description: str | None = None,
    plan_rationale: str,
) -> MaterializedDraft:
    """Translate an orchestrator v2 planner output into flows-domain types.

    The architecture commit is a capability envelope: it pins the
    primary runtime input and terminal output contract, not the exact
    implementation step count. ``output_mode`` is derived by the create
    compiler from per-step fields; the post-compile envelope check
    enforces that terminal delivery still honors the committed
    architecture while allowing intermediate extraction/review steps.

    The create-draft validator (``validate_create_draft``) is the same
    gate the existing proposal-processor path runs before compile —
    invoked here so semantic errors (``first_step_invalid_source``,
    ``file_flow_input_requires_runtime_upload``, duplicate form fields,
    out-of-range ``uses_previous_fields``, and the rest) surface
    consistently regardless of which caller reaches the compile path.
    """
    _validate_commit_supports_create_materialization(architecture_commit)
    _require_explicit_tuple_axes_per_envelope_step(draft_plan)

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
            f"Draft envelope failed strict structural validation: {exc}"
        ) from exc

    draft = normalize_create_draft_mechanics(draft)
    _run_create_draft_semantic_validator(draft)
    _validate_pre_compile_tuples(architecture_commit, draft)

    spec = compile_create_draft(draft)

    _validate_compiled_spec_matches_architecture_envelope(architecture_commit, spec)
    prepared_spec = _run_compiled_spec_validator(spec)

    changeset = compile_changeset(prepared_spec, None)
    return MaterializedDraft(
        spec=prepared_spec,
        changeset=changeset,
        plan_rationale=plan_rationale,
    )


def _validate_commit_supports_create_materialization(
    commit: ArchitectureCommit,
) -> None:
    for index, triple in enumerate(commit.tuples_chain):
        if triple.output_mode in _CREATE_UNSUPPORTED_OUTPUT_MODES:
            raise MaterializationError(
                f"architecture_commit.tuples_chain[{index}].output_mode "
                f"{triple.output_mode!r} is unsupported by the create "
                "materializer. The upstream planner contract should "
                "reject this commit before reaching the bridge."
            )


_REQUIRED_ENVELOPE_STEP_TUPLE_KEYS: frozenset[str] = frozenset(
    {"input_type", "output_type"}
)


def _require_explicit_tuple_axes_per_envelope_step(
    envelope: DraftPlanEnvelope,
) -> None:
    """Force the envelope to declare every tuple axis explicitly.

    ``NewStepDraft`` defaults ``input_type`` / ``output_type`` to
    ``text``. Without this check, a plan could silently rely on those
    defaults and hide what capabilities it actually asks the Flow
    compiler to build. Requiring explicit keys keeps the capability
    envelope check meaningful without forcing an exact step-count match.
    """
    for index, step_dict in enumerate(envelope.steps):
        missing = _REQUIRED_ENVELOPE_STEP_TUPLE_KEYS - step_dict.keys()
        if missing:
            raise MaterializationError(
                f"draft_plan.steps[{index}] is missing required tuple "
                f"axes: {sorted(missing)}. The envelope must declare the "
                "same (input_type, output_type) as the architecture commit."
            )


def _validate_pre_compile_tuples(
    commit: ArchitectureCommit,
    draft: FlowCreateDraft,
) -> None:
    if not commit.tuples_chain:
        raise MaterializationError(
            "architecture_commit.tuples_chain must contain at least one "
            "architecture envelope tuple"
        )

    primary_input_type = commit.tuples_chain[0].input_type
    if primary_input_type == "any":
        return

    has_primary_input = any(
        step.input_source.value == "flow_input"
        and step.input_type.value == primary_input_type
        for step in draft.steps
    )
    if has_primary_input:
        return

    actual_flow_inputs = [
        step.input_type.value
        for step in draft.steps
        if step.input_source.value == "flow_input"
    ]
    raise MaterializationError(
        "draft_plan does not contain a flow_input step matching "
        f"architecture primary input_type {primary_input_type!r}; "
        f"actual flow_input input_type values: {actual_flow_inputs}"
    )


def _run_create_draft_semantic_validator(draft: FlowCreateDraft) -> None:
    result = validate_create_draft(draft)
    if result.valid:
        return
    rendered = "; ".join(
        f"{error.code} at {error.step_ref or 'draft'}: {error.message}"
        for error in result.errors
    )
    raise MaterializationError(
        f"Draft envelope failed create-draft semantic validation: {rendered}"
    )


def _validate_compiled_spec_matches_architecture_envelope(
    commit: ArchitectureCommit,
    spec: FlowDraftSpecCore,
) -> None:
    if not commit.tuples_chain:
        raise MaterializationError(
            "architecture_commit.tuples_chain must contain at least one "
            "architecture envelope tuple"
        )
    if not spec.steps:
        raise MaterializationError("compiled spec has no steps")

    terminal = commit.tuples_chain[-1]
    terminal_step = spec.steps[-1]
    if terminal_step.output_type.value != terminal.output_type:
        raise MaterializationError(
            "terminal output_type "
            f"{terminal_step.output_type.value!r} does not match architecture "
            f"terminal output_type {terminal.output_type!r}"
        )

    if terminal.output_mode == "transcribe_only":
        if _has_audio_transcription_step(spec):
            return
        raise MaterializationError(
            "architecture terminal output_mode 'transcribe_only' requires at "
            "least one compiled audio transcription step"
        )

    if terminal_step.output_mode.value != terminal.output_mode:
        raise MaterializationError(
            "terminal output_mode "
            f"{terminal_step.output_mode.value!r} does not match architecture "
            f"terminal output_mode {terminal.output_mode!r}"
        )


def _has_audio_transcription_step(spec: FlowDraftSpecCore) -> bool:
    return any(
        step.input_source.value == "flow_input"
        and step.input_type.value == "audio"
        and step.output_type.value == "text"
        and step.output_mode.value == "transcribe_only"
        for step in spec.steps
    )


def _run_compiled_spec_validator(spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
    """Mirror the create-path compiled-spec acceptance gate.

    The proposal processor runs ``prepare_compiled_spec_for_session``
    after ``compile_create_draft`` so the hard ``validate_spec`` checks
    (duplicate step names, chaining rules, type compatibility, enum
    guards, contract parity) block malformed plans before they reach
    the write surface. The bridge must preserve that contract — without
    it, a spec with e.g. ``["Same", "same"]`` step names materializes
    into a changeset that would be rejected the moment the proposal
    processor tries to accept it.

    The preparer also runs two normalizations
    (``normalize_compiled_spec_for_session``,
    ``normalize_ai_builder_spec``); the prepared spec, not the raw
    compiler output, is what we emit so the downstream ``compile_changeset``
    and any caller-side rendering sees the canonical shape.

    Resource / model / knowledge-base refs stay ``None`` at this seam:
    the bridge is a pure translator. Callers that need catalog
    resolution must run it upstream or downstream; baking it in here
    would force the bridge to carry context it has no business knowing
    about.

    Scope note: this mirrors structural, semantic, and hard
    compiled-spec validation — not the proposal processor's
    quality-retry policy (the retryable-warning filter in
    ``_format_quality_feedback``). Quality retry is a policy concern
    that needs caller context (retry budgets, conversation history,
    which warnings are retryable) and is a caller responsibility when
    exact acceptance parity is required.
    """
    prepared = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        valid_existing_step_refs=None,
    )
    # resource_catalog=None guarantees the preparer never takes the
    # ``failure_feedback`` branch, which is the only path that returns
    # spec=None / validation=None. Raising ``MaterializationError`` (not
    # ``assert``) so the invariant survives ``python -O`` and the check
    # remains a runtime contract at the module boundary.
    if prepared.spec is None or prepared.validation is None:
        raise MaterializationError(
            "prepare_compiled_spec_for_session returned an incomplete "
            "result (spec or validation missing). The bridge invokes it "
            "with resource_catalog=None, which should never trigger the "
            "failure_feedback branch — a refactor has widened the failure "
            "surface without updating the bridge's contract."
        )
    if not prepared.validation.valid:
        rendered = "; ".join(
            f"{error.code} at {error.step_ref or 'spec'}: {error.message}"
            for error in prepared.validation.errors
        )
        raise MaterializationError(
            f"Compiled spec failed create-path validation: {rendered}"
        )
    return prepared.spec


async def apply_to_draft(
    *,
    repo: AIBuilderRepository,
    session_id: UUID,
    tenant_id: UUID,
    materialized: MaterializedDraft,
    assumptions: list[str] | None = None,
    risk_acknowledgments: list[str] | None = None,
    reasoning: str | None = None,
) -> BuilderPlan:
    """Persist a ``MaterializedDraft`` as a ``builder_plans`` row.

    Thin async wrapper over ``AIBuilderRepository.create_plan`` that
    constructs the ``PlannerPlanEnvelope`` the repo expects. The
    envelope carries the spec plus the post-acceptance metadata a
    builder session needs to render the plan card (assumptions,
    risk acknowledgments, reasoning, plan_rationale).

    ``plan_rationale`` rides on the ``MaterializedDraft`` rather than
    accepting a separate kwarg so it cannot drift from the value
    ``materialize()`` validated. ``lint_warnings`` is left to the
    envelope's default factory because the bridge has no consumer
    plumbed yet — adding it speculatively would create dead API
    surface.

    Lists are copied defensively — a caller that recycles its
    assumptions / risk buffer across turns must not retroactively
    mutate what was persisted.

    Edit-mode materialization (``edit_result_json``) is intentionally
    not forwarded: this translator is create-only, and ``create_plan``'s
    edit parameter is for the proposal-processor's edit adapter.
    """
    envelope = PlannerPlanEnvelope(
        spec=materialized.spec,
        assumptions=list(assumptions) if assumptions is not None else [],
        risk_acknowledgments=(
            list(risk_acknowledgments) if risk_acknowledgments is not None else []
        ),
        reasoning=reasoning,
        plan_rationale=materialized.plan_rationale,
    )
    return await repo.create_plan(
        session_id=session_id,
        tenant_id=tenant_id,
        spec=materialized.spec,
        envelope=envelope,
    )


__all__: list[str] = [
    "MaterializationError",
    "MaterializedDraft",
    "apply_to_draft",
    "materialize",
]
