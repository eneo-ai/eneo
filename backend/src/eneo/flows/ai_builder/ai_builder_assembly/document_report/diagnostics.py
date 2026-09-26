from __future__ import annotations

from typing import NoReturn

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.flow_authoring_spec import InputType, OutputMode, OutputType

DOCUMENT_REPORT_COMPOSE_TOPOLOGY_MISSING_FEEDBACK = (
    "Document report flows with a committed report disposition must end with "
    "a deterministic compose_text body writer before the renderer."
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
        repair_disposition="server_defect",
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


raise_document_report_compose_topology_missing = (
    _raise_document_report_compose_topology_missing
)
