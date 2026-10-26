"""clear cross-tenant icon references

Before 2.3 a resource update accepted any icon id, and icon ids are public, so
an assistant, app, space or group chat could show another tenant's icon. Such a
reference displays one tenant's image in another and, since an icon that
anything shows can no longer be deleted, keeps its owner from deleting it.
Updates now accept only the caller's own uploads; this clears the references
whose icon belongs to a different tenant than the resource, which then shows
its default avatar. References within a tenant are kept: older icons do not
record their uploader, and the owner's tenant can clear those itself.

Revision ID: 202610261300
Revises: 202610261200
Create Date: 2026-10-26 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202610261300"
down_revision: str | None = "202610261200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("assistants", "apps", "group_chats"):
        op.execute(
            f"""
            UPDATE {table} AS resource SET icon_id = NULL
            FROM spaces, icons
            WHERE spaces.id = resource.space_id
              AND icons.id = resource.icon_id
              AND icons.tenant_id <> spaces.tenant_id
            """
        )
    op.execute(
        """
        UPDATE spaces SET icon_id = NULL
        FROM icons
        WHERE icons.id = spaces.icon_id AND icons.tenant_id <> spaces.tenant_id
        """
    )


def downgrade() -> None:
    # The cleared references are not recorded, so there is nothing to restore.
    pass
