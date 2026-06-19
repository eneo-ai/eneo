from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.application.flow_classification_retention_policy_service import (
    FlowClassificationRetentionPolicyService,
)
from intric.flows.domain.flow_classification_retention_policy import (
    FlowClassificationRetentionPolicy,
)
from intric.main.exceptions import NotFoundException
from intric.roles.permissions import Permission


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.ADMIN],
    )


def _service(repo: AsyncMock, audit_service: AsyncMock):
    return FlowClassificationRetentionPolicyService(
        user=_user(),
        repo=repo,
        audit_service=audit_service,
    )


@pytest.mark.asyncio
async def test_set_policy_requires_tenant_security_classification() -> None:
    repo = AsyncMock()
    repo.security_classification_exists.return_value = False
    audit_service = AsyncMock()
    service = _service(repo, audit_service)

    with pytest.raises(NotFoundException):
        await service.set_policy(
            security_classification_id=uuid4(),
            data_retention_days=7,
        )

    repo.upsert.assert_not_awaited()
    audit_service.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_policy_upserts_and_audits_change() -> None:
    classification_id = uuid4()
    repo = AsyncMock()
    repo.security_classification_exists.return_value = True
    repo.get.return_value = FlowClassificationRetentionPolicy(
        tenant_id=uuid4(),
        security_classification_id=classification_id,
        data_retention_days=30,
    )
    repo.upsert.return_value = FlowClassificationRetentionPolicy(
        tenant_id=uuid4(),
        security_classification_id=classification_id,
        data_retention_days=7,
    )
    audit_service = AsyncMock()
    service = _service(repo, audit_service)

    updated = await service.set_policy(
        security_classification_id=classification_id,
        data_retention_days=7,
    )

    assert updated.data_retention_days == 7
    repo.upsert.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
    metadata = audit_service.log_async.await_args.kwargs["metadata"]
    assert metadata["setting"] == "flow_classification_retention_policy"
    assert metadata["security_classification_id"] == str(classification_id)
    assert metadata["changes"]["data_retention_days"] == {
        "old": 30,
        "new": 7,
    }


@pytest.mark.asyncio
async def test_delete_policy_is_idempotent_for_existing_classification() -> None:
    classification_id = uuid4()
    repo = AsyncMock()
    repo.security_classification_exists.return_value = True
    repo.get.return_value = None
    repo.delete.return_value = False
    audit_service = AsyncMock()
    service = _service(repo, audit_service)

    await service.delete_policy(security_classification_id=classification_id)

    repo.delete.assert_awaited_once()
    audit_service.log_async.assert_awaited_once()
    metadata = audit_service.log_async.await_args.kwargs["metadata"]
    assert metadata["security_classification_id"] == str(classification_id)
    assert metadata["deleted"] is False
    assert metadata["old_data_retention_days"] is None
