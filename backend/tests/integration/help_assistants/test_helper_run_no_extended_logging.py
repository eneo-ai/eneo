"""Critical test #3 — helper runs never produce extended logging or insights.

Pins PRD §6 + "Critical tests #3": even if the helper assistant is mutated
to ``logging_enabled=True`` AND ``insight_enabled=True``, calling
``HelperRunService.run()`` must NOT:

  1. insert a row in the ``logging`` table for the helper's question, and
  2. surface the helper question via any insights aggregation query.

The third assertion confirms the orchestration produced a real ``help_assistant_runs``
row — without it, the first two assertions would be vacuously true.

Mutating the seeded defaults via direct DB writes (instead of going through
``OrgSpaceAssistantRoleService.update`` or the seed migration) ensures the
test exercises the **override** path, not the platform defaults. The
extended-logging block in ``HelperRunService.run`` is the only thing
between this configuration and a row in ``logging``.

The completion call is stubbed via monkeypatch — the assertion inside the
stub also catches any future regression that lets ``extended_logging`` leak
from the helper assistant's stored flag into the completion service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.spaces_table import Spaces
from eneo.help_assistants.domain.helper_kind import HelperKind


async def _get_org_space(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    row = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert row is not None, "Expected an org-space seeded by add_tenant_user"
    return row


async def _get_default_completion_model_id(
    session: sa.ext.asyncio.AsyncSession, *, tenant_id: UUID
) -> UUID:
    row = await session.scalar(
        sa.select(CompletionModels.id).where(
            CompletionModels.tenant_id == tenant_id,
            CompletionModels.is_enabled.is_(True),
        )
    )
    assert row is not None, "Expected seed_default_models to provide a model"
    return row


async def _insert_assistant(
    session: sa.ext.asyncio.AsyncSession,
    *,
    owner_user_id: UUID,
    space_id: UUID,
    completion_model_id: UUID,
    name: str,
    logging_enabled: bool = False,
    insight_enabled: bool = False,
) -> UUID:
    assistant_id = uuid4()
    await session.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name,
            user_id=owner_user_id,
            space_id=space_id,
            completion_model_id=completion_model_id,
            logging_enabled=logging_enabled,
            insight_enabled=insight_enabled,
            is_default=False,
            published=False,
        )
    )
    return assistant_id


async def _assign_helper_role(
    container,
    *,
    org_space_id: UUID,
    assistant_id: UUID,
    actor_user_id: UUID,
) -> None:
    role_repo = container.org_space_assistant_role_repo()
    factory = container.helper_assistants_factory()
    await role_repo.add(
        factory.create_role_assignment(
            org_space_id=org_space_id,
            kind=HelperKind.PROMPT_GUIDE,
            assistant_id=assistant_id,
            created_by_user_id=actor_user_id,
        )
    )


_STUB_ANSWER = "Helper would say something polite here."


def _stub_completion_response(
    *,
    model: Any,
    captured: dict[str, Any],
    **kwargs: Any,
) -> CompletionModelResponse:
    """Record kwargs and return a deterministic non-streaming response.

    Captures ``extended_logging`` so the test can assert it was ``False``
    even though the helper assistant's stored ``logging_enabled`` was
    forced to ``True``. The captured kwargs are checked once the run
    completes — failing the test loudly if a future refactor lets the
    helper's stored flag leak into the completion call.
    """

    captured["extended_logging"] = kwargs.get("extended_logging")
    captured["prompt"] = kwargs.get("prompt")
    captured["text_input"] = kwargs.get("text_input")
    captured["stream"] = kwargs.get("stream")

    completion_obj = Completion(text=_STUB_ANSWER)
    return CompletionModelResponse(
        completion=completion_obj,
        model=model,
        extended_logging=None,
        total_token_count=42,
        usage=None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_helper_run_does_not_produce_logging_or_insights(
    db_container, admin_user, monkeypatch
):
    """Mutate helper to logging+insight enabled, run, verify no leakage."""

    captured: dict[str, Any] = {}

    async def fake_get_response(self: CompletionService, **kwargs: Any):
        return _stub_completion_response(captured=captured, **kwargs)

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)

    helper_assistant_id: UUID
    target_assistant_id: UUID
    helper_run_session_id: UUID

    async with db_container() as container:
        session = container.session()
        # Mirror the production lazy-init: any admin entering a Help Assistant
        # surface triggers ``get_or_create_tenant_space``, which adds the
        # tenant's admins as org-space members. The test would otherwise hit
        # ``can_read_assistants`` → False before exercising the run path.
        space_service = container.space_service()
        await space_service.get_or_create_tenant_space()

        org_space_id = await _get_org_space(session, tenant_id=admin_user.tenant_id)
        completion_model_id = await _get_default_completion_model_id(
            session, tenant_id=admin_user.tenant_id
        )

        target_assistant_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            completion_model_id=completion_model_id,
            name="target-assistant",
        )
        # Mutate helper directly via insert with logging_enabled=True and
        # insight_enabled=True. This is the "override" the test pins —
        # the seed-default values are logging_enabled=False / insight_enabled=False,
        # so an admin (or DB poke) could push them either way. The contract is
        # that HelperRunService still hides this from logging and insights.
        helper_assistant_id = await _insert_assistant(
            session,
            owner_user_id=admin_user.id,
            space_id=org_space_id,
            completion_model_id=completion_model_id,
            name="prompt-guide-helper",
            logging_enabled=True,
            insight_enabled=True,
        )
        await _assign_helper_role(
            container,
            org_space_id=org_space_id,
            assistant_id=helper_assistant_id,
            actor_user_id=admin_user.id,
        )

        await session.flush()

        service = container.helper_run_service()
        result = await service.run(
            kind=HelperKind.PROMPT_GUIDE,
            target_type="assistant",
            target_id=target_assistant_id,
            question="Help me write a system prompt for a triage assistant.",
        )

        assert result.answer == _STUB_ANSWER
        assert result.run.assistant_id == helper_assistant_id
        assert result.run.target_id == target_assistant_id
        assert result.session.id is not None
        helper_run_session_id = result.session.id

    # The stub asserts extended_logging was False *during* the call.
    assert captured.get("extended_logging") is False, (
        "HelperRunService must hard-code extended_logging=False even when "
        "the helper assistant has logging_enabled=True"
    )
    assert captured.get("stream") is False

    # Reconnect to verify cross-table invariants on the same DB after the
    # run committed. We open a fresh container/session so we read what was
    # actually persisted, not what's still cached in the previous session.
    async with db_container() as container:
        session = container.session()

        logging_count = await session.scalar(sa.text("SELECT COUNT(*) FROM logging"))
        assert logging_count == 0, (
            f"Helper run leaked into `logging` table: {logging_count} row(s)"
        )

        helper_runs_count = await session.scalar(
            sa.select(sa.func.count(HelpAssistantRuns.id)).where(
                HelpAssistantRuns.session_id == helper_run_session_id
            )
        )
        assert helper_runs_count == 1, (
            f"help_assistant_runs should have 1 row for the helper session, "
            f"got {helper_runs_count}"
        )

        # The insights query must NOT surface the helper question. The
        # ``_exclude_helper_run_sessions`` filter (step 013) is what makes
        # this true; here we re-prove it end-to-end after a real run.
        analysis_repo = container.analysis_repo()
        from_date = datetime.now(timezone.utc) - timedelta(days=1)
        to_date = datetime.now(timezone.utc) + timedelta(days=1)
        (
            items,
            total_count,
            has_more,
        ) = await analysis_repo.get_assistant_question_history_page(
            assistant_id=helper_assistant_id,
            from_date=from_date,
            to_date=to_date,
            include_followups=True,
            tenant_id=admin_user.tenant_id,
            limit=50,
        )
        assert items == [], "Helper question must not appear in insights history page"
        assert total_count == 0
        assert has_more is False

        texts = await analysis_repo.get_assistant_question_texts_since(
            assistant_id=helper_assistant_id,
            from_date=from_date,
            to_date=to_date,
            include_followups=True,
            tenant_id=admin_user.tenant_id,
        )
        assert texts == [], (
            "Helper question must not appear in question-texts aggregation"
        )
