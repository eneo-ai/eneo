from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows import FlowRepository
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_transcript_words_service import (
    FlowTranscriptWordsService,
)
from eneo.flows.domain.transcript_corrections import segments_content_hash
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_words_repo import (
    FlowTranscriptWordsRepository,
)
from eneo.main.exceptions import NotFoundException
from tests.integration.flows import transcript_source_support
from tests.integration.flows.statement_capture_support import capture_queries
from tests.integration.flows.test_transcript_corrections import (
    SEGMENTS,
    _create_scenario,
    _store_segments,
)

source_scenario = transcript_source_support.source_scenario

WORDS = [
    {
        "segment_index": 0,
        "words": [
            {"word": "Vi", "start": 0.1, "end": 0.3, "probability": 0.98},
            {"word": "frågade", "start": 0.35, "end": 0.9, "probability": 0.0},
        ],
    }
]


def _service(*, session, user) -> FlowTranscriptWordsService:
    from tests.integration.flows.test_transcript_source import (
        _service as source_service,
    )

    return FlowTranscriptWordsService(
        user=user,
        transcript_words_repo=FlowTranscriptWordsRepository(session=session),
        flow_run_repo=FlowRunRepository(session=session),
        transcript_source_service=source_service(session, user),
    )


async def _words_view(*, session, user, scenario):
    """The step's words for a run the caller authorized for content first."""
    run = await FlowRunAccessPolicy(
        user=user,
        flow_repo=FlowRepository(session=session),
        flow_run_repo=FlowRunRepository(session=session),
    ).load_run_status(
        run_id=scenario.flow_run_id, flow_id=scenario.flow_id, access_kind="content"
    )
    return await _service(session=session, user=user).get_for_step(
        run=run, step_id=scenario.transcription_step_id
    )


async def test_words_round_trip_and_replace_on_retry(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowTranscriptWordsRepository(session=session)
        first = await repo.upsert(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments_hash=segments_content_hash(SEGMENTS),
            alignment="forced",
            words_json=WORDS,
        )
        # An in-run retry re-transcribes: the row is replaced, never duplicated.
        second = await repo.upsert(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments_hash=segments_content_hash(SEGMENTS),
            alignment="provider_words",
            words_json=WORDS,
        )
        assert second.id == first.id
        assert second.alignment == "provider_words"

        view = await _words_view(session=session, user=admin_user, scenario=scenario)

        assert view.stale is False
        assert view.words.words_json == WORDS
        assert view.words.alignment == "provider_words"


async def test_words_go_stale_when_the_segments_change(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await FlowTranscriptWordsRepository(session=session).upsert(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments_hash=segments_content_hash(SEGMENTS),
            alignment="forced",
            words_json=WORDS,
        )
        await _store_segments(
            session=session,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments=[{**SEGMENTS[0], "text": "Vi frågade Çagri om planen."}],
        )

        view = await _words_view(session=session, user=admin_user, scenario=scenario)

        assert view.stale is True


async def test_missing_words_are_not_found(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )

        with pytest.raises(NotFoundException):
            await _words_view(session=session, user=admin_user, scenario=scenario)


async def test_words_are_invisible_across_tenants(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowTranscriptWordsRepository(session=session)
        await repo.upsert(
            tenant_id=scenario.tenant_id,
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments_hash=segments_content_hash(SEGMENTS),
            alignment="forced",
            words_json=WORDS,
        )

        same_tenant = await repo.get_for_step(
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            tenant_id=scenario.tenant_id,
        )
        other_tenant = await repo.get_for_step(
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            tenant_id=uuid4(),
        )

        assert same_tenant is not None
        assert other_tenant is None
        await repo.delete_for_step(
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            tenant_id=uuid4(),
        )
        assert (
            await repo.get_for_step(
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                tenant_id=scenario.tenant_id,
            )
            is not None
        )


async def test_words_route_authorizes_once_without_reading_run_content(
    client,
    db_container,
    patch_auth_service_jwt,
    source_scenario,
) -> None:
    import re

    import sqlalchemy as sa

    from eneo.audit.domain.action_types import ActionType
    from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
    from eneo.database.tables.flow_tables import FlowRuns, FlowStepResults
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.spaces.api.space_models import SpaceRoleValue
    from tests.integration.flows.test_transcript_source import _lines, _store

    session, scenario, user = source_scenario
    segments = _lines(3)
    source = await _store(session, scenario, user, segments)
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == scenario.flow_run_id)
        .values(output_payload_json={"text": "Protected transcript " * 500})
    )
    await session.execute(
        sa.update(FlowStepResults)
        .where(
            FlowStepResults.flow_run_id == scenario.flow_run_id,
            FlowStepResults.step_id == scenario.transcription_step_id,
        )
        .values(current_attempt_no=1)
    )
    await FlowTranscriptWordsRepository(session=session).upsert(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
        segments_hash=source.source_hash,
        alignment="forced",
        words_json=WORDS,
    )
    flow = await FlowRepository(session=session).get(scenario.flow_id, user.tenant_id)
    session.add(
        SpacesUsers(space_id=flow.space_id, user_id=user.id, role=SpaceRoleValue.EDITOR)
    )
    await session.commit()
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
    bind = session.sync_session.bind
    assert bind is not None
    with capture_queries(bind) as queries:
        response = await client.get(
            f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}"
            f"/steps/{scenario.transcription_step_id}/transcript-words/",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stale"] is False
    assert body["segments"] == [
        {
            "speaker_attribution": None,
            "overlap_ids": [],
            "segment_index": 0,
            "words": WORDS[0]["words"],
        }
    ]
    runs = [q.sql for q in queries if re.search(r"\bFROM flow_runs\b", q.sql)]
    assert len(runs) == 1, runs
    assert "input_payload_json" not in runs[0]
    assert "output_payload_json" not in runs[0]
    async with db_container() as container:
        audits = (
            await container.session().execute(
                sa.select(AuditLogTable.description, AuditLogTable.log_metadata).where(
                    AuditLogTable.action == ActionType.FLOW_EVIDENCE_VIEWED.value,
                    AuditLogTable.entity_id == scenario.flow_run_id,
                )
            )
        ).all()
    assert len(audits) == 1
    assert audits[0].description == (
        f"Viewed transcript words for flow run {scenario.flow_run_id}"
    )
    assert audits[0].log_metadata["target"] == {
        "id": str(scenario.flow_run_id),
        "name": None,
    }
    assert audits[0].log_metadata["extra"] == {
        "evidence_detail": "transcript_words",
        "step_id": str(scenario.transcription_step_id),
        "flow_id": str(scenario.flow_id),
        "run_id": str(scenario.flow_run_id),
    }
