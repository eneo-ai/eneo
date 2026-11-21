"""Publishing an assistant is refused or applied, audited with the calling
user as actor and followed up, the same way for every caller."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.assistants.application import assistant_publish_operation
from eneo.assistants.application.assistant_publish_operation import (
    apply_assistant_publish,
)
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import ApiKeyNotificationTargetType
from eneo.main.exceptions import NotFoundException, UnauthorizedException


def _context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    helper_chat_owner_id: UUID | None = None,
    refusal: Exception | None = None,
    follow: AsyncMock | None = None,
) -> SimpleNamespace:
    assistant_id = uuid4()
    space_id = uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        active_api_key=None,
        username="admin",
        email="admin@example.com",
    )
    permissions = ["read", "publish"]

    async def publish(*, assistant_id: UUID, publish: bool):
        if refusal is not None:
            raise refusal
        return (
            SimpleNamespace(
                id=assistant_id,
                name="Ärendehjälpen",
                space_id=space_id,
                published=publish,
            ),
            permissions,
        )

    service = SimpleNamespace(
        helper_chat_owner_id=AsyncMock(return_value=helper_chat_owner_id),
        publish_assistant=AsyncMock(side_effect=publish),
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())
    session = object()
    container: Any = SimpleNamespace(
        assistant_service=lambda: service,
        user=lambda: user,
        space_service=lambda: SimpleNamespace(
            get_space=AsyncMock(return_value=SimpleNamespace(id=space_id, name="Space"))
        ),
        audit_service=lambda: audit_service,
        session=lambda: session,
    )
    follow = follow or AsyncMock()
    monkeypatch.setattr(assistant_publish_operation, "auto_follow_on_publish", follow)
    return SimpleNamespace(
        assistant_id=assistant_id,
        user=user,
        service=service,
        audit_service=audit_service,
        container=container,
        session=session,
        follow=follow,
        permissions=permissions,
    )


@pytest.mark.parametrize("published", [True, False])
async def test_the_entry_names_the_calling_user_and_what_was_done(
    monkeypatch: pytest.MonkeyPatch, published: bool
):
    ctx = _context(monkeypatch)

    applied = await apply_assistant_publish(
        ctx.container, assistant_id=ctx.assistant_id, published=published
    )

    ctx.service.publish_assistant.assert_awaited_once_with(
        assistant_id=ctx.assistant_id, publish=published
    )
    ctx.audit_service.log_async.assert_awaited_once()
    entry = ctx.audit_service.log_async.await_args.kwargs
    assert entry["action"] == ActionType.ASSISTANT_PUBLISHED
    assert entry["entity_type"] == EntityType.ASSISTANT
    assert entry["entity_id"] == ctx.assistant_id
    assert entry["tenant_id"] == ctx.user.tenant_id
    assert entry["user"] is ctx.user
    assert entry["description"] == (
        f"{'Published' if published else 'Unpublished'} assistant 'Ärendehjälpen'"
    )
    assert entry["metadata"]["actor"]["id"] == str(ctx.user.id)
    assert entry["metadata"]["extra"] == {
        "published": published,
        "action": "published" if published else "unpublished",
    }
    assert applied.assistant.published is published
    assert applied.permissions is ctx.permissions


async def test_the_entry_extra_carries_the_audit_context_given(
    monkeypatch: pytest.MonkeyPatch,
):
    ctx = _context(monkeypatch)

    await apply_assistant_publish(
        ctx.container,
        assistant_id=ctx.assistant_id,
        published=True,
        audit_context={"origin": "helper_chat", "session_id": "a-session"},
    )

    extra = ctx.audit_service.log_async.await_args.kwargs["metadata"]["extra"]
    assert extra == {
        "published": True,
        "action": "published",
        "origin": "helper_chat",
        "session_id": "a-session",
    }


async def test_publishing_follows_the_api_key_notifications_and_unpublishing_does_not(
    monkeypatch: pytest.MonkeyPatch,
):
    ctx = _context(monkeypatch)

    await apply_assistant_publish(
        ctx.container, assistant_id=ctx.assistant_id, published=True
    )
    ctx.follow.assert_awaited_once_with(
        session=ctx.session,
        user=ctx.user,
        target_type=ApiKeyNotificationTargetType.ASSISTANT,
        target_id=ctx.assistant_id,
    )

    ctx.follow.reset_mock()
    await apply_assistant_publish(
        ctx.container, assistant_id=ctx.assistant_id, published=False
    )
    ctx.follow.assert_not_awaited()


async def test_a_failed_follow_up_is_logged_and_the_publishing_stands(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    ctx = _context(monkeypatch, follow=AsyncMock(side_effect=RuntimeError("down")))

    applied = await apply_assistant_publish(
        ctx.container, assistant_id=ctx.assistant_id, published=True
    )

    assert applied.assistant.published is True
    ctx.audit_service.log_async.assert_awaited_once()
    assert "Failed to auto-follow API key expiry notifications" in caplog.text


async def test_a_refused_publishing_writes_no_entry(monkeypatch: pytest.MonkeyPatch):
    ctx = _context(
        monkeypatch,
        refusal=UnauthorizedException(
            "Publishing assistants is not allowed for your current space role."
        ),
    )

    with pytest.raises(UnauthorizedException):
        await apply_assistant_publish(
            ctx.container, assistant_id=ctx.assistant_id, published=True
        )

    ctx.audit_service.log_async.assert_not_awaited()
    ctx.follow.assert_not_awaited()


async def test_another_persons_helper_chat_assistant_is_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch,
):
    ctx = _context(monkeypatch, helper_chat_owner_id=uuid4())

    with pytest.raises(NotFoundException):
        await apply_assistant_publish(
            ctx.container, assistant_id=ctx.assistant_id, published=True
        )

    ctx.service.publish_assistant.assert_not_awaited()
    ctx.audit_service.log_async.assert_not_awaited()
    ctx.follow.assert_not_awaited()
