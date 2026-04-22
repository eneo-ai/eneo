from __future__ import annotations

from typing import Literal, cast

DiscoveryFamily = Literal[
    "case_scope",
    "input_shape",
    "output_artifact",
    "output_style",
    "structured_reuse",
    "runtime_metadata",
]

QUESTION_FAMILY: dict[str, DiscoveryFamily] = {
    "comparison_scope_conflict": "case_scope",
    "case_scope": "case_scope",
    "comparison_scope": "case_scope",
    "input_material_mode": "input_shape",
    "flow_input_architecture": "input_shape",
    "document_kind": "input_shape",
    "document_material_scope": "input_shape",
    "final_output_mode": "output_artifact",
    "docx_output_mode": "output_artifact",
    "pdf_generation_mode": "output_artifact",
    "final_pdf_type": "output_style",
    "structured_analysis_need": "structured_reuse",
    "runtime_metadata_fields": "runtime_metadata",
    "output_reader": "output_style",
    "final_output_scope": "output_style",
}

ALL_DISCOVERY_FAMILIES: frozenset[DiscoveryFamily] = frozenset(QUESTION_FAMILY.values())


def family_for_issue(
    issue_id: str, *, default: DiscoveryFamily | None = None
) -> DiscoveryFamily | None:
    return cast(DiscoveryFamily | None, QUESTION_FAMILY.get(issue_id, default))
