"""Integration tests for hierarchical conversation history retention policies.

Tests cover:
- Hierarchical policy resolution (Assistant → Space → Tenant → None)
- Hard deletion of old questions and app runs
- Retention policy persistence and audit logging
- Multi-tenant isolation of retention policies
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.domain.retention import RetentionOverdue
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from tests.integration.data_retention.retention_support import run_registered_retention


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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
    await retention_session.flush()

    # Verify: old question deleted by tenant policy
    assert deleted_count == 1

    old_exists = await retention_session.get(Questions, old_question.id)
    recent_exists = await retention_session.get(Questions, recent_question.id)

    assert old_exists is None, "Question older than tenant retention should be deleted"
    assert recent_exists is not None, "Question within tenant retention should be kept"


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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    deleted_count = report.counts.get("app_runs.conversations_deleted", 0)
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
    deleted_count = report.counts.get("app_runs.conversations_deleted", 0)
    await retention_session.flush()

    # Verify: old run deleted by space policy
    assert deleted_count == 1

    old_exists = await retention_session.get(AppRuns, old_run.id)
    recent_exists = await retention_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "App run older than space retention should be deleted"
    assert recent_exists is not None, "App run within space retention should be kept"


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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    deleted_count = report.counts.get("app_runs.conversations_deleted", 0)
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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    deleted_count = report.counts.get("questions.conversations_deleted", 0)
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
    original_delete = ConversationRetentionRepository.delete_due_prefix

    async def cancel_before_delete(
        repository: ConversationRetentionRepository, identifiers: Sequence[UUID]
    ) -> Sequence[ConversationDeletion]:
        async with sessionmanager.session() as other, other.begin():
            await other.execute(
                update(type(owner))
                .where(type(owner).id == owner_id)
                .values(data_retention_days=None)
            )
        return await original_delete(repository, identifiers)

    monkeypatch.setattr(
        ConversationRetentionRepository, "delete_due_prefix", cancel_before_delete
    )
    report = await run_registered_retention(retention_session)
    step = "app_runs" if is_app else "questions"
    assert report.counts.get(f"{step}.conversations_deleted", 0) == 0
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
            user_id=admin_user.id,
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

    assert report.counts["questions.conversations_deleted"] == 1
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
    from eneo.data_retention.infrastructure.conversation_retention_repo import (
        ConversationRetentionRepository,
        ConversationRootKind,
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
            user_id=admin_user.id,
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

    # Two links and three tool references: a ceiling of 2 stops at 3 rows.
    repository = ConversationRetentionRepository(
        retention_session,
        kind=ConversationRootKind.QUESTION,
        now=datetime.now(timezone.utc),
    )
    assert await repository.cascade_cost(big_id, 2) == 3
    assert await repository.cascade_cost(big_id, 10) == 5

    settings = get_settings().model_copy(
        update={"retention_conversations_max_unit_rows": 4, "retention_chunk_rows": 30}
    )
    report = await run_registered_retention(retention_session, settings=settings)

    assert report.blocked["questions.unit_exceeds_budget"] == 1
    assert report.counts["questions.conversations_deleted"] == 1
    assert await retention_session.get(Questions, big_id) is not None
    assert await retention_session.get(Questions, small_id) is None


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

    # The first run probes owners 1-3, policy or not, and spends the rest of its
    # budget there.
    first = await run_registered_retention(retention_session, settings=settings)
    assert first.counts["questions.owners_examined"] == 3
    assert "questions.conversations_deleted" not in first.counts
    assert await retention_session.get(Questions, due_id) is not None

    second = await run_registered_retention(retention_session, settings=settings)
    assert second.counts["questions.conversations_deleted"] == 1
    assert await retention_session.get(Questions, due_id) is None


@pytest.mark.asyncio
async def test_overdue_covers_every_owner_page(
    retention_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
):
    """Mutant: overdue reads one page of owners, so more owners than the page
    report an incomplete snapshot (unknown health) and miss a later one."""
    from eneo.data_retention.infrastructure.conversation_retention_repo import (
        ConversationRetentionRepository,
        ConversationRootKind,
    )

    owners = await _numbered_owners(retention_session, test_assistant, admin_user)
    repository = ConversationRetentionRepository(
        retention_session,
        kind=ConversationRootKind.QUESTION,
        now=datetime.now(timezone.utc),
    )
    window = timedelta(days=1)

    assert await repository.overdue(
        window=window, limit=2, owner_page=2
    ) == RetentionOverdue(count=0, complete=True, oldest_due_at=None)

    await create_old_question(
        retention_session, owners[-1].id, test_tenant.id, admin_user.id, days_old=60
    )
    overdue = await repository.overdue(window=window, limit=2, owner_page=2)
    assert (overdue.count, overdue.complete) == (1, True)
    assert overdue.oldest_due_at is not None


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
