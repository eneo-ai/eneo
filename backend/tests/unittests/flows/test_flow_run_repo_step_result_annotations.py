"""The narrow step-result reads: the graph's annotations never select step
content, and finalization reads one output payload, the last completed."""

from unittest.mock import AsyncMock, MagicMock
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


def _sql(stmt) -> str:
    return " ".join(str(stmt.compile(dialect=postgresql.dialect())).split())


def test_step_result_annotation_select_projects_status_facts_only() -> None:
    """Finalization and the executor read statuses alone: no payload, no other
    table."""
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
    assert _CONTENT_COLUMNS <= set(FlowStepResults.__table__.columns.keys())
    sql = _sql(stmt)
    assert "input_payload_json" not in sql
    assert "JOIN" not in sql
    assert "flow_runs" not in sql


def test_the_graphs_annotations_read_why_the_live_text_was_not_used_alone() -> None:
    """The graph poll shows why a streamed step's audio goes to the transcription
    model as soon as the step's attempt decides it, before the step's status
    changes. Only a step the run's input says was streamed reads it, through
    one path in its result's and its current attempt's input: another step,
    and every step of a run without streamed audio, reads no payload."""
    run_id, tenant_id = uuid4(), uuid4()
    stmt = step_result_annotation_select(
        run_id=run_id, tenant_id=tenant_id, with_live_fallback_reasons=True
    )
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())

    assert {column.name for column in stmt.selected_columns} >= {
        "step_id",
        "live_fallback_reason",
    }
    assert (
        "LEFT OUTER JOIN flow_step_attempts"
        " ON flow_step_attempts.flow_run_id = flow_step_results.flow_run_id"
        " AND flow_step_attempts.step_id = flow_step_results.step_id"
        " AND flow_step_attempts.attempt_no = flow_step_results.current_attempt_no"
    ) in sql
    # The run's step facts come from this run alone, read once for the
    # statement rather than once per step.
    run_facts = sql[
        sql.index("(SELECT flow_runs.input_payload_json") : sql.index(
            ", CAST(flow_step_results.step_id AS TEXT)"
        )
    ]
    assert "FROM flow_runs WHERE flow_runs.id = " in run_facts
    assert "AND flow_runs.tenant_id = " in run_facts
    assert "flow_step_results" not in run_facts
    # A step's payloads appear only behind the streamed check, each through
    # one path; the payload columns themselves are never selected.
    guarded = sql[sql.index("CASE WHEN (jsonb_extract_path_text(") :]
    assert sql.count(".input_payload_json #>> ") == 2
    assert guarded.count(".input_payload_json #>> ") == 2
    assert "flow_step_results.input_payload_json," not in sql
    assert "flow_step_attempts.input_payload_json," not in sql
    assert {"step_inputs", "streamed"} <= set(compiled.params.values())
    paths = [value for value in compiled.params.values() if isinstance(value, tuple)]
    assert sorted(paths) == [
        ("live_fallback", "reason"),
        ("transcription", "live_fallback_reason"),
    ]
    assert run_id in compiled.params.values()
    assert tenant_id in compiled.params.values()


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


@pytest.mark.asyncio
async def test_live_fallbacks_are_read_for_the_streamed_steps_alone() -> None:
    """Only a streamed step can have one: a run without streamed audio reads
    nothing, and a streamed step's read selects the decision alone."""
    session = AsyncMock()
    repo = FlowRunRepository(session=session)
    run_id, tenant_id, step_id = uuid4(), uuid4(), uuid4()

    assert (
        await repo.list_current_attempt_live_fallbacks(
            run_id=run_id, tenant_id=tenant_id, step_ids=frozenset()
        )
        == {}
    )
    session.execute.assert_not_awaited()

    decision = f'{{"reason": "no_timing", "model_id": "{uuid4()}", "model_name": "KB-Whisper"}}'
    session.execute.return_value = MagicMock(all=lambda: [(step_id, decision)])
    fallbacks = await repo.list_current_attempt_live_fallbacks(
        run_id=run_id, tenant_id=tenant_id, step_ids=frozenset({step_id})
    )

    assert {key: value.reason for key, value in fallbacks.items()} == {
        step_id: "no_timing"
    }
    stmt = session.execute.await_args.args[0]
    sql = " ".join(str(stmt.compile(dialect=postgresql.dialect())).split())
    assert len(stmt.selected_columns) == 2
    assert "flow_step_results.step_id IN" in sql
    assert "flow_step_attempts.input_payload_json ->" in sql
    assert "flow_step_attempts.input_payload_json," not in sql
