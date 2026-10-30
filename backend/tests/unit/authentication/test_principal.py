from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.audit.domain.actor_types import ActorType
from eneo.authentication.principal import Principal
from eneo.authentication.principal_types import PrincipalType


def test_user_principal_maps_to_tenant_scoped_file_owner() -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    principal = Principal(
        principal_type=PrincipalType.USER,
        principal_user_id=user_id,
    )

    owner = principal.file_owner(tenant_id=tenant_id)

    assert owner.tenant_id == tenant_id
    assert owner.owner_type is PrincipalType.USER
    assert owner.owner_user_id == user_id
    assert owner.owner_service_id is None
    assert principal.audit_actor_fields() == {
        "actor_id": user_id,
        "actor_type": ActorType.USER,
        "actor_api_key_id": None,
    }


def test_service_principal_keeps_stable_owner_separate_from_rotating_key() -> None:
    service_id = uuid4()
    api_key_id = uuid4()
    tenant_id = uuid4()
    principal = Principal(
        principal_type=PrincipalType.SERVICE_KEY,
        principal_service_id=service_id,
        actor_api_key_id=api_key_id,
    )

    owner = principal.file_owner(tenant_id=tenant_id)

    assert owner.owner_service_id == service_id
    assert owner.owner_user_id is None
    assert principal.audit_actor_fields() == {
        "actor_id": None,
        "actor_type": ActorType.API_KEY,
        "actor_api_key_id": api_key_id,
    }


def test_principal_owner_match_is_bound_to_stable_identity() -> None:
    service_id = uuid4()
    snapshot = SimpleNamespace(
        principal_type=PrincipalType.SERVICE_KEY,
        principal_user_id=None,
        principal_service_id=service_id,
        created_by_api_key_id=uuid4(),
    )

    assert Principal(
        principal_type=PrincipalType.SERVICE_KEY,
        principal_service_id=service_id,
    ).matches_owner_snapshot(snapshot)
    assert not Principal(
        principal_type=PrincipalType.SERVICE_KEY,
        principal_service_id=uuid4(),
    ).matches_owner_snapshot(snapshot)


def test_file_ownership_rejects_same_principal_from_another_tenant() -> None:
    tenant_id = uuid4()
    principal = Principal(
        principal_type=PrincipalType.SERVICE_KEY,
        principal_service_id=uuid4(),
    )
    owner = principal.file_owner(tenant_id=tenant_id)

    assert principal.owns_file(owner, tenant_id=tenant_id)
    assert not principal.owns_file(owner, tenant_id=uuid4())


@pytest.mark.parametrize(
    ("principal_type", "user_id", "service_id", "api_key_id"),
    [
        (PrincipalType.USER, None, None, None),
        (PrincipalType.SERVICE_KEY, None, None, None),
        (PrincipalType.USER, uuid4(), uuid4(), None),
        (PrincipalType.USER, uuid4(), None, uuid4()),
    ],
)
def test_invalid_principal_shapes_are_rejected(
    principal_type: PrincipalType,
    user_id: UUID | None,
    service_id: UUID | None,
    api_key_id: UUID | None,
) -> None:
    with pytest.raises(ValueError):
        Principal(
            principal_type=principal_type,
            principal_user_id=user_id,
            principal_service_id=service_id,
            actor_api_key_id=api_key_id,
        )
