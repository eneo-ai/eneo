# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.roles.permissions import Permission
from intric.security_classifications.application.security_classification_service import (
    SecurityClassificationService,
)
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from intric.tenants.tenant import TenantInDB


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def user(tenant_id):
    user = MagicMock()
    user.tenant_id = tenant_id
    tenant = TenantInDB(
        id=tenant_id, name="Test Tenant", quota_limit=1000000, security_enabled=False
    )
    user.tenant = tenant
    # Add admin permission
    user.permissions = [Permission.ADMIN]
    return user


@pytest.fixture
def user_without_permissions(tenant_id):
    user = MagicMock()
    user.tenant_id = tenant_id
    tenant = TenantInDB(
        id=tenant_id, name="Test Tenant", quota_limit=1000000, security_enabled=False
    )
    user.tenant = tenant
    # No admin permission
    user.permissions = []
    return user


@pytest.fixture
def security_repo():
    return AsyncMock()


@pytest.fixture
def tenant_service():
    service = AsyncMock()
    return service


@pytest.fixture
def service(user, security_repo, tenant_service):
    return SecurityClassificationService(
        user=user,
        repo=security_repo,
        tenant_service=tenant_service,
    )


@pytest.fixture
def service_without_permissions(user_without_permissions, security_repo, tenant_service):
    return SecurityClassificationService(
        user=user_without_permissions,
        repo=security_repo,
        tenant_service=tenant_service,
    )


class TestSecurityClassificationService:
    async def test_update_security_levels(self, service, tenant_id):
        # Given the tenant has security_enabled=True
        service.user.tenant.security_enabled = True

        # Create test classifications
        sc1 = SecurityClassification(
            id=uuid.uuid4(), tenant_id=tenant_id, name="Classification 1", security_level=0
        )
        sc2 = SecurityClassification(
            id=uuid.uuid4(), tenant_id=tenant_id, name="Classification 2", security_level=1
        )
        sc3 = SecurityClassification(
            id=uuid.uuid4(), tenant_id=tenant_id, name="Classification 3", security_level=2
        )

        # Configure repo mock to return all classifications
        service.repo.all.return_value = [sc1, sc2, sc3]

        # Configure repo to return updated objects
        def mock_update(sc):
            # Return the updated object with the same ID
            return sc

        service.repo.update.side_effect = mock_update

        # Reorder classifications by providing just the IDs: 3, 1, 2
        model_ids = [sc3.id, sc1.id, sc2.id]

        # When updating security levels
        result = await service.update_security_levels(security_classifications=model_ids)

        # Then the security levels should be updated based on new order
        assert len(result) == 3
        assert result[0].id == sc3.id
        assert result[0].security_level == 0
        assert result[1].id == sc1.id
        assert result[1].security_level == 1
        assert result[2].id == sc2.id
        assert result[2].security_level == 2

        # And repo.update should be called for each classification
        assert service.repo.update.call_count == 3

    async def test_update_security_levels_with_nonexistent_id(self, service):
        # Given the tenant has security_enabled=True
        service.user.tenant.security_enabled = True

        # And some existing classifications
        sc1 = SecurityClassification(
            id=uuid.uuid4(),
            tenant_id=service.user.tenant_id,
            name="Classification 1",
            security_level=0,
        )
        service.repo.all.return_value = [sc1]

        # When trying to update with a non-existent ID
        with pytest.raises(NotFoundException) as excinfo:
            await service.update_security_levels(security_classifications=[uuid.uuid4()])

        # Then a NotFoundException should be raised
        assert "not found" in str(excinfo.value)

        # And no updates should be performed
        service.repo.update.assert_not_called()

    async def test_toggle_security_enabled_to_true(self, service, user, tenant_service, tenant_id):
        # Given the tenant has security_enabled=False (set in fixture)
        # And the tenant_service toggle_security method returns a tenant with security_enabled=True
        updated_tenant = TenantInDB(
            id=tenant_id, name="Test Tenant", quota_limit=1000000, security_enabled=True
        )
        tenant_service.toggle_security.return_value = updated_tenant

        # When toggling security to enabled
        result = await service.toggle_security_on_tenant(True)

        # Then tenant_service.toggle_security should be called with correct parameters
        tenant_service.toggle_security.assert_called_once_with(
            tenant_id=tenant_id, enabled=True
        )

        # And the result should be the updated tenant with security_enabled=True
        assert result.security_enabled is True

    async def test_toggle_security_enabled_to_false(self, service, user, tenant_service, tenant_id):
        # Given the tenant has security_enabled=True
        user.tenant.security_enabled = True

        # And the tenant_service toggle_security method returns a tenant with security_enabled=False
        updated_tenant = TenantInDB(
            id=tenant_id,
            name="Test Tenant",
            quota_limit=1000000,
            security_enabled=False,
        )
        tenant_service.toggle_security.return_value = updated_tenant

        # When toggling security to disabled
        result = await service.toggle_security_on_tenant(False)

        # Then tenant_service.toggle_security should be called with correct parameters
        tenant_service.toggle_security.assert_called_once_with(
            tenant_id=tenant_id, enabled=False
        )

        # And the result should be the updated tenant with security_enabled=False
        assert result.security_enabled is False

    async def test_toggle_security_without_required_permission(
        self, service_without_permissions, tenant_service, tenant_id
    ):
        # Given a user without admin permissions
        # When trying to toggle security settings
        # Then an UnauthorizedException should be raised
        with pytest.raises(UnauthorizedException) as excinfo:
            await service_without_permissions.toggle_security_on_tenant(True)

        # And the error message should indicate that admin permission is required
        assert "Need permission admin in order to access" in str(excinfo.value)

        # And no tenant update should have been attempted
        tenant_service.toggle_security.assert_not_called()
