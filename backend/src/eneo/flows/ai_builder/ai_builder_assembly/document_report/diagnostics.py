from __future__ import annotations

from dataclasses import replace
from typing import NoReturn

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_assembly.plan import PlannedStep
from eneo.flows.ai_builder.ai_builder_domain_models import LintWarning
from eneo.flows.flow_authoring_spec import InputType, OutputMode, OutputType

DOCUMENT_REPORT_COMPOSE_TOPOLOGY_MISSING_FEEDBACK = (
    "Document report flows with a committed report disposition must end with "
    "a deterministic compose_text body writer before the renderer."
)


def _degrade_document_report_citations(
    planned_steps: tuple[PlannedStep, ...],
    *,
    field_diagnostics: list[LintWarning] | None,
    ui_language: str | None,
) -> tuple[PlannedStep, ...]:
    if any(step.citations_requested for step in planned_steps):
        planned_steps = tuple(
            replace(step, citations_requested=False) for step in planned_steps
        )
        if field_diagnostics is not None:
            field_diagnostics.append(
                LintWarning(
                    code="document_report_citations_downgraded",
                    message=(
                        "The report will not include source citations."
                        if ui_language == "en"
                        else "Rapporten kommer inte att innehålla källhänvisningar."
                    ),
                )
            )
    return planned_steps


def _append_combined_model_selection_diagnostics(
    combined_producer_model_refs: list[str],
    *,
    field_diagnostics: list[LintWarning] | None,
    ui_language: str | None,
) -> None:
    if field_diagnostics is not None:
        for model_ref in combined_producer_model_refs:
            field_diagnostics.append(
                LintWarning(
                    code="document_report_model_selection_combined",
                    message=(
                        "The steps specified different model selections; they were "
                        "combined and the combined report-writing step uses model "
                        "selection "
                        f"{model_ref}."
                        if ui_language == "en"
                        else "Stegen angav olika modellval; de kombinerades och "
                        "det kombinerade rapportskrivningssteget använder modellvalet "
                        f"{model_ref}."
                    ),
                )
            )


def _raise_document_report_compose_topology_missing(
    *,
    runtime_input_type: InputType,
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    pattern_ids: tuple[str, ...],
    chain_steps: tuple[str, ...],
    semantic_step_count: int,
) -> NoReturn:
    raise AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail=DOCUMENT_REPORT_COMPOSE_TOPOLOGY_MISSING_FEEDBACK,
        log_context={
            "failure_code": "assembly_document_report_compose_topology_missing",
            "reason": "document_report_compose_topology_missing",
            "runtime_input_type": runtime_input_type.value,
            "final_output_type": final_output_type.value,
            "final_output_mode": (
                final_output_mode.value if final_output_mode is not None else None
            ),
            "pattern_ids": ",".join(pattern_ids),
            "chain_steps": ",".join(chain_steps),
            "semantic_step_count": semantic_step_count,
        },
    )


append_combined_model_selection_diagnostics = (
    _append_combined_model_selection_diagnostics
)
degrade_document_report_citations = _degrade_document_report_citations
raise_document_report_compose_topology_missing = (
    _raise_document_report_compose_topology_missing
)
