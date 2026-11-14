"""Integration tests for hierarchical conversation history retention policies.

Tests cover:
- Hierarchical policy resolution (Assistant → Space → Tenant → None)
- Hard deletion of old questions and app runs
- Retention policy persistence and audit logging
- Multi-tenant isolation of retention policies
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.domain.retention import RetentionOverdue
from eneo.data_retention.domain.rules import RetentionRule, resolve_period
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository
from eneo.policy_levels import PolicyLevel
from tests.integration.data_retention.retention_support import (
    run_registered_retention,
    step_batches,
)


@pytest.fixture
async def test_space(
    retention_session: AsyncSession, test_tenant, admin_user
) -> Spaces:
    """Create a test space with no retention policy."""
    space = Spaces(
        name=f"Test Retention Space {admin_user.id}",
        description="Testing retention policies",
        tenant_id=test_tenant.id,
        user_id=admin_user.id,  # Personal space to avoid org space constraint
        tenant_space_id=None,
        data_retention_days=None,  # No space-level retention
    )
    retention_session.add(space)
    await retention_session.flush()
    return space


@pytest.fixture
async def test_assistant(
    retention_session: AsyncSession,
    test_space,
    test_tenant,
    admin_user,
    completion_model_factory,
) -> Assistants:
    """Create a test assistant with no retention policy."""
    completion_model = await completion_model_factory(retention_session, "gpt-4")

    assistant = Assistants(
        name="Test Assistant for Retention",
        description="Testing retention",
        user_id=admin_user.id,
        space_id=test_space.id,
        completion_model_id=completion_model.id,
        completion_model_kwargs={},
        logging_enabled=True,
        is_default=False,
        published=False,
        data_retention_days=None,  # No assistant-level retention
    )
    retention_session.add(assistant)
    await retention_session.flush()
    return assistant


@pytest.fixture
async def test_app(
    retention_session: AsyncSession,
    test_space,
    test_tenant,
    admin_user,
    completion_model_factory,
) -> Apps:
    """Create a test app with no retention policy."""
    completion_model = await completion_model_factory(
        retention_session, "gpt-4", nickname="retention-app-model"
    )

    app = Apps(
        name="Test App for Retention",
        description="Testing retention",
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
        space_id=test_space.id,
        completion_model_id=completion_model.id,
        completion_model_kwargs={},
        data_retention_days=None,  # No app-level retention
        published=False,
    )
    retention_session.add(app)
    await retention_session.flush()
    return app


async def create_old_question(
    retention_session: AsyncSession, assistant_id, tenant_id, user_id, days_old: int
) -> Questions:
    """Create a question with a specific age."""
    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)

    # Create session first (Sessions table doesn't have tenant_id)
    test_session = Sessions(
        user_id=user_id,
        name="Test Session",
        assistant_id=assistant_id,
        created_at=created_at,
        updated_at=created_at,
    )
    retention_session.add(test_session)
    await retention_session.flush()

    question = Questions(
        question="Test question",
        answer="Test answer",
        num_tokens_question=10,
        num_tokens_answer=20,
        tenant_id=tenant_id,
        assistant_id=assistant_id,
        session_id=test_session.id,
        created_at=created_at,
        updated_at=created_at,
    )
    retention_session.add(question)
    await retention_session.flush()
    return question


async def create_old_app_run(
    retention_session: AsyncSession,
    app_id,
    tenant_id,
    user_id,
    completion_model_id,
    days_old: int,
) -> AppRuns:
    """Create an app run with a specific age."""
    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)

    app_run = AppRuns(
        tenant_id=tenant_id,
        app_id=app_id,
        user_id=user_id,
        completion_model_id=completion_model_id,
        input_text="Test input",
        output_text="Test output",
        created_at=created_at,
        updated_at=created_at,
    )
    retention_session.add(app_run)
    await retention_session.flush()
    return app_run


@pytest.mark.asyncio
async def test_assistant_level_retention_deletes_old_questions(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that assistant-level retention policy deletes old questions."""
    # Set assistant retention to 30 days
    test_assistant.data_retention_days = 30
    retention_session.add(test_assistant)
    await retention_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one old (60 days), one recent (10 days)
    old_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=60
    )
    recent_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=10
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: old question deleted, recent kept
    assert deleted_count == 1

    old_exists = await retention_session.get(Questions, old_question.id)
    recent_exists = await retention_session.get(Questions, recent_question.id)

    assert old_exists is None, "Old question should be deleted"
    assert recent_exists is not None, "Recent question should be kept"


