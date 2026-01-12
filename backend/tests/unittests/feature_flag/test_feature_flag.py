from uuid import uuid4

import pytest

from intric.feature_flag.feature_flag import FeatureFlag


@pytest.fixture
def feature_flag():
    return FeatureFlag(name="test_feature", feature_id=uuid4(), tenant_ids=set())


async def test_feature_update_tenant(feature_flag: FeatureFlag):
    tenant_id = "fake-tenant-id"
    feature_flag.enable_tenant(tenant_id=tenant_id)
    assert tenant_id in feature_flag.tenant_ids

    feature_flag.disable_tenant(tenant_id=tenant_id)
    assert tenant_id not in feature_flag.tenant_ids


async def test_disable_tenant_is_idempotent(feature_flag: FeatureFlag):
    """Test that disabling a tenant that was never enabled doesn't raise an error.

    This is a regression test for the 500 error when toggling templates off
    for a tenant that never had them enabled.
    """
    tenant_id = "never-enabled-tenant"

    # Tenant was never enabled - this should NOT raise KeyError
    feature_flag.disable_tenant(tenant_id=tenant_id)
    assert tenant_id not in feature_flag.tenant_ids

    # Calling disable again should also be safe (idempotent)
    feature_flag.disable_tenant(tenant_id=tenant_id)
    assert tenant_id not in feature_flag.tenant_ids


async def test_enable_tenant_is_idempotent(feature_flag: FeatureFlag):
    """Test that enabling a tenant multiple times is safe."""
    tenant_id = "test-tenant"

    feature_flag.enable_tenant(tenant_id=tenant_id)
    assert tenant_id in feature_flag.tenant_ids

    # Enabling again should be safe (idempotent)
    feature_flag.enable_tenant(tenant_id=tenant_id)
    assert tenant_id in feature_flag.tenant_ids
    assert len(feature_flag.tenant_ids) == 1  # Still only one entry
