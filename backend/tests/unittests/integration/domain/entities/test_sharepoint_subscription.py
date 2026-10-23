from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)


def _subscription(*, site_id: str, drive_id: str) -> SharePointSubscription:
    return SharePointSubscription(
        user_integration_id=uuid4(),
        site_id=site_id,
        subscription_id="graph-subscription",
        drive_id=drive_id,
        expires_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    ("site_id", "drive_id", "is_onedrive"),
    [
        pytest.param("b!drive", "b!drive", True, id="onedrive"),
        pytest.param("contoso.sharepoint.com,site,web", "b!drive", False, id="site"),
        pytest.param("", "", False, id="no-identifiers"),
    ],
)
def test_a_onedrive_subscription_stores_its_drive_as_its_site(
    site_id: str, drive_id: str, is_onedrive: bool
):
    subscription = _subscription(site_id=site_id, drive_id=drive_id)

    assert subscription.is_onedrive is is_onedrive
