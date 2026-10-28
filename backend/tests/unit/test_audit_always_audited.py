"""A federation change is audited whatever the tenant's audit configuration says.

A tenant admin can switch off audit categories, single actions and the whole
audit log; none of those may hide a change to how the organisation signs in.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.audit.application.audit_config_service import AuditConfigService
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ALWAYS_AUDITED_ACTIONS, ActionType
from eneo.audit.schemas.audit_config_schemas import ActionUpdate


def test_federation_updated_is_always_audited():
    assert ActionType.FEDERATION_UPDATED in ALWAYS_AUDITED_ACTIONS


@pytest.mark.asyncio
async def test_switched_off_audit_still_logs_federation_changes():
    flags = AsyncMock()
    flags.check_is_feature_enabled.return_value = False
    config = AsyncMock()
    config.is_action_enabled.return_value = False
    service = AuditService(
        AsyncMock(), audit_config_service=config, feature_flag_service=flags
    )

    assert await service._should_log_action(uuid4(), ActionType.FEDERATION_UPDATED)
    assert not await service._should_log_action(uuid4(), ActionType.USER_CREATED)
    flags.check_is_feature_enabled.assert_awaited_once()


@pytest.fixture
def config_service():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    with patch(
        "eneo.audit.application.audit_config_service.get_redis", return_value=redis
    ):
        yield AuditConfigService(AsyncMock())


@pytest.mark.asyncio
async def test_the_config_api_does_not_store_an_override_that_disables_it(
    config_service: AuditConfigService,
):
    repository = config_service.repository
    repository.find_by_tenant_and_category.return_value = None
    repository.find_all_by_tenant.return_value = [
        ("admin_actions", False, {"federation_updated": False})
    ]

    response = await config_service.update_action_config(
        uuid4(),
        [
            ActionUpdate(action="federation_updated", enabled=False),
            ActionUpdate(action="user_created", enabled=False),
        ],
    )

    stored = repository.update.await_args.args[3]
    assert stored == {"user_created": False}
    federation = next(a for a in response.actions if a.action == "federation_updated")
    assert federation.enabled is True
