"""The graph's step annotation read never selects step content."""

from uuid import uuid4

from eneo.database.tables.flow_tables import FlowStepResults
from eneo.flows.infrastructure.flow_run_repo import step_result_annotation_select

_CONTENT_COLUMNS = {
    "input_payload_json",
    "output_payload_json",
    "effective_prompt",
    "model_parameters_json",
}


def test_step_result_annotation_select_projects_status_facts_only() -> None:
    stmt = step_result_annotation_select(run_id=uuid4(), tenant_id=uuid4())

    selected = {column.name for column in stmt.selected_columns}

    assert selected == {
        "step_id",
        "step_order",
        "status",
        "num_tokens_input",
        "num_tokens_output",
        "error_message",
    }
    assert selected.isdisjoint(_CONTENT_COLUMNS)
    assert _CONTENT_COLUMNS <= set(FlowStepResults.__table__.columns.keys())
