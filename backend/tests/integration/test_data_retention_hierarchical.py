"""Integration tests for hierarchical conversation history retention policies.

Tests cover:
- Hierarchical policy resolution (Assistant → Space → Tenant → None)
- Hard deletion of old questions and app runs
- Retention policy persistence and audit logging
- Multi-tenant isolation of retention policies
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_retention import (
    ConversationDeletion,
    conversation_page_allocation,
    run_conversation_page,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.domain.retention import (
    ConversationPolicySource,
    RetentionBudget,
    RetentionJobOutcome,
)
from eneo.data_retention.infrastructure.conversation_retention_repo import (
    ConversationRetentionRepository,
    ConversationRootKind,
)
from eneo.data_retention.infrastructure.retention_tasks import (
    build_conversation_history_task,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.mcp_tool_references_table import McpToolReference
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    Questions,
    QuestionsFiles,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.main.config import get_settings
from tests.integration.data_retention.retention_support import run_conversation_history
from tests.integration.data_retention.test_gallring_runner import _runner, _Task
from tests.integration.flows.flow_run_deletion_support import due_run_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cap,conversations_due,count,complete,oldest_days",
    [
        (1, True, 1, False, 5),
        (2, True, 2, True, 5),
        (4, True, 2, True, 5),
        (1, False, 0, True, None),
    ],
)
async def test_overdue_counts_share_one_deadline_cap_without_orphan_false_alarms(
    async_session,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    cap: int,
    conversations_due: bool,
    count: int,
    complete: bool,
    oldest_days: int | None,
):
    """Kills G1b-P1A: independent store caps, missing policy filters or orphan health noise."""
    now = datetime.now(timezone.utc)
    test_assistant.data_retention_days = 7 if conversations_due else None
    test_app.data_retention_days = 3 if conversations_due else None
    question = await create_old_question(
        async_session,
        test_assistant.id,
        test_tenant.id,
        admin_user.id,
        days_old=12,
    )
    question.created_at = now - timedelta(days=12)
    await async_session.execute(
        update(Sessions)
        .where(Sessions.id == question.session_id)
        .values(created_at=question.created_at)
    )
    app = await create_old_app_run(
        async_session,
        test_app.id,
        test_tenant.id,
        admin_user.id,
        test_app.completion_model_id,
        days_old=8,
    )
    app.created_at = now - timedelta(days=8)
    orphan = Sessions(
        user_id=admin_user.id,
        name="overdue orphan",
        created_at=now - timedelta(days=7),
        updated_at=now,
    )
    async_session.add(orphan)
    await async_session.flush()
    settings = get_settings().model_copy(update={"retention_overdue_max_rows": cap})
    task = build_conversation_history_task(
        async_session,
        RetentionBudget(rows=250_000, files=1, seconds=600),
        settings,
        now=now,
    )
    snapshot = await task.overdue()
    assert (snapshot.count, snapshot.complete) == (count, complete)
    assert snapshot.oldest_due_at == (
        now - timedelta(days=oldest_days) if oldest_days is not None else None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("unit_rows,deleted", [(1, False), (2, True)])
async def test_orphan_session_cascade_respects_age_references_and_unit_cap(
    async_session,
    test_assistant,
    test_space,
    test_tenant,
    admin_user,
    monkeypatch,
    unit_rows: int,
    deleted: bool,
):
    """Kills omitted orphan anti-join, inclusive age cutoff, or omitted helper cost."""
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(get_settings(), "retention_chats_max_unit_rows", unit_rows)
    orphan = Sessions(
        user_id=admin_user.id,
        name="old orphan",
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=3),
    )
    boundary = Sessions(
        user_id=admin_user.id,
        name="exact age boundary",
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    )
    async_session.add_all([orphan, boundary])
    await async_session.flush()
    helper = HelpAssistantRuns(
        tenant_id=test_tenant.id,
        org_space_id=test_space.id,
        kind="help",
        target_type="space",
        target_id=test_space.id,
        session_id=orphan.id,
        actor_user_id=admin_user.id,
    )
    async_session.add(helper)
    referenced = await create_old_question(
        async_session, test_assistant.id, test_tenant.id, admin_user.id, days_old=3
    )
    orphan_id, boundary_id, helper_id = orphan.id, boundary.id, helper.id
    referenced_id, referenced_session = referenced.id, referenced.session_id
    report = await run_conversation_history(async_session, now=now)
    assert report.outcome is RetentionJobOutcome.SUCCEEDED
    assert (await async_session.get(Sessions, orphan_id) is None) is deleted
    assert (await async_session.get(HelpAssistantRuns, helper_id) is None) is deleted
    assert await async_session.get(Sessions, boundary_id) is not None
    assert await async_session.get(Sessions, referenced_session) is not None
    assert await async_session.get(Questions, referenced_id) is not None
    assert report.counts.get("orphan_sessions.orphan_sessions_deleted", 0) == int(
        deleted
    )
    assert report.blocked.get("orphan_sessions.unit_exceeds_budget", 0) == int(
        not deleted
    )
    events = (
        await async_session.scalars(
            select(AuditLog).where(
                AuditLog.log_metadata["job_run_id"].astext == str(report.job_run_id)
            )
        )
    ).all()
    assert any(event.log_metadata["step"] == "orphan_sessions" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "execution_day,first_count",
    [
        (5, "questions.conversations_deleted"),
        (6, "app_runs.conversations_deleted"),
        (7, "questions.conversations_deleted"),
    ],
)
async def test_deadline_stores_rotate_before_aged_session_housekeeping(
    async_session,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    monkeypatch,
    execution_day: int,
    first_count: str,
):
    """Kills G1b-P1B: housekeeping starvation or fixed deadline-store order."""
    now = datetime(2026, 10, execution_day, tzinfo=timezone.utc)
    test_assistant.data_retention_days = test_app.data_retention_days = 1
    question = await create_old_question(
        async_session, test_assistant.id, test_tenant.id, admin_user.id, days_old=60
    )
    await async_session.execute(
        update(Sessions)
        .where(Sessions.id == question.session_id)
        .values(created_at=now - timedelta(days=60))
    )
    app = await create_old_app_run(
        async_session,
        test_app.id,
        test_tenant.id,
        admin_user.id,
        days_old=60,
        completion_model_id=test_app.completion_model_id,
    )
    orphan = Sessions(
        user_id=admin_user.id,
        name="rotated store",
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=3),
    )
    async_session.add(orphan)
    await async_session.flush()
    ids = {
        "questions.conversations_deleted": (Questions, question.id),
        "app_runs.conversations_deleted": (AppRuns, app.id),
        "orphan_sessions.orphan_sessions_deleted": (Sessions, orphan.id),
    }
    for name, value in (
        ("retention_chats_max_rows_per_run", 4),
        ("retention_chats_max_unit_rows", 1),
        ("retention_chunk_rows", 4),
    ):
        monkeypatch.setattr(get_settings(), name, value)
    report = await run_conversation_history(async_session, now=now)
    assert report.outcome is RetentionJobOutcome.PARTIAL
    assert report.counts[first_count] == 1
    assert report.counts.get("orphan_sessions.session_rows_examined", 0) == 0
    assert (
        sum(
            report.counts.get(name, 0)
            for name in (
                "questions.conversations_deleted",
                "app_runs.conversations_deleted",
                "orphan_sessions.orphan_sessions_deleted",
            )
        )
        == 1
    )
    for count, (model, identifier) in ids.items():
        assert (await async_session.get(model, identifier) is None) is (
            count == first_count
        )


@pytest.fixture
async def async_session(setup_database) -> AsyncIterator[AsyncSession]:
    # Runner commits must release real transactions, not nested savepoints.
    async with sessionmanager.session() as session:
        session.sync_session.expire_on_commit = False
        await session.begin()
        yield session


@pytest.fixture
async def test_space(async_session: AsyncSession, test_tenant, admin_user) -> Spaces:
    """Create a test space with no retention policy."""
    space = Spaces(
        name=f"Test Retention Space {admin_user.id}",
        description="Testing retention policies",
        tenant_id=test_tenant.id,
        user_id=admin_user.id,  # Personal space to avoid org space constraint
        tenant_space_id=None,
        data_retention_days=None,  # No space-level retention
    )
    async_session.add(space)
    await async_session.flush()
    return space


@pytest.fixture
async def retention_completion_model(
    async_session: AsyncSession, completion_model_factory
):
    return await completion_model_factory(async_session, "gpt-4")


@pytest.fixture
async def test_assistant(
    async_session: AsyncSession,
    test_space,
    test_tenant,
    admin_user,
    retention_completion_model,
) -> Assistants:
    """Create a test assistant with no retention policy."""
    completion_model = retention_completion_model

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
    async_session.add(assistant)
    await async_session.flush()
    return assistant


@pytest.fixture
async def test_app(
    async_session: AsyncSession,
    test_space,
    test_tenant,
    admin_user,
    retention_completion_model,
) -> Apps:
    """Create a test app with no retention policy."""
    completion_model = retention_completion_model

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
    async_session.add(app)
    await async_session.flush()
    return app


async def create_old_question(
    async_session: AsyncSession, assistant_id, tenant_id, user_id, days_old: int
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
    async_session.add(test_session)
    await async_session.flush()

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
    async_session.add(question)
    await async_session.flush()
    return question


async def create_old_app_run(
    async_session: AsyncSession,
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
    async_session.add(app_run)
    await async_session.flush()
    return app_run


@pytest.mark.asyncio
async def test_assistant_level_retention_deletes_old_questions(
    async_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that assistant-level retention policy deletes old questions."""
    # Set assistant retention to 30 days
    test_assistant.data_retention_days = 30
    async_session.add(test_assistant)
    await async_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one old (60 days), one recent (10 days)
    old_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=60
    )
    recent_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=10
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    # Verify: old question deleted, recent kept
    assert deleted_count == 1

    old_exists = await async_session.get(Questions, old_question.id)
    recent_exists = await async_session.get(Questions, recent_question.id)

    assert old_exists is None, "Old question should be deleted"
    assert recent_exists is not None, "Recent question should be kept"


