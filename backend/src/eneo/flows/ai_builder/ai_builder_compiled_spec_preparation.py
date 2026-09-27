from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import partial

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import EditMutationScope
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_NAMES,
    BoundedListing,
    CorrectableFailure,
    display_value,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AIBuilderResourceCatalogEntry,
    AIBuilderResourceResolutionIssue,
    ResourceKind,
    canonicalize_flow_spec_resources,
    resource_label,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    disambiguate_ai_builder_step_names,
    normalize_ai_builder_spec,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputType,
)

_STRICT_EDIT_TERMINAL_OUTPUT_TYPES = frozenset(
    {OutputType.JSON, OutputType.PDF, OutputType.DOCX}
)


@dataclass(frozen=True)
class PreparedCompiledSpecResult:
    spec: FlowDraftSpecCore | None
    validation: SpecValidationResult | None
    failure_feedback: str | None = None


def prepare_compiled_spec_for_session(
    *,
    spec: FlowDraftSpecCore,
    target_kind: TargetKind,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None,
    terminal_output_type: OutputType | None = None,
    ui_language: str | None = None,
    mutation_scope: EditMutationScope | None = None,
) -> PreparedCompiledSpecResult:
    prepared_spec = spec
    if target_kind == TargetKind.EDIT:
        prepared_spec, _normalization_changes = normalize_ai_builder_spec(
            spec,
            terminal_output_type=terminal_output_type,
            disambiguate_duplicate_step_names=True,
            ui_language=ui_language,
        )
    else:
        prepared_spec, _normalization_changes = disambiguate_ai_builder_step_names(spec)
    if resource_catalog is not None:
        prepared_spec, resolution_issues = canonicalize_flow_spec_resources(
            prepared_spec,
            catalog=resource_catalog,
        )
        if resolution_issues:
            return PreparedCompiledSpecResult(
                spec=None,
                validation=None,
                failure_feedback=format_resource_resolution_feedback(resolution_issues),
            )
    if mutation_scope is not None:
        prepared_spec = mutation_scope.restore(prepared_spec)

    validation = validate_spec(
        prepared_spec,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
    )
    _enforce_terminal_output_alignment(
        validation=validation,
        spec=prepared_spec,
        terminal_output_type=terminal_output_type,
        target_kind=target_kind,
    )
    return PreparedCompiledSpecResult(spec=prepared_spec, validation=validation)


def authored_knowledge_ref_repair(
    catalog: AIBuilderResourceCatalog,
    refs_by_step: Iterable[tuple[str, Sequence[str]]],
) -> CorrectableFailure | None:
    """The repair for authored knowledge refs the catalog cannot resolve.

    Run before compile, for create and edit alike: the portable spec refuses a
    local id (an attachment's file id, say) as an invariant, which no model
    repair could then reach. `refs_by_step` pairs a step label with its refs.
    """

    # Identity only, and only the lines shown: an issue formats when the
    # listing keeps it, and the valid refs are listed once from the catalog.
    listing = BoundedListing()
    codes: set[str] = set()
    for step_label, refs in refs_by_step:
        for index, ref in enumerate(refs):
            matches = catalog.alias_matches(kind="knowledge_base", value=ref)
            if len(matches) == 1:
                continue
            codes.add("ambiguous_kb_ref" if matches else "unknown_kb_ref")
            listing.add(
                partial(
                    _reference_line,
                    kind="knowledge_base",
                    value=ref,
                    location=f"{step_label} knowledge_refs[{index}]",
                    matches=matches,
                )
            )
    if not listing.total:
        return None
    valid = BoundedListing()
    for entry in catalog.knowledge_bases:
        valid.add(partial(_option_label, entry))
    return CorrectableFailure(
        feedback="\n".join(
            (
                listing.render(_REPAIR_HEADING),
                valid.render(f"Valid knowledge base refs ({valid.total}):"),
            )
        ),
        kind="validation",
        codes=frozenset(codes),
    )


def format_resource_resolution_feedback(
    issues: Sequence[AIBuilderResourceResolutionIssue],
) -> str:
    """Bounded repair text: the first issues, then each kind's valid refs once."""

    listing = BoundedListing()
    for issue in issues:
        listing.add(
            partial(
                _reference_line,
                kind=issue.kind,
                value=issue.provided_value,
                location=issue.location,
                matches=(
                    issue.valid_options if issue.code.startswith("ambiguous_") else ()
                ),
            )
        )
    parts = [listing.render(_REPAIR_HEADING)]
    unknown_options: dict[ResourceKind, tuple[str, ...]] = {
        issue.kind: issue.valid_options
        for issue in issues
        if issue.code.startswith("unknown_")
    }
    for kind, options in unknown_options.items():
        valid = BoundedListing()
        for option in options:
            valid.add(partial(display_value, option))
        parts.append(
            valid.render(f"Valid {resource_label(kind)} refs ({valid.total}):")
        )
    return "\n".join(parts)


_REPAIR_HEADING = "Replace or remove these resource references:"


def _option_label(entry: AIBuilderResourceCatalogEntry) -> str:
    return display_value(entry.option_label)


def _reference_line(
    *,
    kind: ResourceKind,
    value: str,
    location: str,
    matches: Sequence[str | AIBuilderResourceCatalogEntry],
) -> str:
    """One unresolved reference; `matches` are an ambiguous ref's candidates."""

    label = resource_label(kind)
    shown = display_value(value)
    if not matches:
        return f"Unknown {label} reference '{shown}' at {location}."
    names = ", ".join(
        display_value(match) if isinstance(match, str) else _option_label(match)
        for match in matches[:MAX_DIAGNOSTIC_NAMES]
    )
    more = len(matches) - MAX_DIAGNOSTIC_NAMES
    return (
        f"Ambiguous {label} reference '{shown}' at {location}. "
        f"Matching options: {names}{f' and {more} more' if more > 0 else ''}."
    )


def _enforce_terminal_output_alignment(
    *,
    validation: SpecValidationResult,
    spec: FlowDraftSpecCore,
    terminal_output_type: OutputType | None,
    target_kind: TargetKind,
) -> None:
    if (
        terminal_output_type is None
        or not spec.steps
        or (
            target_kind == TargetKind.EDIT
            and terminal_output_type not in _STRICT_EDIT_TERMINAL_OUTPUT_TYPES
        )
    ):
        return

    terminal_step = spec.steps[-1]
    if terminal_step.output_type == terminal_output_type:
        return

    if target_kind == TargetKind.CREATE:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            repair_disposition="server_defect",
            detail=(
                "The create compiler produced a terminal output type that does "
                "not match the committed architecture."
            ),
            log_context={
                "failure_code": "terminal_output_type_mismatch",
                "reason": "terminal_output_type_mismatch",
                "expected_output_type": terminal_output_type.value,
                "actual_output_type": terminal_step.output_type.value,
                "step_ref": terminal_step.plan_step_ref,
            },
        )

    message = (
        "The final step output_type must match the requested terminal output "
        f"'{terminal_output_type.value}', but the compiled plan ends with "
        f"'{terminal_step.output_type.value}'. Update the final step instead of "
        "adding or preserving a trailing text step."
    )
    validation.add_error(
        step_ref=terminal_step.plan_step_ref,
        code="terminal_output_type_mismatch",
        message=message,
    )