@pytest.mark.asyncio
async def test_space_level_retention_fallback(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that space-level retention applies when assistant has no policy."""
    # Set space retention to 90 days (assistant has None)
    test_space.data_retention_days = 90
    retention_session.add(test_space)
    await retention_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one old (120 days), one recent (60 days)
    old_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=120
    )
    recent_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=60
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: old question deleted, recent kept
    assert deleted_count == 1

    old_exists = await retention_session.get(Questions, old_question.id)
    recent_exists = await retention_session.get(Questions, recent_question.id)

    assert old_exists is None, "Question older than space retention should be deleted"
    assert recent_exists is not None, "Question within space retention should be kept"


@pytest.mark.asyncio
async def test_assistant_overrides_space_retention(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that assistant-level retention overrides space-level retention."""
    # Space: 90 days, Assistant: 30 days (more restrictive)
    test_space.data_retention_days = 90
    test_assistant.data_retention_days = 30
    retention_session.add(test_space)
    retention_session.add(test_assistant)
    await retention_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create question that's 60 days old (older than assistant, newer than space)
    question_60d = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=60
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: question deleted by assistant retention (30d), not space (90d)
    assert deleted_count == 1

    exists = await retention_session.get(Questions, question_60d.id)
    assert exists is None, (
        "Assistant retention (30d) should override space retention (90d)"
    )


@pytest.mark.asyncio
async def test_tenant_level_retention_fallback(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that tenant-level retention applies when space and assistant have no policy."""
    # Create tenant retention policy
    tenant_policy = AuditRetentionPolicy(
        tenant_id=test_tenant.id,
        retention_days=365,  # Audit logs
        conversation_retention_enabled=True,
        conversation_retention_days=180,  # Conversation retention
    )
    retention_session.add(tenant_policy)
    await retention_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one old (200 days), one recent (100 days)
    old_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=200
    )
    recent_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=100
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: old question deleted by tenant policy
    assert deleted_count == 1

    old_exists = await retention_session.get(Questions, old_question.id)
    recent_exists = await retention_session.get(Questions, recent_question.id)

    assert old_exists is None, "Question older than tenant retention should be deleted"
    assert recent_exists is not None, "Question within tenant retention should be kept"


# The organisation's conversation value: no row, or (switch on, days). The
# periods are organisation 30 < Assistant or App 60 < space 90, so an inner
# choice is longer than an outer one in some combinations and shorter in
# others, and a strictest-wins rule removes more than the nearest-wins rule.
_ORGANIZATION_STATES: dict[str, tuple[bool, int | None] | None] = {
    "no organisation row": None,
    "organisation off with days": (False, 30),
    "organisation on without days": (True, None),
    "organisation on with days": (True, 30),
}


def _expected_period(
    organization: tuple[bool, int | None] | None, space: int | None, own: int | None
) -> tuple[int | None, str | None]:
    """Today's conversation history rule, written out: the nearest chosen
    period wins, and the organisation's counts only while its switch is on."""
    if own is not None:
        return own, "assistant_or_app"
    if space is not None:
        return space, "space"
    if organization is not None and organization[0] and organization[1] is not None:
        return organization[1], "organization"
    return None, None


@pytest.mark.asyncio
async def test_every_combination_of_levels_selects_by_the_nearest_choice(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_app: Apps,
    test_tenant,
    admin_user,
):
    """Every combination of the three levels and the organisation switch,
    for questions and App runs: the nearest chosen period wins, a longer inner
    period overrides a shorter outer one, nothing is removed without a choice,
    and each removal is counted under the level that chose it. The SQL removes
    exactly what the kernel resolves, and both match today's rule written out.

    Mutants: the strictest period wins instead of the nearest; the switch is
    ignored; the space value is skipped when the owner has none; a removal is
    counted under another level; the SQL resolves the levels in another order
    than the rule declares."""
    ids = (test_space.id, test_assistant.id, test_app.id)
    space_id, assistant_id, app_id = ids
    tenant_id, user_id = test_tenant.id, admin_user.id
    completion_model_id = test_app.completion_model_id
    ages = (45, 75, 120)

    for state, organization in _ORGANIZATION_STATES.items():
        for space_days in (None, 90):
            for own_days in (None, 60):
                case = f"{state}, space {space_days}, own {own_days}"
                await retention_session.execute(
                    delete(AuditRetentionPolicy).where(
                        AuditRetentionPolicy.tenant_id == tenant_id
                    )
                )
                if organization is not None:
                    retention_session.add(
                        AuditRetentionPolicy(
                            tenant_id=tenant_id,
                            retention_days=365,
                            conversation_retention_enabled=organization[0],
                            conversation_retention_days=organization[1],
                        )
                    )
                await retention_session.execute(
                    update(Spaces)
                    .where(Spaces.id == space_id)
                    .values(data_retention_days=space_days)
                )
                for owner in (Assistants, Apps):
                    await retention_session.execute(
                        update(owner)
                        .where(owner.id.in_((assistant_id, app_id)))
                        .values(data_retention_days=own_days)
                    )
                questions = [
                    (
                        await create_old_question(
                            retention_session, assistant_id, tenant_id, user_id, age
                        )
                    ).id
                    for age in ages
                ]
                runs = [
                    (
                        await create_old_app_run(
                            retention_session,
                            app_id,
                            tenant_id,
                            user_id,
                            completion_model_id,
                            age,
                        )
                    ).id
                    for age in ages
                ]

                report = await run_registered_retention(retention_session)

                days, level = _expected_period(organization, space_days, own_days)
                resolved = resolve_period(
                    RetentionRule.CONVERSATION_HISTORY,
                    {
                        PolicyLevel.ORGANIZATION: organization[1]
                        if organization is not None and organization[0]
                        else None,
                        PolicyLevel.SPACE: space_days,
                        PolicyLevel.ASSISTANT_OR_APP: own_days,
                    },
                )
                assert (resolved.value, resolved.origin) == (days, level), case
                due = [days is not None and age > days for age in ages]
                removed_questions = [
                    await retention_session.get(Questions, question) is None
                    for question in questions
                ]
                removed_runs = [
                    await retention_session.get(AppRuns, run) is None for run in runs
                ]
                assert (removed_questions, removed_runs) == (due, due), case
                assert {
                    key: count
                    for key, count in report.counts.items()
                    if key.endswith("_rule") and count
                } == (
                    {
                        f"questions.by_{level}_rule": sum(due),
                        f"app_runs.by_{level}_rule": sum(due),
                    }
                    if any(due)
                    else {}
                ), case

                await retention_session.execute(
                    delete(Questions).where(Questions.assistant_id == assistant_id)
                )
                await retention_session.execute(
                    delete(Sessions).where(Sessions.assistant_id == assistant_id)
                )
                await retention_session.execute(
                    delete(AppRuns).where(AppRuns.app_id == app_id)
                )


@pytest.mark.asyncio
async def test_the_nightly_run_reads_due_ness_from_the_database_clock(
    monkeypatch: pytest.MonkeyPatch,
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Mutant: the nightly run takes its clock from the worker process, so a
    worker whose clock is behind the database keeps a conversation that is due."""
    from eneo.main import retention_tasks
    from eneo.main.config import get_settings
    from tests.integration.data_retention.retention_support import (
        run_nightly_retention,
    )

    class _WorkerClockBehind(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime(2000, 1, 1, tzinfo=timezone.utc)

    test_assistant.data_retention_days = 30
    question = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, 60
    )
    await retention_session.commit()
    monkeypatch.setattr(retention_tasks, "datetime", _WorkerClockBehind)

    await run_nightly_retention(monkeypatch, get_settings())

    retention_session.expunge_all()
    await retention_session.begin()
    assert await retention_session.get(Questions, question.id) is None


@pytest.mark.asyncio
async def test_no_retention_keeps_all_questions(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that questions are kept forever when no retention policy is set."""
    # No retention at any level

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create very old question (1000 days)
    old_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=1000
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: nothing deleted
    assert deleted_count == 0

    exists = await retention_session.get(Questions, old_question.id)
    assert exists is not None, "Question should be kept when no retention policy exists"


@pytest.mark.asyncio
async def test_app_level_retention_deletes_old_runs(
    retention_session: AsyncSession,
    test_app: Apps,
    test_tenant,
    admin_user,
):
    """Test that app-level retention policy deletes old app runs."""
    # Set app retention to 30 days
    test_app.data_retention_days = 30
    retention_session.add(test_app)
    await retention_session.flush()

    # Extract IDs
    app_id = test_app.id
    tenant_id = test_tenant.id
    user_id = admin_user.id
    completion_model_id = test_app.completion_model_id

    # Create app runs: one old (60 days), one recent (10 days)
    old_run = await create_old_app_run(
        retention_session, app_id, tenant_id, user_id, completion_model_id, days_old=60
    )
    recent_run = await create_old_app_run(
        retention_session, app_id, tenant_id, user_id, completion_model_id, days_old=10
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("app_runs.app_runs_deleted", 0)
    await retention_session.flush()

    # Verify: old run deleted, recent kept
    assert deleted_count == 1

    old_exists = await retention_session.get(AppRuns, old_run.id)
    recent_exists = await retention_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "Old app run should be deleted"
    assert recent_exists is not None, "Recent app run should be kept"


@pytest.mark.asyncio
async def test_space_level_app_retention_fallback(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_app: Apps,
    test_tenant,
    admin_user,
):
    """Test that space-level retention applies to apps without their own policy."""
    # Set space retention to 90 days (app has None)
    test_space.data_retention_days = 90
    retention_session.add(test_space)
    await retention_session.flush()

    # Extract IDs
    app_id = test_app.id
    tenant_id = test_tenant.id
    user_id = admin_user.id
    completion_model_id = test_app.completion_model_id

    # Create app runs: one old (120 days), one recent (60 days)
    old_run = await create_old_app_run(
        retention_session, app_id, tenant_id, user_id, completion_model_id, days_old=120
    )
    recent_run = await create_old_app_run(
        retention_session, app_id, tenant_id, user_id, completion_model_id, days_old=60
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("app_runs.app_runs_deleted", 0)
    await retention_session.flush()

    # Verify: old run deleted by space policy
    assert deleted_count == 1

    old_exists = await retention_session.get(AppRuns, old_run.id)
    recent_exists = await retention_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "App run older than space retention should be deleted"
    assert recent_exists is not None, "App run within space retention should be kept"


@pytest.mark.asyncio
async def test_space_conversation_and_app_retention_does_not_activate_flow_deletion(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_app: Apps,
    test_tenant,
    admin_user,
) -> None:
    anchor = datetime.now(timezone.utc)
    old = anchor - timedelta(days=60)
    test_space.data_retention_days = 30
    await retention_session.execute(
        update(Tenants)
        .where(Tenants.id == test_tenant.id)
        .values(
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
    )
    retention_session.add(test_space)

    assistant = Assistants(
        name="Space-independent retention assistant",
        description="Conversation retention remains Space-owned",
        user_id=admin_user.id,
        space_id=test_space.id,
        completion_model_id=test_app.completion_model_id,
        completion_model_kwargs={},
        logging_enabled=True,
        is_default=False,
        published=False,
        data_retention_days=None,
    )
    retention_session.add(assistant)
    await retention_session.flush()
    question = await create_old_question(
        retention_session,
        assistant.id,
        test_tenant.id,
        admin_user.id,
        days_old=60,
    )
    app_run = await create_old_app_run(
        retention_session,
        test_app.id,
        test_tenant.id,
        admin_user.id,
        test_app.completion_model_id,
        days_old=60,
    )
    flow = Flows(
        name=f"Flow without run-history retention {uuid4()}",
        description="Space retention remains independent",
        tenant_id=test_tenant.id,
        space_id=test_space.id,
        created_by_user_id=admin_user.id,
        owner_user_id=admin_user.id,
        published_version=None,
        metadata_json=None,
        flow_run_history_retention_mode=None,
        flow_run_history_retention_days=None,
        created_at=old,
        updated_at=old,
    )
    retention_session.add(flow)
    await retention_session.flush()
    retention_session.add(
        FlowVersions(
            flow_id=flow.id,
            version=1,
            tenant_id=test_tenant.id,
            definition_checksum=f"independent-retention-{uuid4()}",
            definition_json={"schema_version": 1, "steps": []},
            created_at=old,
            updated_at=old,
        )
    )
    await retention_session.flush()
    flow_run = FlowRuns(
        flow_id=flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=admin_user.id,
        principal_service_id=None,
        runtime_service_permission=None,
        tenant_id=test_tenant.id,
        trace_id=uuid4(),
        status="completed",
        started_at=old,
        finished_at=old,
        input_payload_json={},
        output_payload_json={},
        created_at=old,
        updated_at=old,
    )
    retention_session.add(flow_run)
    await retention_session.flush()

    flow_candidates = list(
        (
            await retention_session.scalars(
                FlowRetentionRepository(
                    retention_session
                )._build_due_flow_run_history_purge_query(now=anchor)
            )
        ).all()
    )
    report = await run_registered_retention(retention_session)

    assert flow_run.id not in flow_candidates
    assert report.counts.get("questions.questions_deleted", 0) == 1
    assert report.counts.get("app_runs.app_runs_deleted", 0) == 1
    assert await retention_session.get(FlowRuns, flow_run.id) is not None
    assert await retention_session.get(Questions, question.id) is None
    assert await retention_session.get(AppRuns, app_run.id) is None


@pytest.mark.asyncio
async def test_multi_tenant_isolation(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that retention policies are isolated per tenant."""
    # Set assistant retention to 30 days
    test_assistant.data_retention_days = 30
    retention_session.add(test_assistant)
    await retention_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create old question for this tenant
    old_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=60
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: only this tenant's old questions deleted
    assert deleted_count == 1

    exists = await retention_session.get(Questions, old_question.id)
    assert exists is None, "Old question from this tenant should be deleted"


@pytest.mark.asyncio
async def test_retention_validation_constraints(
    retention_session: AsyncSession, test_assistant: Assistants
):
    """Test that database constraints enforce valid retention ranges."""
    # Test invalid retention (too low)
    test_assistant.data_retention_days = 0
    retention_session.add(test_assistant)

    with pytest.raises(Exception) as exc_info:
        await retention_session.flush()

    assert "ck_assistants_data_retention_days_range" in str(exc_info.value), (
        "Should enforce minimum 1 day constraint"
    )

    # After flush failure, object is expelled from session
    # Reset the value and test too high
    test_assistant.data_retention_days = 3000
    retention_session.add(test_assistant)

    with pytest.raises(Exception) as exc_info:
        await retention_session.flush()

    assert "ck_assistants_data_retention_days_range" in str(exc_info.value), (
        "Should enforce maximum 2555 days constraint"
    )


@pytest.mark.asyncio
async def test_hard_delete_not_soft_delete(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that questions are permanently deleted (hard delete), not soft deleted."""
    test_assistant.data_retention_days = 30
    retention_session.add(test_assistant)
    await retention_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create old question
    old_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=60
    )
    question_id = old_question.id

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    assert deleted_count == 1

    # Verify hard delete - question completely removed from database
    query = select(Questions).where(Questions.id == question_id)
    result = await retention_session.execute(query)
    found = result.scalar_one_or_none()

    assert found is None, "Question should be permanently deleted (hard delete)"

    # Verify no deleted_at column exists (Questions table doesn't support soft delete)
    assert not hasattr(Questions, "deleted_at"), (
        "Questions table should not have soft delete"
    )


@pytest.mark.asyncio
async def test_tenant_level_retention_fallback_for_app_runs(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_app: Apps,
    test_tenant,
    admin_user,
):
    """Test that tenant-level retention applies to app runs when space and app have no policy."""
    # Create tenant retention policy
    tenant_policy = AuditRetentionPolicy(
        tenant_id=test_tenant.id,
        retention_days=365,  # Audit logs
        conversation_retention_enabled=True,
        conversation_retention_days=180,  # Conversation retention
    )
    retention_session.add(tenant_policy)
    await retention_session.flush()

    # Extract IDs
    app_id = test_app.id
    tenant_id = test_tenant.id
    user_id = admin_user.id
    completion_model_id = test_app.completion_model_id

    # Create app runs: one old (200 days), one recent (100 days)
    old_run = await create_old_app_run(
        retention_session, app_id, tenant_id, user_id, completion_model_id, days_old=200
    )
    recent_run = await create_old_app_run(
        retention_session, app_id, tenant_id, user_id, completion_model_id, days_old=100
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("app_runs.app_runs_deleted", 0)
    await retention_session.flush()

    # Verify: old run deleted by tenant policy
    assert deleted_count == 1

    old_exists = await retention_session.get(AppRuns, old_run.id)
    recent_exists = await retention_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "App run older than tenant retention should be deleted"
    assert recent_exists is not None, "App run within tenant retention should be kept"


@pytest.mark.asyncio
async def test_boundary_condition_exact_retention_days(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test boundary condition: question exactly at retention boundary should NOT be deleted.

    The logic uses created_at < cutoff_date, so a question exactly at the boundary
    should be kept (not deleted). This tests the < vs <= boundary condition.
    """
    # Set assistant retention to 30 days
    test_assistant.data_retention_days = 30
    retention_session.add(test_assistant)
    await retention_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one exactly at boundary (30 days), one just past (31 days)
    boundary_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=30
    )
    past_boundary_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=31
    )

    # Run cleanup
    report = await run_registered_retention(
        retention_session, now=boundary_question.created_at + timedelta(days=30)
    )
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: only question past boundary is deleted
    assert deleted_count == 1

    boundary_exists = await retention_session.get(Questions, boundary_question.id)
    past_exists = await retention_session.get(Questions, past_boundary_question.id)

    assert boundary_exists is not None, (
        "Question exactly at 30 days should be kept (< not <=)"
    )
    assert past_exists is None, "Question at 31 days should be deleted"


@pytest.mark.asyncio
async def test_tenant_enabled_but_days_null_keeps_forever(
    retention_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test edge case: tenant retention enabled but days is NULL should keep forever.

    The COALESCE hierarchy treats NULL as 'keep forever'. If conversation_retention_enabled
    is True but conversation_retention_days is NULL, questions should be kept indefinitely
    because the CASE expression returns NULL when days is NULL.
    """
    # Create tenant policy with enabled=True but days=None
    tenant_policy = AuditRetentionPolicy(
        tenant_id=test_tenant.id,
        retention_days=365,  # Audit logs (not conversation)
        conversation_retention_enabled=True,  # Enabled...
        conversation_retention_days=None,  # ...but no days set
    )
    retention_session.add(tenant_policy)
    await retention_session.flush()

    # No space or assistant level retention
    # The COALESCE should return NULL (keep forever) because:
    # 1. Assistant retention = NULL
    # 2. Space retention = NULL
    # 3. Tenant: enabled=True but days=NULL → CASE returns NULL

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create very old question (1000 days)
    old_question = await create_old_question(
        retention_session, assistant_id, tenant_id, user_id, days_old=1000
    )

    # Run cleanup
    report = await run_registered_retention(retention_session)
    deleted_count = report.counts.get("questions.questions_deleted", 0)
    await retention_session.flush()

    # Verify: nothing deleted (enabled=True but days=NULL means keep forever)
    assert deleted_count == 0

    exists = await retention_session.get(Questions, old_question.id)
    assert exists is not None, (
        "Question should be kept when tenant has enabled=True but days=NULL"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("is_app", [False, True], ids=["question", "app_run"])
async def test_policy_cancellation_after_discovery_preserves_the_conversation(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_app: Apps,
    test_tenant,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
    is_app: bool,
):
    """Mutant: delete discovered IDs without re-reading the current due policy."""
    from sqlalchemy import update

    from eneo.data_retention.infrastructure.conversation_retention_repo import (
        ConversationDeletion,
        ConversationRetentionRepository,
    )
    from eneo.database.database import sessionmanager

    owner = test_app if is_app else test_assistant
    owner.data_retention_days = 1
    await retention_session.flush()
    if is_app:
        conversation = await create_old_app_run(
            retention_session,
            owner.id,
            test_tenant.id,
            admin_user.id,
            test_app.completion_model_id,
            days_old=2,
        )
    else:
        conversation = await create_old_question(
            retention_session, owner.id, test_tenant.id, admin_user.id, days_old=2
        )
    owner_id, conversation_id = owner.id, conversation.id
    original_delete = ConversationRetentionRepository.delete_if_still_due

    async def cancel_before_delete(
        repository: ConversationRetentionRepository, identifier: UUID
    ) -> ConversationDeletion | None:
        async with sessionmanager.session() as other, other.begin():
            await other.execute(
                update(type(owner))
                .where(type(owner).id == owner_id)
                .values(data_retention_days=None)
            )
        return await original_delete(repository, identifier)

    monkeypatch.setattr(
        ConversationRetentionRepository, "delete_if_still_due", cancel_before_delete
    )
    report = await run_registered_retention(retention_session)
    step = "app_runs" if is_app else "questions"
    assert report.counts.get(f"{step}.{step}_deleted", 0) == 0
    assert report.blocked[f"{step}.no_longer_due"] == 1
    assert (
        await retention_session.get(AppRuns if is_app else Questions, conversation_id)
        is not None
    )


@pytest.mark.asyncio
async def test_retention_removes_files_only_the_old_answer_used(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """A deleted answer takes its upload and generated files with it.

    A generated file that an answer inside the retention period still links
    is kept. Mutant: releasing a root File while another answer links it.
    """
    test_assistant.data_retention_days = 30
    await retention_session.flush()

    old_question = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, days_old=60
    )
    recent_question = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, days_old=10
    )

    def new_file(name: str) -> Files:
        return Files(
            name=name,
            mimetype="application/pdf",
            owner_type="user",
            owner_user_id=admin_user.id,
            tenant_id=test_tenant.id,
        )

    upload, generated, shared = new_file("upload"), new_file("made"), new_file("kept")
    retention_session.add_all([upload, generated, shared])
    await retention_session.flush()
    upload_id, generated_id, shared_id = upload.id, generated.id, shared.id
    retention_session.add_all(
        [
            QuestionsFiles(question_id=old_question.id, file_id=upload_id, type="user"),
            QuestionsFiles(
                question_id=old_question.id, file_id=generated_id, type="assistant"
            ),
            QuestionsFiles(
                question_id=old_question.id, file_id=shared_id, type="assistant"
            ),
            QuestionsFiles(
                question_id=recent_question.id, file_id=shared_id, type="assistant"
            ),
        ]
    )
    await retention_session.flush()

    report = await run_registered_retention(retention_session)

    assert report.counts["questions.questions_deleted"] == 1
    assert report.counts["questions.files_deleted"] == 2
    assert report.counts["questions.files_in_use"] == 1
    remaining = set(
        await retention_session.scalars(
            select(Files.id).where(Files.id.in_([upload_id, generated_id, shared_id]))
        )
    )
    assert remaining == {shared_id}


@pytest.mark.asyncio
async def test_an_oversized_question_is_proved_within_one_limit_and_passed(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Mutants: a LIMIT per child relation instead of one over all of them; an
    oversized root that stops the page or is deleted anyway."""
    from eneo.data_retention.application.conversation_retention import (
        ConversationRootKind,
    )
    from eneo.data_retention.infrastructure.conversation_retention_repo import (
        ConversationRetentionRepository,
    )
    from eneo.database.tables.mcp_tool_references_table import McpToolReference
    from eneo.main.config import get_settings

    test_assistant.data_retention_days = 1
    await retention_session.flush()
    big = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, 3
    )
    small = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, 2
    )
    attachments = [
        Files(
            name=f"attachment-{index}",
            mimetype="application/pdf",
            owner_user_id=admin_user.id,
            tenant_id=test_tenant.id,
        )
        for index in range(2)
    ]
    retention_session.add_all(attachments)
    await retention_session.flush()
    retention_session.add_all(
        [
            *(
                QuestionsFiles(question_id=big.id, file_id=file.id, type="user")
                for file in attachments
            ),
            *(
                McpToolReference(question_id=big.id, uri=f"tool://{index}")
                for index in range(3)
            ),
        ]
    )
    await retention_session.flush()
    big_id, small_id = big.id, small.id

    # Its session, two links and three tool references: a ceiling of 2 stops
    # at 3 rows.
    repository = ConversationRetentionRepository(
        retention_session,
        kind=ConversationRootKind.QUESTION,
        now=datetime.now(timezone.utc),
    )
    assert await repository.cascade_cost(big_id, 2) == 3
    assert await repository.cascade_cost(big_id, 10) == 6

    settings = get_settings().model_copy(
        update={"retention_conversations_max_unit_rows": 4, "retention_chunk_rows": 30}
    )
    report = await run_registered_retention(retention_session, settings=settings)

    assert report.blocked["questions.unit_exceeds_budget"] == 1
    assert report.counts["questions.questions_deleted"] == 1
    assert await retention_session.get(Questions, big_id) is not None
    assert await retention_session.get(Questions, small_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("short", ["session", "files"])
async def test_a_unit_its_remainder_cannot_fund_writes_nothing(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    short: str,
):
    """Mutant: the root DELETE and its cascade run first and are rolled back
    when the remainder cannot fund the session release or the Files."""
    from sqlalchemy import event

    from eneo.data_retention.application.conversation_retention import (
        ConversationRootKind,
    )
    from eneo.data_retention.infrastructure.conversation_retention_repo import (
        ConversationRetentionRepository,
    )

    test_assistant.data_retention_days = 1
    await retention_session.flush()
    question = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, 2
    )
    upload = Files(
        name="upload",
        mimetype="application/pdf",
        owner_user_id=admin_user.id,
        tenant_id=test_tenant.id,
    )
    retention_session.add(upload)
    await retention_session.flush()
    retention_session.add(
        QuestionsFiles(question_id=question.id, file_id=upload.id, type="user")
    )
    await retention_session.flush()
    repository = ConversationRetentionRepository(
        retention_session,
        kind=ConversationRootKind.QUESTION,
        now=datetime.now(timezone.utc),
    )
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    connection = (await retention_session.connection()).sync_connection
    event.listen(connection, "before_cursor_execute", record)
    try:
        # A session release needs up to 2 rows after the root DELETE; the
        # proof charged the session's lock.
        unit = await repository.delete_unit(
            question.id,
            child_rows=1,
            max_rows=2 if short == "session" else 10,
            max_files=0 if short == "files" else 10,
            max_family_rows=5,
        )
    finally:
        event.remove(connection, "before_cursor_execute", record)

    assert not unit.fits and unit.deletion is None
    assert not [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("DELETE", "SAVEPOINT"))
    ]
    assert await retention_session.get(Questions, question.id) is not None


async def _held_and_later_questions(
    retention_session: AsyncSession, test_assistant: Assistants, test_tenant, admin_user
) -> tuple[UUID, UUID]:
    """A due question linked to an upload, then a later due question."""
    test_assistant.data_retention_days = 1
    await retention_session.flush()
    held = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, 3
    )
    later = await create_old_question(
        retention_session, test_assistant.id, test_tenant.id, admin_user.id, 2
    )
    upload = Files(
        name="upload",
        mimetype="application/pdf",
        owner_user_id=admin_user.id,
        tenant_id=test_tenant.id,
    )
    retention_session.add(upload)
    await retention_session.flush()
    retention_session.add(
        QuestionsFiles(question_id=held.id, file_id=upload.id, type="user")
    )
    held_id, later_id = held.id, later.id
    await retention_session.commit()
    return held_id, later_id


@pytest.mark.asyncio
async def test_a_cascade_lock_wait_keeps_one_question_and_the_open_chunk_goes_on(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Mutants: a lock timeout inside the unit savepoint fails the whole chunk,
    so the run ends partial and the next due question waits for another run;
    the lock wait charges the unit's whole row allowance, which at the default
    unit (5000 rows) and chunk (500 rows) ends the chunk, so the later
    question is deleted in a second batch."""
    from eneo.database.database import sessionmanager
    from eneo.main.config import get_settings

    held_id, later_id = await _held_and_later_questions(
        retention_session, test_assistant, test_tenant, admin_user
    )
    # The default unit and chunk rows: a unit allowance far above the chunk.
    # The gather window outlasts the lock wait on a cold database.
    settings = get_settings().model_copy(
        update={
            "retention_chunk_lock_timeout_ms": 200,
            "retention_chunk_gather_seconds": 60.0,
        }
    )

    # A chat that holds the link row the held question's DELETE cascades to.
    async with sessionmanager.session() as chat, chat.begin():
        await chat.execute(
            select(QuestionsFiles.question_id)
            .where(QuestionsFiles.question_id == held_id)
            .with_for_update()
        )
        report = await run_registered_retention(retention_session, settings=settings)

    assert report.blocked["questions.cascade_locked"] == 1
    assert report.counts["questions.questions_deleted"] == 1
    assert await retention_session.get(Questions, held_id) is not None
    assert await retention_session.get(Questions, later_id) is None
    # One questions batch kept the held question and deleted the later one.
    [batch] = await step_batches(retention_session, report.job_run_id, "questions")
    assert batch["blocked"] == {"cascade_locked": 1}
    assert batch["counts"] == {
        "questions_deleted": 1,
        "sessions_deleted": 1,
        "by_assistant_or_app_rule": 1,
    }


@pytest.mark.asyncio
async def test_a_cascade_lock_wait_at_the_default_ratio_ends_the_chunk_and_the_run_goes_on(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """The default gather window is shorter than the default lock timeout, so
    the chunk that waited admits no further root: it commits the kept question
    and the next chunk deletes the later one. Mutants: a lock timeout inside
    the unit savepoint fails the chunk, so the run ends chunk_timeout and the
    later question is kept; the lock wait charges the unit's whole row
    allowance, so the execution budget cannot fund another unit and the later
    question is deferred."""
    from eneo.data_retention.domain.retention import RetentionJobOutcome
    from eneo.database.database import sessionmanager
    from eneo.main.config import get_settings

    held_id, later_id = await _held_and_later_questions(
        retention_session, test_assistant, test_tenant, admin_user
    )
    # The default gather window and lock timeout, pinned; an execution budget
    # that funds a second unit only if the wait was charged what it read.
    settings = get_settings().model_copy(
        update={
            "retention_chunk_lock_timeout_ms": 2_000,
            "retention_chunk_gather_seconds": 1.0,
            "retention_conversations_max_unit_rows": 5_000,
            "retention_conversations_max_rows_per_run": 6_000,
        }
    )

    async with sessionmanager.session() as chat, chat.begin():
        await chat.execute(
            select(QuestionsFiles.question_id)
            .where(QuestionsFiles.question_id == held_id)
            .with_for_update()
        )
        report = await run_registered_retention(retention_session, settings=settings)

    # Every due question was visited; the kept one is a blocked count.
    assert report.outcome is RetentionJobOutcome.SUCCEEDED
    assert await retention_session.get(Questions, held_id) is not None
    assert await retention_session.get(Questions, later_id) is None
    batches = await step_batches(retention_session, report.job_run_id, "questions")
    assert [(batch["counts"], batch["blocked"]) for batch in batches] == [
        ({}, {"cascade_locked": 1}),
        (
            {
                "questions_deleted": 1,
                "sessions_deleted": 1,
                "by_assistant_or_app_rule": 1,
            },
            {},
        ),
    ]


@pytest.mark.asyncio
async def test_a_statement_timeout_in_the_unit_ends_the_chunk(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Mutant: the unit takes every database error for a lock wait, so a
    statement timeout (57014) keeps the question as cascade_locked and the
    chunk goes on instead of ending the run partial."""
    from eneo.data_retention.domain.retention import (
        RetentionErrorCode,
        RetentionJobOutcome,
    )
    from eneo.database.database import sessionmanager
    from eneo.main.config import get_settings

    held_id, _later_id = await _held_and_later_questions(
        retention_session, test_assistant, test_tenant, admin_user
    )
    # The statement times out before its lock wait would, and not before a
    # cold connection prepares the chunk's other statements.
    settings = get_settings().model_copy(
        update={
            "retention_chunk_statement_timeout_ms": 3_000,
            "retention_chunk_lock_timeout_ms": 60_000,
        }
    )

    async with sessionmanager.session() as chat, chat.begin():
        await chat.execute(
            select(QuestionsFiles.question_id)
            .where(QuestionsFiles.question_id == held_id)
            .with_for_update()
        )
        report = await run_registered_retention(
            retention_session,
            settings=settings,
            error_code=RetentionErrorCode.CHUNK_TIMEOUT,
        )

    assert report.outcome is RetentionJobOutcome.PARTIAL
    assert "questions.cascade_locked" not in report.blocked
    assert await retention_session.get(Questions, held_id) is not None


@pytest.mark.asyncio
async def test_owners_without_due_history_are_charged_and_passed(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Mutants: probed owners are not charged, or the page skips owners without
    a policy uncharged, so the first run reaches the later owner's question;
    exhaustion is decided by the root count, so the empty owners end every pass
    before it."""
    from eneo.main.config import get_settings

    owners = await _numbered_owners(retention_session, test_assistant, admin_user)
    due = await create_old_question(
        retention_session, owners[-1].id, test_tenant.id, admin_user.id, days_old=60
    )
    due_id = due.id
    # Pages of two owners, then one, fit an 8-row run; a unit needs up to 4.
    settings = get_settings().model_copy(
        update={
            "retention_conversations_max_unit_rows": 4,
            "retention_conversations_max_rows_per_run": 8,
            "retention_chunk_rows": 6,
        }
    )

    real_now = datetime.now(timezone.utc)
    # A date on which questions go first among the task's three steps: on the
    # others a step before them charges its rows from the same 8, and questions
    # stop after two owners with the cursor past the second.
    now = next(
        real_now + timedelta(days=offset)
        for offset in range(3)
        if (real_now + timedelta(days=offset)).date().toordinal() % 3 == 0
    )

    # The first run probes owners 1-3, policy or not, and spends the rest of its
    # budget there.
    first = await run_registered_retention(
        retention_session, settings=settings, now=now
    )
    assert first.counts["questions.owners_examined"] == 3
    assert "questions.questions_deleted" not in first.counts
    assert await retention_session.get(Questions, due_id) is not None

    second = await run_registered_retention(
        retention_session, settings=settings, now=now
    )
    assert second.counts["questions.questions_deleted"] == 1
    assert await retention_session.get(Questions, due_id) is None


@pytest.mark.asyncio
async def test_overdue_covers_every_owner_page(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Mutants: overdue reads one page of owners, so more owners than the page
    report an incomplete snapshot (unknown health) and miss a later one; the
    walk ignores its bound in owner rows, or takes it from the overdue row cap,
    so it reads every owner however many."""
    from eneo.data_retention.application.conversation_history_retention_task import (
        ConversationHistoryRetentionTask,
    )
    from eneo.data_retention.application.conversation_retention import (
        ConversationRootKind,
        conversation_page_allocation,
    )
    from eneo.data_retention.infrastructure.conversation_retention_repo import (
        ConversationRetentionRepository,
    )

    owners = await _numbered_owners(retention_session, test_assistant, admin_user)
    repository = ConversationRetentionRepository(
        retention_session,
        kind=ConversationRootKind.QUESTION,
        now=datetime.now(timezone.utc),
    )
    window = timedelta(days=1)

    # Six owners in pages of two: the fourth page comes back empty.
    assert await repository.overdue(
        window=window, limit=2, owner_page=2, max_pages=4
    ) == RetentionOverdue(count=0, complete=True, oldest_due_at=None)

    await create_old_question(
        retention_session, owners[-1].id, test_tenant.id, admin_user.id, days_old=60
    )
    overdue = await repository.overdue(
        window=window, limit=2, owner_page=2, max_pages=4
    )
    assert (overdue.count, overdue.complete) == (1, True)
    assert overdue.oldest_due_at is not None
    # Four owner rows are two pages of two, which end before the fifth owner
    # and its question; the row cap of ten does not widen the walk.
    task = ConversationHistoryRetentionTask(
        retention_session,
        # Discovery pages hold 6 // 3 = 2 owners.
        allocation=conversation_page_allocation(
            unit_rows=4,
            chunk_rows=6,
            execution_rows=1000,
            execution_files=10,
            family_rows=5,
        ),
        now=datetime.now(timezone.utc),
        overdue_window=window,
        overdue_rows=10,
        overdue_owner_rows=4,
        gather_seconds=1.0,
    )
    assert await task.overdue() == RetentionOverdue(
        count=0, complete=False, oldest_due_at=None
    )


@pytest.mark.asyncio
async def test_overdue_pages_owners_apart_from_the_cap_and_stops_at_it(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_app: Apps,
    test_tenant,
    admin_user,
):
    """Mutants: the owner page shrinks to the remaining row cap (two statements
    per owner); the app-run stream is still walked once questions spent the cap."""
    from sqlalchemy import event

    from eneo.data_retention.application.conversation_history_retention_task import (
        ConversationHistoryRetentionTask,
    )
    from eneo.data_retention.application.conversation_retention import (
        conversation_page_allocation,
    )

    owners = await _numbered_owners(retention_session, test_assistant, admin_user)
    for _ in range(2):
        await create_old_question(
            retention_session, owners[-1].id, test_tenant.id, admin_user.id, days_old=60
        )
    other_app = Apps(
        name="Second retention app",
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
        space_id=test_app.space_id,
        completion_model_id=test_app.completion_model_id,
        completion_model_kwargs={},
        data_retention_days=30,
        published=False,
    )
    test_app.data_retention_days = 30
    retention_session.add(other_app)
    await retention_session.flush()
    for app in (test_app, other_app):
        await create_old_app_run(
            retention_session,
            app.id,
            test_tenant.id,
            admin_user.id,
            app.completion_model_id,
            days_old=60,
        )
    task = ConversationHistoryRetentionTask(
        retention_session,
        # Discovery pages hold 30 // 3 = 10 owners: all six assistants at once.
        allocation=conversation_page_allocation(
            unit_rows=4,
            chunk_rows=30,
            execution_rows=1000,
            execution_files=10,
            family_rows=5,
        ),
        now=datetime.now(timezone.utc),
        overdue_window=timedelta(days=1),
        overdue_rows=1,
        overdue_owner_rows=1000,
        gather_seconds=1.0,
    )
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    connection = (await retention_session.connection()).sync_connection
    event.listen(connection, "before_cursor_execute", record)
    try:
        overdue = await task.overdue()
    finally:
        event.remove(connection, "before_cursor_execute", record)

    assert (overdue.count, overdue.complete) == (1, False)
    assert overdue.oldest_due_at is not None
    # One owner page and one window over the questions; no app-run statement.
    assert len(statements) == 2


async def _numbered_owners(
    retention_session: AsyncSession, test_assistant: Assistants, admin_user
) -> list[Assistants]:
    """Assistants 1-5 in id order ahead of the fixture's; only the last has a
    policy (the shared space has none)."""
    owners = [
        Assistants(
            id=UUID(int=index),
            name=f"Policy owner {index}",
            user_id=admin_user.id,
            space_id=test_assistant.space_id,
            completion_model_id=test_assistant.completion_model_id,
            completion_model_kwargs={},
            logging_enabled=True,
            is_default=False,
            published=False,
            data_retention_days=30 if index == 5 else None,
        )
        for index in range(1, 6)
    ]
    retention_session.add_all(owners)
    await retention_session.flush()
    return owners