@pytest.mark.asyncio
async def test_space_level_retention_fallback(
    async_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that space-level retention applies when assistant has no policy."""
    # Set space retention to 90 days (assistant has None)
    test_space.data_retention_days = 90
    async_session.add(test_space)
    await async_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one old (120 days), one recent (60 days)
    old_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=120
    )
    recent_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=60
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    # Verify: old question deleted, recent kept
    assert deleted_count == 1

    old_exists = await async_session.get(Questions, old_question.id)
    recent_exists = await async_session.get(Questions, recent_question.id)

    assert old_exists is None, "Question older than space retention should be deleted"
    assert recent_exists is not None, "Question within space retention should be kept"


@pytest.mark.asyncio
async def test_assistant_overrides_space_retention(
    async_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that assistant-level retention overrides space-level retention."""
    # Space: 90 days, Assistant: 30 days (more restrictive)
    test_space.data_retention_days = 90
    test_assistant.data_retention_days = 30
    async_session.add(test_space)
    async_session.add(test_assistant)
    await async_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create question that's 60 days old (older than assistant, newer than space)
    question_60d = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=60
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    # Verify: question deleted by assistant retention (30d), not space (90d)
    assert deleted_count == 1

    exists = await async_session.get(Questions, question_60d.id)
    assert exists is None, (
        "Assistant retention (30d) should override space retention (90d)"
    )


@pytest.mark.asyncio
async def test_tenant_level_retention_fallback(
    async_session: AsyncSession,
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
    async_session.add(tenant_policy)
    await async_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one old (200 days), one recent (100 days)
    old_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=200
    )
    recent_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=100
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    # Verify: old question deleted by tenant policy
    assert deleted_count == 1

    old_exists = await async_session.get(Questions, old_question.id)
    recent_exists = await async_session.get(Questions, recent_question.id)

    assert old_exists is None, "Question older than tenant retention should be deleted"
    assert recent_exists is not None, "Question within tenant retention should be kept"


@pytest.mark.asyncio
async def test_no_retention_keeps_all_questions(
    async_session: AsyncSession,
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
        async_session, assistant_id, tenant_id, user_id, days_old=1000
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    # Verify: nothing deleted
    assert deleted_count == 0

    exists = await async_session.get(Questions, old_question.id)
    assert exists is not None, "Question should be kept when no retention policy exists"


@pytest.mark.asyncio
async def test_app_level_retention_deletes_old_runs(
    async_session: AsyncSession,
    test_app: Apps,
    test_tenant,
    admin_user,
):
    """Test that app-level retention policy deletes old app runs."""
    # Set app retention to 30 days
    test_app.data_retention_days = 30
    async_session.add(test_app)
    await async_session.flush()

    # Extract IDs
    app_id = test_app.id
    tenant_id = test_tenant.id
    user_id = admin_user.id
    completion_model_id = test_app.completion_model_id

    # Create app runs: one old (60 days), one recent (10 days)
    old_run = await create_old_app_run(
        async_session, app_id, tenant_id, user_id, completion_model_id, days_old=60
    )
    recent_run = await create_old_app_run(
        async_session, app_id, tenant_id, user_id, completion_model_id, days_old=10
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("app_runs.conversations_deleted", 0)
    await async_session.flush()

    # Verify: old run deleted, recent kept
    assert deleted_count == 1

    old_exists = await async_session.get(AppRuns, old_run.id)
    recent_exists = await async_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "Old app run should be deleted"
    assert recent_exists is not None, "Recent app run should be kept"


@pytest.mark.asyncio
async def test_space_level_app_retention_fallback(
    async_session: AsyncSession,
    test_space: Spaces,
    test_app: Apps,
    test_tenant,
    admin_user,
):
    """Test that space-level retention applies to apps without their own policy."""
    # Set space retention to 90 days (app has None)
    test_space.data_retention_days = 90
    async_session.add(test_space)
    await async_session.flush()

    # Extract IDs
    app_id = test_app.id
    tenant_id = test_tenant.id
    user_id = admin_user.id
    completion_model_id = test_app.completion_model_id

    # Create app runs: one old (120 days), one recent (60 days)
    old_run = await create_old_app_run(
        async_session, app_id, tenant_id, user_id, completion_model_id, days_old=120
    )
    recent_run = await create_old_app_run(
        async_session, app_id, tenant_id, user_id, completion_model_id, days_old=60
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("app_runs.conversations_deleted", 0)
    await async_session.flush()

    # Verify: old run deleted by space policy
    assert deleted_count == 1

    old_exists = await async_session.get(AppRuns, old_run.id)
    recent_exists = await async_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "App run older than space retention should be deleted"
    assert recent_exists is not None, "App run within space retention should be kept"


@pytest.mark.asyncio
async def test_space_conversation_and_app_retention_does_not_activate_flow_deletion(
    async_session: AsyncSession,
    test_space: Spaces,
    test_app: Apps,
    test_tenant,
    admin_user,
) -> None:
    anchor = datetime.now(timezone.utc)
    old = anchor - timedelta(days=60)
    test_space.data_retention_days = 30
    await async_session.execute(
        update(Tenants)
        .where(Tenants.id == test_tenant.id)
        .values(
            flow_run_history_retention_mode=None,
            flow_run_history_retention_days=None,
        )
    )
    async_session.add(test_space)

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
    async_session.add(assistant)
    await async_session.flush()
    question = await create_old_question(
        async_session,
        assistant.id,
        test_tenant.id,
        admin_user.id,
        days_old=60,
    )
    app_run = await create_old_app_run(
        async_session,
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
    async_session.add(flow)
    await async_session.flush()
    async_session.add(
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
    await async_session.flush()
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
    async_session.add(flow_run)
    await async_session.flush()

    flow_candidates, _ = await due_run_ids(async_session, test_tenant.id, now=anchor)
    report = await run_conversation_history(async_session)
    deleted_questions = report.counts.get("questions.conversations_deleted", 0)
    deleted_app_runs = report.counts.get("app_runs.conversations_deleted", 0)
    await async_session.flush()

    assert flow_run.id not in flow_candidates
    assert deleted_questions == 1
    assert deleted_app_runs == 1
    assert await async_session.get(FlowRuns, flow_run.id) is not None
    assert await async_session.get(Questions, question.id) is None
    assert await async_session.get(AppRuns, app_run.id) is None


@pytest.mark.asyncio
async def test_multi_tenant_isolation(
    async_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that retention policies are isolated per tenant."""
    # Set assistant retention to 30 days
    test_assistant.data_retention_days = 30
    async_session.add(test_assistant)
    await async_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create old question for this tenant
    old_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=60
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    # Verify: only this tenant's old questions deleted
    assert deleted_count == 1

    exists = await async_session.get(Questions, old_question.id)
    assert exists is None, "Old question from this tenant should be deleted"


@pytest.mark.asyncio
async def test_retention_validation_constraints(
    async_session: AsyncSession, test_assistant: Assistants
):
    """Test that database constraints enforce valid retention ranges."""
    # Test invalid retention (too low)
    test_assistant.data_retention_days = 0
    async_session.add(test_assistant)

    with pytest.raises(Exception) as exc_info:
        await async_session.flush()

    assert "ck_assistants_data_retention_days_range" in str(exc_info.value), (
        "Should enforce minimum 1 day constraint"
    )

    # After flush failure, object is expelled from session
    # Reset the value and test too high
    test_assistant.data_retention_days = 3000
    async_session.add(test_assistant)

    with pytest.raises(Exception) as exc_info:
        await async_session.flush()

    assert "ck_assistants_data_retention_days_range" in str(exc_info.value), (
        "Should enforce maximum 2555 days constraint"
    )


@pytest.mark.asyncio
async def test_hard_delete_not_soft_delete(
    async_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Test that questions are permanently deleted (hard delete), not soft deleted."""
    test_assistant.data_retention_days = 30
    async_session.add(test_assistant)
    await async_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create old question
    old_question = await create_old_question(
        async_session, assistant_id, tenant_id, user_id, days_old=60
    )
    question_id = old_question.id

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    assert deleted_count == 1

    # Verify hard delete - question completely removed from database
    query = select(Questions).where(Questions.id == question_id)
    result = await async_session.execute(query)
    found = result.scalar_one_or_none()

    assert found is None, "Question should be permanently deleted (hard delete)"

    # Verify no deleted_at column exists (Questions table doesn't support soft delete)
    assert not hasattr(Questions, "deleted_at"), (
        "Questions table should not have soft delete"
    )


@pytest.mark.asyncio
async def test_tenant_level_retention_fallback_for_app_runs(
    async_session: AsyncSession,
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
    async_session.add(tenant_policy)
    await async_session.flush()

    # Extract IDs
    app_id = test_app.id
    tenant_id = test_tenant.id
    user_id = admin_user.id
    completion_model_id = test_app.completion_model_id

    # Create app runs: one old (200 days), one recent (100 days)
    old_run = await create_old_app_run(
        async_session, app_id, tenant_id, user_id, completion_model_id, days_old=200
    )
    recent_run = await create_old_app_run(
        async_session, app_id, tenant_id, user_id, completion_model_id, days_old=100
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("app_runs.conversations_deleted", 0)
    await async_session.flush()

    # Verify: old run deleted by tenant policy
    assert deleted_count == 1

    old_exists = await async_session.get(AppRuns, old_run.id)
    recent_exists = await async_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "App run older than tenant retention should be deleted"
    assert recent_exists is not None, "App run within tenant retention should be kept"


@pytest.mark.asyncio
async def test_tenant_enabled_but_days_null_keeps_forever(
    async_session: AsyncSession,
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
    async_session.add(tenant_policy)
    await async_session.flush()

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
        async_session, assistant_id, tenant_id, user_id, days_old=1000
    )

    # Run cleanup
    report = await run_conversation_history(async_session)
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await async_session.flush()

    # Verify: nothing deleted (enabled=True but days=NULL means keep forever)
    assert deleted_count == 0

    exists = await async_session.get(Questions, old_question.id)
    assert exists is not None, (
        "Question should be kept when tenant has enabled=True but days=NULL"
    )


async def create_conversation_root(
    session: AsyncSession,
    owner: Assistants | Apps,
    tenant_id: UUID,
    user_id: UUID,
    *,
    days_old: int,
) -> Questions | AppRuns:
    if isinstance(owner, Assistants):
        return await create_old_question(
            session, owner.id, tenant_id, user_id, days_old
        )
    return await create_old_app_run(
        session, owner.id, tenant_id, user_id, owner.completion_model_id, days_old
    )


async def add_conversation_files(
    session: AsyncSession,
    root: Questions | AppRuns,
    user_id: UUID,
    count: int,
) -> set[UUID]:
    files = [
        Files(
            name=f"retained-{index}.txt",
            tenant_id=root.tenant_id,
            owner_type="user",
            owner_user_id=user_id,
        )
        for index in range(count)
    ]
    session.add_all(files)
    await session.flush()
    for file in files:
        reference = (
            QuestionsFiles(question_id=root.id, file_id=file.id, type="input")
            if isinstance(root, Questions)
            else AppRunsFiles(app_run_id=root.id, file_id=file.id)
        )
        session.add(reference)
    await session.flush()
    return {file.id for file in files}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
async def test_oversized_conversation_keeps_its_children_and_allows_later_roots(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
):
    """Kills G1b-C02/C03: omit cascade cost, or stop at an oversized root."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    oversized = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=60
    )
    small = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=50
    )
    file_ids = await add_conversation_files(async_session, oversized, admin_user.id, 5)
    file_ids |= await add_conversation_files(async_session, small, admin_user.id, 1)
    repository = ConversationRetentionRepository(
        async_session, kind=kind, now=datetime.now(timezone.utc)
    )
    allocation = conversation_page_allocation(
        unit_rows=4, chunk_rows=12, execution_rows=50
    )
    result = await run_conversation_page(
        repository,
        RetentionBatch(
            job_run_id=uuid4(), batch_seq=0, rows=allocation.max_batch, files=0
        ),
        allocation,
    )
    remaining = set((await async_session.scalars(select(type(oversized).id))).all())
    assert oversized.id in remaining and small.id not in remaining
    references = (
        QuestionsFiles if kind is ConversationRootKind.QUESTION else AppRunsFiles
    )
    assert len((await async_session.scalars(select(references.file_id))).all()) == 5
    assert (
        set(
            (
                await async_session.scalars(
                    select(Files.id).where(Files.id.in_(file_ids))
                )
            ).all()
        )
        == file_ids
    )
    assert result.rows == 6  # Two discovery/proof pairs, one root, one child.
    assert result.blocked == {"unit_exceeds_budget": 1}
    assert result.cursor is not None and result.cursor.id == small.id
    assert result.exhausted and not result.deferred
    assert len(result.effects) == 1
    assert result.effects[0].tenant_id == test_tenant.id
    assert result.effects[0].counts == {"conversations_deleted": 1, "by_own_rule": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
@pytest.mark.parametrize(
    "completed_prefix,unit_rows,chunk_rows,remaining_rows",
    [
        (False, 4, 12, 5),
        (True, 7, 6, 11),
    ],
    ids=["execution-remainder", "chunk-remainder"],
)
async def test_conversation_remainder_preserves_next_root_for_a_fresh_call(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
    completed_prefix: bool,
    unit_rows: int,
    chunk_rows: int,
    remaining_rows: int,
):
    """Kills G1b-C04/C05: skip a no-fit root, or enlarge every unit's allowance."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    first = (
        await create_conversation_root(
            async_session, owner, test_tenant.id, admin_user.id, days_old=60
        )
        if completed_prefix
        else None
    )
    next_root = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=50
    )
    await add_conversation_files(async_session, next_root, admin_user.id, 3)
    repository = ConversationRetentionRepository(
        async_session, kind=kind, now=datetime.now(timezone.utc)
    )
    allocation = conversation_page_allocation(
        unit_rows=unit_rows, chunk_rows=chunk_rows, execution_rows=50
    )
    partial = await run_conversation_page(
        repository,
        RetentionBatch(job_run_id=uuid4(), batch_seq=0, rows=remaining_rows, files=0),
        allocation,
    )
    remaining = set((await async_session.scalars(select(type(next_root).id))).all())
    assert next_root.id in remaining
    assert not partial.blocked and not partial.exhausted
    assert partial.deferred is not completed_prefix
    if first is None:
        assert partial.rows == 0 and partial.cursor is None and not partial.effects
    else:
        assert first.id not in remaining and partial.rows == 5
        assert partial.cursor is not None and partial.cursor.id == first.id
        assert partial.effects[0].counts == {
            "conversations_deleted": 1,
            "by_own_rule": 1,
        }
    resumed = await run_conversation_page(
        repository,
        RetentionBatch(
            job_run_id=uuid4(),
            batch_seq=1,
            rows=allocation.max_batch,
            files=0,
            cursor=partial.cursor,
        ),
        allocation,
    )
    assert (
        next_root.id
        not in (await async_session.scalars(select(type(next_root).id))).all()
    )
    assert resumed.rows == 6 and not resumed.deferred
    assert resumed.effects[0].counts == {"conversations_deleted": 1, "by_own_rule": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
@pytest.mark.parametrize(
    "own_days,space_days,organization_days,expected_source",
    [
        (None, None, None, None),
        (90, None, None, None),
        (None, 10, None, ConversationPolicySource.SPACE),
        (None, None, 10, ConversationPolicySource.ORGANIZATION),
    ],
)
async def test_conversation_delete_rechecks_policy_and_audits_its_current_source(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_space,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
    own_days: int | None,
    space_days: int | None,
    organization_days: int | None,
    expected_source: ConversationPolicySource | None,
):
    """Kills G1b-C06/C07: delete from stale eligibility or audit its old rule."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    root = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=60
    )
    repository = ConversationRetentionRepository(
        async_session, kind=kind, now=datetime.now(timezone.utc)
    )
    selected = await repository.lock_due_page(None, 1)
    assert [row.id for row in selected.roots] == [root.id]
    assert list(selected.locked_ids) == [root.id]
    assert await repository.cascade_costs([root.id], 4) == {root.id: 0}
    owner.data_retention_days = own_days
    test_space.data_retention_days = space_days
    if organization_days is not None:
        async_session.add(
            AuditRetentionPolicy(
                tenant_id=test_tenant.id,
                retention_days=365,
                conversation_retention_enabled=True,
                conversation_retention_days=organization_days,
            )
        )
    await async_session.flush()
    deleted = await repository.delete_due_prefix([root.id])
    exists = root.id in (await async_session.scalars(select(type(root).id))).all()
    if expected_source is None:
        assert deleted == () and exists
    else:
        assert len(deleted) == 1 and not exists
        assert deleted[0].tenant_id == test_tenant.id
        assert deleted[0].source is expected_source


@pytest.mark.asyncio
async def test_question_budget_counts_all_three_cascading_reference_stores(
    async_session: AsyncSession,
    test_assistant,
    test_tenant,
    admin_user,
):
    """Kills G1b-C08: omit a reference store from the cascade proof."""
    test_assistant.data_retention_days = 30
    root = await create_old_question(
        async_session, test_assistant.id, test_tenant.id, admin_user.id, days_old=60
    )
    files = await add_conversation_files(async_session, root, admin_user.id, 1)
    blob = InfoBlobs(
        text="independent knowledge",
        size=21,
        source_id=uuid4(),
        version_state="active",
        user_id=admin_user.id,
        tenant_id=test_tenant.id,
    )
    async_session.add(blob)
    await async_session.flush()
    async_session.add_all(
        [
            InfoBlobReferences(question_id=root.id, info_blob_id=blob.id),
            McpToolReference(question_id=root.id, uri="test://independent-reference"),
        ]
    )
    await async_session.flush()
    repository = ConversationRetentionRepository(
        async_session,
        kind=ConversationRootKind.QUESTION,
        now=datetime.now(timezone.utc),
    )
    allocation = conversation_page_allocation(
        unit_rows=3, chunk_rows=12, execution_rows=50
    )
    refused = await run_conversation_page(
        repository,
        RetentionBatch(
            job_run_id=uuid4(), batch_seq=0, rows=allocation.max_batch, files=0
        ),
        allocation,
    )
    assert refused.blocked == {"unit_exceeds_budget": 1} and not refused.effects
    assert root.id in (await async_session.scalars(select(Questions.id))).all()
    allocation = conversation_page_allocation(
        unit_rows=4, chunk_rows=12, execution_rows=50
    )
    deleted = await run_conversation_page(
        repository,
        RetentionBatch(
            job_run_id=uuid4(), batch_seq=0, rows=allocation.max_batch, files=0
        ),
        allocation,
    )
    assert deleted.rows == 6 and deleted.effects[0].counts["conversations_deleted"] == 1
    assert root.id not in (await async_session.scalars(select(Questions.id))).all()
    assert not (await async_session.scalars(select(QuestionsFiles.question_id))).all()
    assert not (
        await async_session.scalars(select(InfoBlobReferences.question_id))
    ).all()
    assert not (await async_session.scalars(select(McpToolReference.question_id))).all()
    assert blob.id in (await async_session.scalars(select(InfoBlobs.id))).all()
    assert files <= set((await async_session.scalars(select(Files.id))).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
@pytest.mark.parametrize("competing_write", ["root_lock", "child_insert"])
async def test_conversation_page_skips_roots_with_competing_writers(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
    competing_write: str,
):
    """Kills G1b-C09: remove SKIP LOCKED or weaken the FK-conflicting root lock."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    root = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=60
    )
    next_root = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=59
    )
    file = Files(
        name="concurrent.txt",
        tenant_id=test_tenant.id,
        owner_type="user",
        owner_user_id=admin_user.id,
    )
    async_session.add(file)
    await async_session.flush()
    root_id, file_id, next_id = root.id, file.id, next_root.id
    records = type(root)
    await async_session.commit()
    async with (
        sessionmanager.session() as writer,
        writer.begin(),
        sessionmanager.session() as worker,
        worker.begin(),
    ):
        if competing_write == "root_lock":
            await writer.execute(
                select(records.id).where(records.id == root_id).with_for_update()
            )
        else:
            reference = (
                QuestionsFiles(question_id=root_id, file_id=file_id, type="input")
                if kind is ConversationRootKind.QUESTION
                else AppRunsFiles(app_run_id=root_id, file_id=file_id)
            )
            writer.add(reference)
            await writer.flush()
        await worker.execute(text("SET LOCAL lock_timeout = '250ms'"))
        repository = ConversationRetentionRepository(
            worker, kind=kind, now=datetime.now(timezone.utc)
        )
        allocation = conversation_page_allocation(
            unit_rows=4, chunk_rows=12, execution_rows=50
        )
        batch = RetentionBatch(job_run_id=uuid4(), batch_seq=0, rows=6, files=0)
        skipped = await run_conversation_page(repository, batch, allocation)
        assert not skipped.exhausted and skipped.rows == 1 and not skipped.effects
        assert skipped.blocked == {"root_locked": 1}
        assert skipped.cursor is not None and skipped.cursor.id == root_id
        assert root_id in (await worker.scalars(select(records.id))).all()
        following = await run_conversation_page(
            repository,
            RetentionBatch(
                job_run_id=batch.job_run_id,
                batch_seq=1,
                rows=6,
                files=0,
                cursor=skipped.cursor,
            ),
            allocation,
        )
        assert following.effects[0].counts["conversations_deleted"] == 1
        assert next_id not in (await worker.scalars(select(records.id))).all()
        await writer.rollback()
        resumed = await run_conversation_page(repository, batch, allocation)
        assert resumed.effects[0].counts["conversations_deleted"] == 1
        assert root_id not in (await worker.scalars(select(records.id))).all()
        assert file_id in (await worker.scalars(select(Files.id))).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
async def test_conversation_page_failure_rolls_back_roots_and_their_cascades(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
):
    """Kills G1b-C10: commit deletion separately from its enclosing transaction."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    root = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=60
    )
    files = await add_conversation_files(async_session, root, admin_user.id, 3)
    root_id, records = root.id, type(root)
    await async_session.commit()
    with pytest.raises(RuntimeError, match="required audit failed"):
        async with sessionmanager.session() as worker, worker.begin():
            repository = ConversationRetentionRepository(
                worker, kind=kind, now=datetime.now(timezone.utc)
            )
            allocation = conversation_page_allocation(
                unit_rows=4, chunk_rows=12, execution_rows=50
            )
            deleted = await run_conversation_page(
                repository,
                RetentionBatch(
                    job_run_id=uuid4(), batch_seq=0, rows=allocation.max_batch, files=0
                ),
                allocation,
            )
            assert deleted.effects[0].counts["conversations_deleted"] == 1
            raise RuntimeError("required audit failed")
    async with sessionmanager.session() as verifier, verifier.begin():
        assert root_id in (await verifier.scalars(select(records.id))).all()
        references = (
            QuestionsFiles if kind is ConversationRootKind.QUESTION else AppRunsFiles
        )
        assert files <= set((await verifier.scalars(select(references.file_id))).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
async def test_conversation_cursor_reaches_older_roots_of_the_next_owner(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    assistant_factory,
    app_factory,
    kind: ConversationRootKind,
):
    """Kills G1b-C11: apply the timestamp cursor across different owners."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    factory = (
        assistant_factory if kind is ConversationRootKind.QUESTION else app_factory
    )
    other = await factory(
        async_session,
        "Other retention owner",
        owner.completion_model_id,
        space_id=owner.space_id,
        data_retention_days=30,
    )
    owners = sorted([owner, other], key=lambda row: row.id)
    first = await create_conversation_root(
        async_session, owners[0], test_tenant.id, admin_user.id, days_old=50
    )
    second = await create_conversation_root(
        async_session, owners[1], test_tenant.id, admin_user.id, days_old=80
    )
    repository = ConversationRetentionRepository(
        async_session, kind=kind, now=datetime.now(timezone.utc)
    )
    allocation = conversation_page_allocation(
        unit_rows=3, chunk_rows=3, execution_rows=50
    )
    initial = await run_conversation_page(
        repository,
        RetentionBatch(
            job_run_id=uuid4(), batch_seq=0, rows=allocation.max_batch, files=0
        ),
        allocation,
    )
    remaining = set((await async_session.scalars(select(type(first).id))).all())
    assert first.id not in remaining and second.id in remaining
    assert initial.cursor is not None and initial.cursor.group == owners[0].id
    following = await run_conversation_page(
        repository,
        RetentionBatch(
            job_run_id=uuid4(),
            batch_seq=1,
            rows=allocation.max_batch,
            files=0,
            cursor=initial.cursor,
        ),
        allocation,
    )
    assert second.id not in (await async_session.scalars(select(type(first).id))).all()
    assert following.effects[0].counts == {"conversations_deleted": 1, "by_own_rule": 1}
    assert following.cursor is not None and following.cursor.group == owners[1].id


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
async def test_conversation_cutoff_keeps_equal_and_newer_roots(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
):
    """Kills G1b-C12: make the strict retention cutoff inclusive."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    now = datetime.now(timezone.utc)
    roots = []
    for delta in [-1, 0, 1]:
        root = await create_conversation_root(
            async_session, owner, test_tenant.id, admin_user.id, days_old=30
        )
        root.created_at = now - timedelta(days=30) + timedelta(microseconds=delta)
        roots.append(root)
    await async_session.flush()
    repository = ConversationRetentionRepository(async_session, kind=kind, now=now)
    allocation = conversation_page_allocation(
        unit_rows=4, chunk_rows=12, execution_rows=50
    )
    result = await run_conversation_page(
        repository,
        RetentionBatch(
            job_run_id=uuid4(), batch_seq=0, rows=allocation.max_batch, files=0
        ),
        allocation,
    )
    remaining = set((await async_session.scalars(select(type(roots[0]).id))).all())
    assert roots[0].id not in remaining
    assert {root.id for root in roots[1:]} <= remaining
    assert result.effects[0].counts == {"conversations_deleted": 1, "by_own_rule": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
async def test_conversation_run_defers_its_tail_without_one_root_transactions(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
):
    """Kills G1b-C13: shrink the remaining run budget into one-root pages."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    roots = [
        await create_conversation_root(
            async_session, owner, test_tenant.id, admin_user.id, days_old=60 - index
        )
        for index in range(10)
    ]
    allocation = conversation_page_allocation(
        unit_rows=4, chunk_rows=6, execution_rows=23
    )
    repository = ConversationRetentionRepository(
        async_session, kind=kind, now=datetime.now(timezone.utc)
    )
    remaining, cursor, charged_pages = 23, None, 0
    for sequence in range(10):
        result = await run_conversation_page(
            repository,
            RetentionBatch(
                job_run_id=uuid4(),
                batch_seq=sequence,
                rows=min(remaining, allocation.max_batch),
                files=0,
                cursor=cursor,
            ),
            allocation,
        )
        remaining -= result.rows
        cursor = result.cursor
        charged_pages += bool(result.rows)
        if result.deferred or result.exhausted:
            break
    assert charged_pages == 3 and remaining == 5
    assert result.deferred and result.rows == 0 and not result.effects
    assert cursor is not None and cursor.id == roots[5].id
    assert set((await async_session.scalars(select(type(roots[0]).id))).all()) == {
        root.id for root in roots[6:]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(ConversationRootKind))
async def test_fresh_policy_refusal_keeps_the_root_and_audits_proof_work(
    async_session: AsyncSession,
    test_assistant,
    test_app,
    test_tenant,
    admin_user,
    kind: ConversationRootKind,
):
    """Kills G1b-C14: charge discovery/proof without an audited fresh refusal."""
    owner = test_assistant if kind is ConversationRootKind.QUESTION else test_app
    owner.data_retention_days = 30
    root = await create_conversation_root(
        async_session, owner, test_tenant.id, admin_user.id, days_old=60
    )
    root_id, owner_id, owner_type, record_type = (
        root.id,
        owner.id,
        type(owner),
        type(root),
    )
    await async_session.commit()

    class PolicyChangingRepository(ConversationRetentionRepository):
        async def delete_due_prefix(
            self, ids: Sequence[UUID]
        ) -> Sequence[ConversationDeletion]:
            await self.session.execute(
                update(owner_type)
                .where(owner_type.id == owner_id)
                .values(data_retention_days=90)
            )
            return await super().delete_due_prefix(ids)

    async with sessionmanager.session() as session:
        repository = PolicyChangingRepository(
            session, kind=kind, now=datetime.now(timezone.utc)
        )
        allocation = conversation_page_allocation(
            unit_rows=4, chunk_rows=12, execution_rows=50
        )

        async def page(batch: RetentionBatch) -> RetentionStepResult:
            return await run_conversation_page(repository, batch, allocation)

        task = _Task(
            (
                RetentionStep(
                    "roots", page, max_batch=allocation.max_batch, max_files=0
                ),
            ),
            count_keys=frozenset(
                {
                    "conversations_deleted",
                    "by_own_rule",
                    "by_space_rule",
                    "by_organization_rule",
                }
            ),
            blocked_keys=frozenset({"unit_exceeds_budget", "no_longer_due"}),
            name="tests.conversation_fresh",
        )
        report = await _runner(session, budget_rows=50, chunk_rows=12).run(task)
    assert report.outcome is RetentionJobOutcome.SUCCEEDED
    assert report.blocked == {"roots.no_longer_due": 1}
    assert not report.counts
    async with sessionmanager.session() as verifier, verifier.begin():
        assert await verifier.get(record_type, root_id) is not None
        events = list(
            (
                await verifier.scalars(
                    select(AuditLog).where(
                        AuditLog.log_metadata["job_run_id"].astext
                        == str(report.job_run_id)
                    )
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].log_metadata["blocked"] == {"no_longer_due": 1}
        assert events[0].log_metadata["counts"] == {}
