"""The graph poll reads a run's speaker-label setting as one key of its input
payload, never the payload itself. Only a JSON boolean is a choice: Postgres
hands the key back as JSON, so a string, a number and a null must stay
distinct from true and false once decoded (`True == 1` in Python)."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.flow_tables import FlowRuns
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.flow_run_input_envelope import SPEAKER_LABELS_KEY
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from tests.integration.flows.test_flow_runtime_health import (
    _create_published_flow,
    _create_run,
)

_LARGE_TRANSCRIPT = "Talare 1: Det här är en rad i ett mötestranskript.\n" * 40_000


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("payload", "raw", "choice"),
    [
        (sa.null(), None, None),
        (sa.JSON.NULL, None, None),
        ({"input": "value"}, None, None),
        ({SPEAKER_LABELS_KEY: None}, None, None),
        ({SPEAKER_LABELS_KEY: "true"}, "true", None),
        ({SPEAKER_LABELS_KEY: 1}, 1, None),
        ({SPEAKER_LABELS_KEY: 0}, 0, None),
        ({SPEAKER_LABELS_KEY: True}, True, True),
        ({SPEAKER_LABELS_KEY: False}, False, False),
        (
            {
                "transkribering": {
                    "kind": "inline_transcript",
                    "text": _LARGE_TRANSCRIPT,
                },
                SPEAKER_LABELS_KEY: True,
            },
            True,
            True,
        ),
    ],
    ids=[
        "sql_null",
        "json_null",
        "missing",
        "key_null",
        "string",
        "one",
        "zero",
        "true",
        "false",
        "large_transcript",
    ],
)
async def test_the_projection_reads_only_a_boolean_as_the_choice(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    payload,
    raw,
    choice,
):
    async with db_container() as container:
        session = container.session()
        flow = await _create_published_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        repo = FlowRunRepository(session=session)
        run = await _create_run(
            run_repo=repo, flow=flow, admin_user=admin_user, case="speaker-labels"
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(input_payload_json=payload)
        )

        # What the driver decodes the indexed expression to, before the
        # repository reads a choice from it.
        decoded = await session.scalar(
            sa.select(FlowRuns.input_payload_json[SPEAKER_LABELS_KEY]).where(
                FlowRuns.id == run.id
            )
        )
        assert decoded == raw
        assert type(decoded) is type(raw)

        snapshot, speaker_labels = await repo.get_status_with_speaker_labels(
            run_id=run.id, tenant_id=admin_user.tenant_id, flow_id=flow.id
        )

        assert speaker_labels is choice
        assert snapshot == await repo.get_status(
            run_id=run.id, tenant_id=admin_user.tenant_id, flow_id=flow.id
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_projection_keeps_the_tenant_and_flow_filters(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        flow = await _create_published_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        repo = FlowRunRepository(session=session)
        run = await _create_run(
            run_repo=repo, flow=flow, admin_user=admin_user, case="filters"
        )

        for tenant_id, flow_id in (
            (uuid4(), flow.id),
            (uuid4(), None),
            (admin_user.tenant_id, uuid4()),
        ):
            with pytest.raises(FlowRunNotFoundError):
                await repo.get_status_with_speaker_labels(
                    run_id=run.id, tenant_id=tenant_id, flow_id=flow_id
                )
        snapshot, speaker_labels = await repo.get_status_with_speaker_labels(
            run_id=run.id, tenant_id=admin_user.tenant_id
        )
        assert snapshot.id == run.id
        assert speaker_labels is None
