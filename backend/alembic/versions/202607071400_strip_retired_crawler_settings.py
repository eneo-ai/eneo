"""strip retired crawler settings from tenant rows

Revision ID: 202607071400
Revises: 728087c4649a
Create Date: 2026-07-07 14:00:00.000000

The keys dns_timeout, retry_times, obey_robots and autothrottle_enabled were
crawler settings for the old in-process Scrapy crawler. They have been removed
from CRAWLER_SETTING_SPECS, so any tenants.crawler_settings row that still holds
them would fail TenantInDB validation on load. This migration drops those keys
from storage. The read-path validator also tolerates them, so tenants keep
working during a rolling upgrade regardless of migration ordering.
"""

from alembic import op

revision = "202607071400"
down_revision = "728087c4649a"
branch_labels = None
depends_on = None

_RETIRED_KEYS = (
    "dns_timeout",
    "retry_times",
    "obey_robots",
    "autothrottle_enabled",
)


def upgrade() -> None:
    # `- key` removes a key from a jsonb object (no-op when absent); the WHERE
    # limits the write to rows that actually carry a retired key.
    removals = " ".join(f"- '{key}'" for key in _RETIRED_KEYS)
    keys_array = ", ".join(f"'{key}'" for key in _RETIRED_KEYS)
    op.execute(
        f"""
        UPDATE tenants
        SET crawler_settings = crawler_settings {removals}
        WHERE jsonb_exists_any(crawler_settings, ARRAY[{keys_array}])
        """
    )


def downgrade() -> None:
    # Irreversible: the retired overrides carried no runtime meaning once their
    # settings were removed, and their prior values are not recoverable.
    pass
