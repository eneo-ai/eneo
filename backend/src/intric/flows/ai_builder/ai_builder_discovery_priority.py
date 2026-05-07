from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryIssue

DISCOVERY_ISSUE_PRIORITY: dict[str, int] = {
    "comparison_scope_conflict": 0,
    "case_scope": 10,
    "input_material_mode": 20,
    "flow_input_architecture": 25,
    "final_output_mode": 30,
    "external_delivery_unsupported": 30,
    "document_kind": 40,
    "document_material_scope": 50,
    "comparison_scope": 60,
    "docx_output_mode": 70,
    "pdf_generation_mode": 72,
    "final_pdf_type": 75,
    "output_reader": 80,
    "final_output_scope": 90,
    "structured_analysis_need": 95,
    "runtime_metadata_fields": 100,
}


def sort_discovery_issues(issues: list[DiscoveryIssue]) -> list[DiscoveryIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.severity == "blocking" else 1,
            DISCOVERY_ISSUE_PRIORITY.get(issue.issue_id, 999),
        ),
    )
