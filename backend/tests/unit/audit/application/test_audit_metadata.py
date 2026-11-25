from types import SimpleNamespace
from uuid import uuid4

from eneo.audit.application.audit_metadata import AuditMetadata


def test_a_space_running_its_own_work_is_named_as_the_space() -> None:
    """Scheduled work has no person and no key behind it, so the entry names
    the space instead of a key that does not exist."""
    space_id = uuid4()
    scope = SimpleNamespace(
        id=space_id, name="Economy", ownership="service", key_prefix="space"
    )
    actor = SimpleNamespace(
        id=space_id,
        acting_space_id=space_id,
        active_api_key=scope,
        username="Space (Economy)",
        email="space-0000@space.actor",
    )

    assert AuditMetadata.actor(actor) == {
        "type": "space",
        "id": str(space_id),
        "name": "Economy",
    }


def test_a_service_key_is_named_by_its_key() -> None:
    key = SimpleNamespace(
        id=uuid4(), name="Invoice reader", ownership="service", key_prefix="sk_"
    )
    actor = SimpleNamespace(id=key.id, active_api_key=key, acting_space_id=None)

    assert AuditMetadata.actor(actor) == {
        "type": "service_key",
        "id": str(key.id),
        "name": "Invoice reader",
        "key_prefix": "sk_",
    }
