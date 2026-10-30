"""AuditService records who acted once, when the event happens, and never replaces it."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType

pytestmark = pytest.mark.asyncio


def _user() -> Any:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        username="anna",
        email="anna@example.org",
        active_api_key=None,
    )


def _service_key_user() -> Any:
    key = SimpleNamespace(
        id=uuid4(), name="Ingest key", key_prefix="sk_ab", ownership="service"
    )
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        username="Service Key (Ingest key)",
        email="sk-xxxx@service.key",
        active_api_key=key,
    )


def _event() -> dict[str, Any]:
    return {
        "tenant_id": uuid4(),
        "action": ActionType.FLOW_DELETED,
        "entity_type": EntityType.FLOW,
        "entity_id": uuid4(),
        "description": "Deleted flow",
    }


async def _logged_metadata(**kwargs: Any) -> dict[str, Any]:
    repository = AsyncMock()
    await AuditService(repository).log(**_event(), **kwargs)
    return repository.create.call_args.args[0].metadata


async def _enqueued_metadata(**kwargs: Any) -> dict[str, Any]:
    with patch("eneo.audit.application.audit_service.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock()
        await AuditService(AsyncMock()).log_async(**_event(), **kwargs)
    return job_manager.enqueue.call_args.args[2]["metadata"]


@pytest.mark.parametrize("write", [_logged_metadata, _enqueued_metadata])
async def test_user_event_records_the_user_at_the_time(write) -> None:
    user = _user()
    caller_metadata: dict[str, Any] = {"target": {"id": "t"}}

    metadata = await write(user=user, metadata=caller_metadata)

    assert metadata == {
        "target": {"id": "t"},
        "actor": {
            "type": "user",
            "id": str(user.id),
            "name": "anna",
            "email": "anna@example.org",
        },
    }
    assert caller_metadata == {"target": {"id": "t"}}


@pytest.mark.parametrize("write", [_logged_metadata, _enqueued_metadata])
async def test_service_key_event_records_the_key_not_the_synthetic_user(
    write,
) -> None:
    user = _service_key_user()

    metadata = await write(user=user, metadata={})

    assert metadata["actor"] == {
        "type": "service_key",
        "id": str(user.active_api_key.id),
        "name": "Ingest key",
        "key_prefix": "sk_ab",
    }


@pytest.mark.parametrize("write", [_logged_metadata, _enqueued_metadata])
async def test_system_event_records_a_system_actor(write) -> None:
    metadata = await write(actor_type=ActorType.SYSTEM, metadata={})

    assert metadata["actor"] == {"type": "system", "via": "flow_deleted"}


@pytest.mark.parametrize("write", [_logged_metadata, _enqueued_metadata])
@pytest.mark.parametrize(
    "existing",
    [
        {"type": "user", "id": "u1", "name": "At the time"},
        {"id": "u1"},
        {},
        None,
        "not a mapping",
    ],
)
async def test_an_existing_actor_block_is_never_replaced(write, existing) -> None:
    metadata = await write(user=_user(), metadata={"actor": existing})

    assert metadata == {"actor": existing}


@pytest.mark.parametrize("write", [_logged_metadata, _enqueued_metadata])
async def test_an_actor_id_without_a_user_records_no_guessed_actor(write) -> None:
    metadata = await write(actor_id=uuid4(), metadata={"target": {"id": "t"}})

    assert "actor" not in metadata
