"""The tenant-model audit helper lets the audit service derive the actor.

A service key authenticates as a synthetic user whose id is no ``users`` row,
so the helper must hand the user over rather than its id: the audit service
turns a service key into the system actor and a real user into itself.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.tenant_models.application.tenant_model_service import _audit


async def test_audit_passes_the_user_and_never_an_actor_id():
    audit_service = MagicMock()
    audit_service.log_async = AsyncMock()
    user = MagicMock(id=uuid4(), tenant_id=uuid4())
    target = MagicMock(id=uuid4(), name="gpt-image-1")

    await _audit(
        audit_service,
        user=user,
        action=ActionType.IMAGE_MODEL_CREATED,
        entity_type=EntityType.IMAGE_MODEL,
        target=target,
        description="Created tenant image model gpt-image-1",
    )

    kwargs = audit_service.log_async.await_args.kwargs
    assert kwargs["user"] is user
    assert kwargs["tenant_id"] == user.tenant_id
    assert "actor_id" not in kwargs
    assert kwargs["entity_id"] == target.id


async def test_audit_is_a_no_op_without_an_audit_service():
    await _audit(
        None,
        user=MagicMock(),
        action=ActionType.IMAGE_MODEL_DELETED,
        entity_type=EntityType.IMAGE_MODEL,
        target=MagicMock(),
        description="unused",
    )
