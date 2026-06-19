from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from intric.audit.domain.actor_types import ActorType
from intric.authentication.auth_models import (
    ApiKeyPermission,
    ApiKeyScopeType,
    ServicePrincipalInDB,
    ServicePrincipalState,
)
from intric.authentication.principal_types import PrincipalType
from intric.flows.runtime.flow_run_actor import (
    FlowRunActor,
    FlowRunServicePrincipalInactiveError,
)


def _service_principal(
    user, *, state: ServicePrincipalState = ServicePrincipalState.ACTIVE
):
    return ServicePrincipalInDB(
        id=uuid4(),
        tenant_id=user.tenant_id,
        display_name="Runtime service",
        description=None,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        state=state,
        created_by_user_id=user.id,
    )


def _service_run(
    user,
    service_principal,
    *,
    actor_api_key_id=None,
    runtime_service_permission=ApiKeyPermission.WRITE,
):
    return SimpleNamespace(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=user.tenant_id,
        principal_type=PrincipalType.SERVICE_KEY.value,
        principal_user_id=None,
        principal_service_id=service_principal.id,
        created_by_api_key_id=actor_api_key_id,
        runtime_service_permission=runtime_service_permission,
    )


def test_user_actor_uses_user_audit_identity(user):
    actor = FlowRunActor.from_user(user=user)

    assert actor.principal.principal_type == PrincipalType.USER
    assert actor.audit_actor_fields() == {
        "actor_id": user.id,
        "actor_type": ActorType.USER,
        "actor_api_key_id": None,
    }


def test_service_principal_actor_uses_stable_owner_and_credential_audit_lineage(user):
    service_principal = _service_principal(user)
    actor_api_key_id = uuid4()
    run = _service_run(
        user,
        service_principal,
        actor_api_key_id=actor_api_key_id,
    )

    actor = FlowRunActor.from_service_principal_run(
        run=run,
        service_principal=service_principal,
    )

    assert actor.principal.principal_service_id == service_principal.id
    assert actor.principal.actor_api_key_id == actor_api_key_id
    assert actor.runtime_service_permission == ApiKeyPermission.WRITE
    assert actor.audit_actor_fields() == {
        "actor_id": None,
        "actor_type": ActorType.API_KEY,
        "actor_api_key_id": actor_api_key_id,
    }
    assert actor.audit_actor_snapshot() == {
        "type": "service_principal",
        "id": str(service_principal.id),
        "name": "Runtime service",
        "scope_type": "tenant",
        "scope_id": None,
        "actor_api_key_id": str(actor_api_key_id),
    }


def test_service_principal_actor_allows_recovered_run_without_exact_credential(user):
    service_principal = _service_principal(user)
    run = _service_run(user, service_principal, actor_api_key_id=None)

    actor = FlowRunActor.from_service_principal_run(
        run=run,
        service_principal=service_principal,
    )

    assert actor.principal.principal_service_id == service_principal.id
    assert actor.principal.actor_api_key_id is None
    assert actor.audit_actor_fields() == {
        "actor_id": None,
        "actor_type": ActorType.SYSTEM,
        "actor_api_key_id": None,
    }


def test_service_principal_actor_uses_persisted_runtime_permission(user):
    service_principal = _service_principal(user)
    run = _service_run(
        user,
        service_principal,
        actor_api_key_id=uuid4(),
        runtime_service_permission=ApiKeyPermission.READ,
    )

    actor = FlowRunActor.from_service_principal_run(
        run=run,
        service_principal=service_principal,
    )

    assert actor.runtime_service_permission == ApiKeyPermission.READ


def test_service_principal_actor_rejects_disabled_principal(user):
    service_principal = _service_principal(
        user,
        state=ServicePrincipalState.DISABLED,
    )
    run = _service_run(user, service_principal, actor_api_key_id=uuid4())

    with pytest.raises(FlowRunServicePrincipalInactiveError):
        FlowRunActor.from_service_principal_run(
            run=run,
            service_principal=service_principal,
        )
