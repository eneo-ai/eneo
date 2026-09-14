"""The review reads runs of the published definition, not of a version number.

`publish_flow` allocates a new version on every publish, identical definition
or not, so an unpublish followed by an unchanged publish used to leave the
review with no runs and every earlier finding stale. The cohort, the finding
ids and a pinned investigation are all keyed by the definition checksum; a
changed definition still excludes the old runs and refuses the old references.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowRuns
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.ai_builder import ai_builder_flow_review as review_module
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_flow_review import (
    AIBuilderSuggestionContext,
    FlowReviewSuggestionFocus,
    resolve_suggestion_evidence,
)
from eneo.flows.domain.flow import FlowStep


def _step(*, flow_id: UUID, tenant_id: UUID, assistant_id: UUID, text: str) -> FlowStep:
    return FlowStep(
        id=None,
        flow_id=flow_id,
        tenant_id=tenant_id,
        assistant_id=assistant_id,
        step_order=1,
        user_description=text,
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )


async def _completed_run(
    session: AsyncSession,
    *,
    flow_id: UUID,
    flow_version: int,
    admin_user,
    created_at: datetime,
) -> UUID:
    # Explicit timestamps: the server default is the transaction's clock, so
    # rows of one transaction would tie and the window order would be random.
    run = FlowRuns(
        flow_id=flow_id,
        flow_version=flow_version,
        principal_type="user",
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        status="completed",
        evidence_classification_level=0,
        input_payload_json={"text": "in"},
        output_payload_json={"text": "out"},
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(run)
    await session.flush()
    return run.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_identical_republish_keeps_the_cohort_and_a_changed_one_excludes_it(
    db_container, admin_user, object_content_runtime_ready, monkeypatch
) -> None:
    async with db_container() as container:
        session = container.session()
        space = Spaces(
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            name=f"review-cohort-{uuid4().hex}",
        )
        session.add(space)
        await session.flush()
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space.id, name="Review cohort", description=None, steps=[]
        )
        assert flow.id is not None
        flow_id = flow.id
        assistant, _ = await flow_service.create_flow_assistant(
            flow_id=flow_id, name="Review cohort assistant"
        )
        step = dict(
            flow_id=flow_id, tenant_id=admin_user.tenant_id, assistant_id=assistant.id
        )
        await flow_service.update_flow(
            flow_id=flow_id, steps=[_step(**step, text="Summarise the input")]
        )
        await flow_service.publish_flow(flow_id=flow_id)
        now = datetime.now(timezone.utc)
        run_id = await _completed_run(
            session,
            flow_id=flow_id,
            flow_version=1,
            admin_user=admin_user,
            created_at=now - timedelta(minutes=1),
        )
        review = container.ai_builder_flow_review_service()
        first = await review.build_packet(flow_id=flow_id, space_id=space.id)
        assert first.flow_version == 1
        assert first.cohort.completed_run_ids == [run_id]

        # Unpublish and publish again without any change: a new version
        # number, the same definition, the same review.
        await flow_service.unpublish_flow(flow_id=flow_id)
        await flow_service.publish_flow(flow_id=flow_id)
        again = await review.build_packet(flow_id=flow_id, space_id=space.id)
        assert again.flow_version == 2
        assert again.definition_checksum == first.definition_checksum
        assert again.cohort.completed_run_ids == [run_id]
        assert again.cohort.omitted.other_version == 0
        assert [f.finding_id for f in again.facts] == [
            f.finding_id for f in first.facts
        ]

        # An investigation of a suggestion judged before the republish still
        # resolves, and its pinned run is read as a run of this definition
        # even once a newer run has pushed it out of the cohort window.
        newer_run_id = await _completed_run(
            session,
            flow_id=flow_id,
            flow_version=2,
            admin_user=admin_user,
            created_at=now,
        )
        monkeypatch.setattr(review_module, "COHORT_SCAN_LIMIT", 1)
        windowed = await review.build_packet(flow_id=flow_id, space_id=space.id)
        assert windowed.cohort.completed_run_ids == [newer_run_id]
        context = AIBuilderSuggestionContext(
            flow_version=first.flow_version,
            definition_checksum=first.definition_checksum,
            sample_run_ids=[run_id],
            suggestions=[
                FlowReviewSuggestionFocus(
                    suggestion_kind="instruction_outcome_drift", step_orders=[1]
                )
            ],
        )
        levels = await review.resolve_sample_run_levels(
            flow_id=flow_id,
            run_ids=[run_id],
            definition_checksum=windowed.definition_checksum,
        )
        assert levels == {run_id: 0}
        evidence = resolve_suggestion_evidence(
            windowed, context, sample_run_levels=levels
        )
        assert evidence.flow_version == 2
        assert [focus.step_orders for focus in evidence.suggestions] == [[1]]

        # A changed definition is another flow to the review: the old runs are
        # counted, not read, and the old references are refused explicitly.
        monkeypatch.setattr(review_module, "COHORT_SCAN_LIMIT", 100)
        await flow_service.unpublish_flow(flow_id=flow_id)
        await flow_service.update_flow(
            flow_id=flow_id, steps=[_step(**step, text="Translate the input")]
        )
        await flow_service.publish_flow(flow_id=flow_id)
        changed = await review.build_packet(flow_id=flow_id, space_id=space.id)
        assert changed.flow_version == 3
        assert changed.definition_checksum != first.definition_checksum
        assert changed.cohort.completed_run_ids == []
        assert changed.cohort.omitted.other_version == 2
        with pytest.raises(AIBuilderBadRequestException) as stale_reference:
            resolve_suggestion_evidence(changed, context, sample_run_levels=levels)
        assert stale_reference.value.code == AIBuilderErrorCode.REVIEW_STALE
        with pytest.raises(AIBuilderBadRequestException) as stale_run:
            await review.resolve_sample_run_levels(
                flow_id=flow_id,
                run_ids=[run_id],
                definition_checksum=changed.definition_checksum,
            )
        assert stale_run.value.code == AIBuilderErrorCode.REVIEW_STALE
        assert stale_run.value.context == {"run_version": 1}
        await session.rollback()
