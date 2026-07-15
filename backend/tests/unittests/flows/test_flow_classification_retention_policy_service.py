from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.data_retention.infrastructure.data_retention_service import (
    FlowRetentionClassificationChangeDecision,
    FlowRetentionClassificationProposal,
)
from eneo.flows.application.flow_classification_retention_policy_service import (
    FlowClassificationRetentionPolicyService,
)
from eneo.flows.domain.flow_classification_retention_policy import (
    FlowClassificationRetentionPolicy,
)
from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.ADMIN],
    )


def _service(
    repo: AsyncMock,
    audit_service: AsyncMock,
    data_retention_service: AsyncMock | None = None,
):
    return FlowClassificationRetentionPolicyService(
        user=_user(),
        repo=repo,
        audit_service=audit_service,
        data_retention_service=data_retention_service or AsyncMock(),
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
            minimum_retention_days=None,
            no_purge=False,
            confirmation=None,
        )

    repo.upsert.assert_not_awaited()
    audit_service.log.assert_not_awaited()


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
    data_retention_service = AsyncMock()
    data_retention_service.prepare_flow_retention_classification_change.return_value = (
        FlowRetentionClassificationChangeDecision(
            old_policy=FlowRetentionClassificationProposal(
                security_classification_id=classification_id,
                data_retention_days=30,
            ),
            new_policy=FlowRetentionClassificationProposal(
                security_classification_id=classification_id,
                data_retention_days=7,
            ),
            destructive_change=True,
            preview=None,
        )
    )
    service = _service(repo, audit_service, data_retention_service)

    updated = await service.set_policy(
        security_classification_id=classification_id,
        data_retention_days=7,
        minimum_retention_days=None,
        no_purge=False,
        confirmation=None,
    )

    assert updated.data_retention_days == 7
    repo.upsert.assert_awaited_once()
    audit_service.log.assert_awaited_once()
    metadata = audit_service.log.await_args.kwargs["metadata"]
    assert set(metadata) == {"old_policy", "new_policy", "preview", "activation"}
    assert metadata["old_policy"]["data_retention_days"] == 30
    assert metadata["new_policy"]["data_retention_days"] == 7
    assert metadata["preview"] is None


@pytest.mark.asyncio
async def test_all_off_desired_state_deletes_through_confirmed_put() -> None:
    classification_id = uuid4()
    repo = AsyncMock()
    repo.security_classification_exists.return_value = True
    audit_service = AsyncMock()
    data_retention_service = AsyncMock()
    data_retention_service.prepare_flow_retention_classification_change.return_value = (
        FlowRetentionClassificationChangeDecision(
            old_policy=FlowRetentionClassificationProposal(
                security_classification_id=classification_id,
                data_retention_days=30,
            ),
            new_policy=FlowRetentionClassificationProposal(
                security_classification_id=classification_id,
                data_retention_days=None,
            ),
            destructive_change=True,
            preview=None,
        )
    )
    service = _service(repo, audit_service, data_retention_service)

    updated = await service.set_policy(
        security_classification_id=classification_id,
        data_retention_days=None,
        minimum_retention_days=None,
        no_purge=False,
        confirmation=None,
    )

    assert updated is None
    repo.delete.assert_awaited_once()
    repo.upsert.assert_not_awaited()
    audit_service.log.assert_awaited_once()
    metadata = audit_service.log.await_args.kwargs["metadata"]
    assert set(metadata) == {"old_policy", "new_policy", "preview", "activation"}
    assert metadata["old_policy"]["security_classification_id"] == str(
        classification_id
    )
    assert metadata["new_policy"] is None
    assert metadata["activation"]["destructive_change"] is True
