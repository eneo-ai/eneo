"""Unit tests for the config-capability registry + runner (Phase 2)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.config_capabilities import CAPABILITY_REGISTRY
from intric.config_capabilities.capability import (
    CapabilityContext,
    CapabilityResult,
    ConfigCapability,
    Scope,
)
from intric.config_capabilities.context import run_capability
from intric.main.exceptions import UnauthorizedException


class _Input(BaseModel):
    pass


def _ctx(actor, audit_service=None):
    container = MagicMock()
    container.actor_manager.return_value.get_space_actor_from_space.return_value = actor
    container.audit_service.return_value = audit_service or AsyncMock()
    return CapabilityContext(
        container=container,
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
        space=MagicMock(),
        assistant_id=uuid4(),
        lang="en",
    )


def _cap(handler, *, permission, mutating=True):
    return ConfigCapability(
        id="test.cap",
        scope=Scope.ASSISTANT,
        input_model=_Input,
        permission=permission,
        handler=handler,
        title_en="Test",
        description="Test capability.",
        mutating=mutating,
        audit_action=ActionType.ASSISTANT_UPDATED,
        audit_entity=EntityType.ASSISTANT,
    )


def test_registry_has_expected_capabilities():
    expected = {
        "assistant.get_settings",
        "assistant.set_name",
        "assistant.set_knowledge",
        "collection.create",
        "website.create",
        "space.list_collections",
    }
    assert expected.issubset(set(CAPABILITY_REGISTRY))


@pytest.mark.asyncio
async def test_run_capability_denies_without_permission():
    handler = AsyncMock()
    cap = _cap(handler, permission=lambda actor: False)
    with pytest.raises(UnauthorizedException):
        await run_capability(cap, _ctx(MagicMock()), _Input())
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_capability_runs_and_audits_on_success():
    eid = uuid4()
    handler = AsyncMock(return_value=CapabilityResult(summary="done", entity_id=eid))
    audit = AsyncMock()
    cap = _cap(handler, permission=lambda actor: True)
    ctx = _ctx(MagicMock(), audit_service=audit)

    result = await run_capability(cap, ctx, _Input())

    assert result.entity_id == eid
    handler.assert_awaited_once()
    audit.log_async.assert_awaited_once()
    assert audit.log_async.await_args.kwargs["action"] == ActionType.ASSISTANT_UPDATED


@pytest.mark.asyncio
async def test_run_capability_audits_failure():
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    audit = AsyncMock()
    cap = _cap(handler, permission=lambda actor: True)
    ctx = _ctx(MagicMock(), audit_service=audit)

    with pytest.raises(RuntimeError):
        await run_capability(cap, ctx, _Input())

    audit.log_async.assert_awaited_once()
    assert audit.log_async.await_args.kwargs["outcome"].value == "failure"
