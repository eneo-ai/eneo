"""The narrow step-result reads: the graph's annotations never select step
content, and finalization reads one output payload, the last completed."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.database.tables.flow_tables import FlowStepResults
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    step_result_annotation_select,
)

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


@pytest.mark.asyncio
async def test_last_completed_output_payload_selects_one_payload_of_one_run() -> None:
    session = AsyncMock()
    session.scalar.return_value = {"text": "final"}
    repo = FlowRunRepository(session=session)
    run_id, tenant_id = uuid4(), uuid4()

    payload = await repo.read_last_completed_output_payload(
        run_id=run_id, tenant_id=tenant_id
    )

    assert payload == {"text": "final"}
    session.scalar.assert_awaited_once()
    stmt = session.scalar.await_args.args[0]
    assert [column.name for column in stmt.selected_columns] == ["output_payload_json"]
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    assert "FROM flow_step_results" in sql
    assert "flow_step_results.flow_run_id = %(flow_run_id_1)s" in sql
    assert "flow_step_results.tenant_id = %(tenant_id_1)s" in sql
    assert "flow_step_results.status = %(status_1)s" in sql
    assert sql.endswith("ORDER BY flow_step_results.step_order DESC LIMIT %(param_1)s")
    assert compiled.params == {
        "flow_run_id_1": run_id,
        "tenant_id_1": tenant_id,
        "status_1": "completed",
        "param_1": 1,
    }


@pytest.mark.asyncio
async def test_last_completed_output_payload_is_none_when_no_step_completed() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    repo = FlowRunRepository(session=session)

    assert (
        await repo.read_last_completed_output_payload(run_id=uuid4(), tenant_id=uuid4())
        is None
    )
