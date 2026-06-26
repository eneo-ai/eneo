from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from intric.flows.flow_authoring_spec import FlowDraftSpecCore, OutputType
from intric.flows.step_lineage import existing_step_order_from_ref

FlowAuthoringTargetKind = Literal["create", "edit"]

_STRICT_TERMINAL_OUTPUT_TYPES = frozenset(
    {OutputType.JSON, OutputType.PDF, OutputType.DOCX}
)


@dataclass(frozen=True, slots=True)
class FlowAuthoringPreparationError:
    step_ref: str | None
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class FlowAuthoringPreparationResult:
    errors: tuple[FlowAuthoringPreparationError, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_prepared_flow_authoring_spec(
    *,
    spec: FlowDraftSpecCore,
    target_kind: FlowAuthoringTargetKind,
    valid_existing_step_refs: Iterable[str] | None,
    terminal_output_type: OutputType | None = None,
) -> FlowAuthoringPreparationResult:
    errors: list[FlowAuthoringPreparationError] = []
    _validate_existing_step_refs(
        spec=spec,
        target_kind=target_kind,
        valid_existing_step_refs=valid_existing_step_refs,
        errors=errors,
    )
    _add_terminal_output_alignment_error(
        spec=spec,
        terminal_output_type=terminal_output_type,
        errors=errors,
    )
    return FlowAuthoringPreparationResult(errors=tuple(errors))


def _validate_existing_step_refs(
    *,
    spec: FlowDraftSpecCore,
    target_kind: FlowAuthoringTargetKind,
    valid_existing_step_refs: Iterable[str] | None,
    errors: list[FlowAuthoringPreparationError],
) -> None:
    valid_ref_set = (
        frozenset(valid_existing_step_refs)
        if valid_existing_step_refs is not None
        else None
    )
    seen_existing_refs: set[str] = set()

    for step in spec.steps:
        existing_step_ref = step.existing_step_ref
        if existing_step_ref is None:
            continue

        if target_kind == "create":
            errors.append(
                FlowAuthoringPreparationError(
                    step_ref=step.plan_step_ref,
                    code="invalid_existing_step_ref",
                    message=(
                        f"Step '{step.plan_step_ref}' cannot set existing_step_ref "
                        f"'{existing_step_ref}' in create mode."
                    ),
                )
            )
            continue

        if existing_step_order_from_ref(existing_step_ref) is None:
            errors.append(
                FlowAuthoringPreparationError(
                    step_ref=step.plan_step_ref,
                    code="invalid_existing_step_ref",
                    message=(
                        f"Step '{step.plan_step_ref}' uses invalid existing_step_ref "
                        f"'{existing_step_ref}'. Expected the server alias format "
                        f"'existing_step_N'."
                    ),
                )
            )
            continue

        if valid_ref_set is not None and existing_step_ref not in valid_ref_set:
            errors.append(
                FlowAuthoringPreparationError(
                    step_ref=step.plan_step_ref,
                    code="invalid_existing_step_ref",
                    message=(
                        f"Step '{step.plan_step_ref}' references unknown "
                        f"existing_step_ref '{existing_step_ref}'. Valid refs: "
                        f"{sorted(valid_ref_set)}"
                    ),
                )
            )
            continue

        if existing_step_ref in seen_existing_refs:
            errors.append(
                FlowAuthoringPreparationError(
                    step_ref=step.plan_step_ref,
                    code="invalid_existing_step_ref",
                    message=(
                        f"Step '{step.plan_step_ref}' reuses existing_step_ref "
                        f"'{existing_step_ref}'. Each existing step can only be "
                        "targeted once."
                    ),
                )
            )
            continue

        seen_existing_refs.add(existing_step_ref)


def _add_terminal_output_alignment_error(
    *,
    spec: FlowDraftSpecCore,
    terminal_output_type: OutputType | None,
    errors: list[FlowAuthoringPreparationError],
) -> None:
    if (
        terminal_output_type is None
        or terminal_output_type not in _STRICT_TERMINAL_OUTPUT_TYPES
        or not spec.steps
    ):
        return

    terminal_step = spec.steps[-1]
    if terminal_step.output_type == terminal_output_type:
        return

    errors.append(
        FlowAuthoringPreparationError(
            step_ref=terminal_step.plan_step_ref,
            code="terminal_output_type_mismatch",
            message=(
                "The final step output_type must match the requested terminal output "
                f"'{terminal_output_type.value}', but the compiled plan ends with "
                f"'{terminal_step.output_type.value}'. Update the final step instead of "
                "adding or preserving a trailing text step."
            ),
        )
    )


__all__ = [
    "FlowAuthoringPreparationError",
    "FlowAuthoringPreparationResult",
    "FlowAuthoringTargetKind",
    "validate_prepared_flow_authoring_spec",
]
