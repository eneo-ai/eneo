"""add websites_spaces table
Revision ID: 42f8f8ae0ea7
Revises: b8a20aead976
Create Date: 2025-08-20 08:49:04.154426
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision = '42f8f8ae0ea7'
down_revision = 'b8a20aead976'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "websites_spaces",
        sa.Column(
            "website_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("website_id", "space_id", name="pk_websites_spaces"),
    )

    op.create_index("ix_websites_spaces_space_id", "websites_spaces", ["space_id"])
    op.create_index("ix_websites_spaces_website_id", "websites_spaces", ["website_id"])

    #koppla befintliga websites till sitt owner space
    op.execute(
        """
        INSERT INTO websites_spaces (website_id, space_id)
        SELECT id, space_id
        FROM websites
        WHERE space_id IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_websites_spaces_website_id", table_name="websites_spaces")
    op.drop_index("ix_websites_spaces_space_id", table_name="websites_spaces")
    op.drop_table("websites_spaces")
