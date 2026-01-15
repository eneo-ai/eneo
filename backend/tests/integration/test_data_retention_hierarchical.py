"""Integration tests for hierarchical conversation history retention policies.

Tests cover:
- Hierarchical policy resolution (Assistant → Space → Tenant → None)
- Hard deletion of old questions and app runs
- Retention policy persistence and audit logging
- Multi-tenant isolation of retention policies
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.app_table import AppRuns, Apps
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.spaces_table import Spaces
from intric.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)


@pytest.fixture
async def retention_service(async_session: AsyncSession) -> DataRetentionService:
    """Create a DataRetentionService instance."""
    return DataRetentionService(async_session)


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
async def test_assistant(async_session: AsyncSession, test_space, test_tenant, admin_user, completion_model_factory) -> Assistants:
    """Create a test assistant with no retention policy."""
    completion_model = await completion_model_factory(async_session, "gpt-4")

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
async def test_app(async_session: AsyncSession, test_space, test_tenant, admin_user, completion_model_factory) -> Apps:
    """Create a test app with no retention policy."""
    completion_model = await completion_model_factory(async_session, "gpt-4")

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
    async_session: AsyncSession,
    assistant_id,
    tenant_id,
    user_id,
    days_old: int
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
    days_old: int
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
    retention_service: DataRetentionService,
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
    old_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=60)
    recent_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=10)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
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
    retention_service: DataRetentionService,
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
    old_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=120)
    recent_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=60)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
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
    retention_service: DataRetentionService,
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
    question_60d = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=60)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
    await async_session.flush()

    # Verify: question deleted by assistant retention (30d), not space (90d)
    assert deleted_count == 1

    exists = await async_session.get(Questions, question_60d.id)
    assert exists is None, "Assistant retention (30d) should override space retention (90d)"


@pytest.mark.asyncio
async def test_tenant_level_retention_fallback(
    async_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
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
    old_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=200)
    recent_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=100)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
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
    retention_service: DataRetentionService,
):
    """Test that questions are kept forever when no retention policy is set."""
    # No retention at any level

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create very old question (1000 days)
    old_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=1000)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
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
    retention_service: DataRetentionService,
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
    old_run = await create_old_app_run(async_session, app_id, tenant_id, user_id, completion_model_id, days_old=60)
    recent_run = await create_old_app_run(async_session, app_id, tenant_id, user_id, completion_model_id, days_old=10)

    # Run cleanup
    deleted_count = await retention_service.delete_old_app_runs()
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
    retention_service: DataRetentionService,
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
    old_run = await create_old_app_run(async_session, app_id, tenant_id, user_id, completion_model_id, days_old=120)
    recent_run = await create_old_app_run(async_session, app_id, tenant_id, user_id, completion_model_id, days_old=60)

    # Run cleanup
    deleted_count = await retention_service.delete_old_app_runs()
    await async_session.flush()

    # Verify: old run deleted by space policy
    assert deleted_count == 1

    old_exists = await async_session.get(AppRuns, old_run.id)
    recent_exists = await async_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "App run older than space retention should be deleted"
    assert recent_exists is not None, "App run within space retention should be kept"


@pytest.mark.asyncio
async def test_multi_tenant_isolation(
    async_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
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
    old_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=60)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
    await async_session.flush()

    # Verify: only this tenant's old questions deleted
    assert deleted_count == 1

    exists = await async_session.get(Questions, old_question.id)
    assert exists is None, "Old question from this tenant should be deleted"


@pytest.mark.asyncio
async def test_get_affected_count_for_assistant(
    async_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
):
    """Test getting affected question count before enabling retention."""
    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions at different ages
    await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=100)
    await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=50)
    await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=10)

    # Check affected count for 30-day retention
    count = await retention_service.get_affected_questions_count_for_assistant(
        assistant_id=test_assistant.id,
        retention_days=30
    )

    # Should find 2 questions older than 30 days
    assert count == 2, "Should count questions older than 30 days"


@pytest.mark.asyncio
async def test_get_affected_count_for_space(
    async_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
):
    """Test getting affected question count for space-level retention."""
    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions for assistant without retention
    await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=100)
    await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=50)
    await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=10)

    # Check affected count for space 90-day retention
    count = await retention_service.get_affected_questions_count_for_space(
        space_id=test_space.id,
        retention_days=90
    )

    # Should find 1 question older than 90 days
    assert count == 1, "Should count questions older than 90 days without assistant retention"


@pytest.mark.asyncio
async def test_retention_validation_constraints(async_session: AsyncSession, test_assistant: Assistants):
    """Test that database constraints enforce valid retention ranges."""
    # Test invalid retention (too low)
    test_assistant.data_retention_days = 0
    async_session.add(test_assistant)

    with pytest.raises(Exception) as exc_info:
        await async_session.flush()

    assert "ck_assistants_data_retention_days_range" in str(exc_info.value), \
        "Should enforce minimum 1 day constraint"

    # After flush failure, object is expelled from session
    # Reset the value and test too high
    test_assistant.data_retention_days = 3000
    async_session.add(test_assistant)

    with pytest.raises(Exception) as exc_info:
        await async_session.flush()

    assert "ck_assistants_data_retention_days_range" in str(exc_info.value), \
        "Should enforce maximum 2555 days constraint"


@pytest.mark.asyncio
async def test_hard_delete_not_soft_delete(
    async_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
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
    old_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=60)
    question_id = old_question.id

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
    await async_session.flush()

    assert deleted_count == 1

    # Verify hard delete - question completely removed from database
    query = select(Questions).where(Questions.id == question_id)
    result = await async_session.execute(query)
    found = result.scalar_one_or_none()

    assert found is None, "Question should be permanently deleted (hard delete)"

    # Verify no deleted_at column exists (Questions table doesn't support soft delete)
    assert not hasattr(Questions, "deleted_at"), "Questions table should not have soft delete"


@pytest.mark.asyncio
async def test_tenant_level_retention_fallback_for_app_runs(
    async_session: AsyncSession,
    test_space: Spaces,
    test_app: Apps,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
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
    old_run = await create_old_app_run(async_session, app_id, tenant_id, user_id, completion_model_id, days_old=200)
    recent_run = await create_old_app_run(async_session, app_id, tenant_id, user_id, completion_model_id, days_old=100)

    # Run cleanup
    deleted_count = await retention_service.delete_old_app_runs()
    await async_session.flush()

    # Verify: old run deleted by tenant policy
    assert deleted_count == 1

    old_exists = await async_session.get(AppRuns, old_run.id)
    recent_exists = await async_session.get(AppRuns, recent_run.id)

    assert old_exists is None, "App run older than tenant retention should be deleted"
    assert recent_exists is not None, "App run within tenant retention should be kept"


@pytest.mark.asyncio
async def test_boundary_condition_exact_retention_days(
    async_session: AsyncSession,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
):
    """Test boundary condition: question exactly at retention boundary should NOT be deleted.

    The logic uses created_at < cutoff_date, so a question exactly at the boundary
    should be kept (not deleted). This tests the < vs <= boundary condition.
    """
    # Set assistant retention to 30 days
    test_assistant.data_retention_days = 30
    async_session.add(test_assistant)
    await async_session.flush()

    # Extract IDs
    assistant_id = test_assistant.id
    tenant_id = test_tenant.id
    user_id = admin_user.id

    # Create questions: one exactly at boundary (30 days), one just past (31 days)
    boundary_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=30)
    past_boundary_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=31)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
    await async_session.flush()

    # Verify: only question past boundary is deleted
    assert deleted_count == 1

    boundary_exists = await async_session.get(Questions, boundary_question.id)
    past_exists = await async_session.get(Questions, past_boundary_question.id)

    assert boundary_exists is not None, "Question exactly at 30 days should be kept (< not <=)"
    assert past_exists is None, "Question at 31 days should be deleted"


@pytest.mark.asyncio
async def test_tenant_enabled_but_days_null_keeps_forever(
    async_session: AsyncSession,
    test_space: Spaces,
    test_assistant: Assistants,
    test_tenant,
    admin_user,
    retention_service: DataRetentionService,
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
    old_question = await create_old_question(async_session, assistant_id, tenant_id, user_id, days_old=1000)

    # Run cleanup
    deleted_count = await retention_service.delete_old_questions()
    await async_session.flush()

    # Verify: nothing deleted (enabled=True but days=NULL means keep forever)
    assert deleted_count == 0

    exists = await async_session.get(Questions, old_question.id)
    assert exists is not None, "Question should be kept when tenant has enabled=True but days=NULL"
