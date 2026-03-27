from uuid import uuid4

import pytest

from eneo.feature_flag.feature_flag import FeatureFlag


@pytest.fixture
def feature_flag():
    return FeatureFlag(name="test_feature", feature_id=uuid4(), tenant_ids=set())


async def test_feature_update_tenant(feature_flag: FeatureFlag):
    tenant_id = "fake-tenant-id"
    feature_flag.enable_tenant(tenant_id=tenant_id)
    assert tenant_id in feature_flag.tenant_ids

    feature_flag.disable_tenant(tenant_id=tenant_id)
    assert tenant_id not in feature_flag.tenant_ids
