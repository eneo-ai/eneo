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
from tests.integration.flows.test_transcript_corrections import (
    SEGMENTS,
    _create_scenario,
    _store_segments,
)

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
    flow_run_repo = FlowRunRepository(session=session)
    return FlowTranscriptWordsService(
        user=user,
        transcript_words_repo=FlowTranscriptWordsRepository(session=session),
        access_policy=FlowRunAccessPolicy(
            user=user,
            flow_repo=FlowRepository(session=session),
            flow_run_repo=flow_run_repo,
        ),
        flow_run_repo=flow_run_repo,
    )


async def test_words_round_trip_and_replace_on_retry(
    session,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
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

    view = await _service(session=session, user=admin_user).get_for_step(
        flow_id=scenario.flow_id,
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
    )

    assert view.stale is False
    assert view.words.words_json == WORDS
    assert view.words.alignment == "provider_words"


async def test_words_go_stale_when_the_segments_change(
    session,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
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

    view = await _service(session=session, user=admin_user).get_for_step(
        flow_id=scenario.flow_id,
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
    )

    assert view.stale is True


async def test_missing_words_are_not_found(
    session,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    scenario = await _create_scenario(
        session=session,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )

    with pytest.raises(NotFoundException):
        await _service(session=session, user=admin_user).get_for_step(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
        )


async def test_words_are_invisible_across_tenants(
    session,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
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
