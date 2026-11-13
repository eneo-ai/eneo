"""Leave the upload limits as the installation set them

This revision used to raise upload limits still at their seed values to 256 MiB
for files and 384 MiB for audio. A seed value cannot be told apart from an
administrator's choice of the same value, so an upgrade must not change the
policy: an administrator with the storage permission raises the limits
through the object content policy.

The revision stays in the chain with an empty body both ways, so databases
already past it keep their history and the graph does not change.

Revision ID: 202609201300
Revises: 202609201200
"""

revision = "202609201300"
down_revision = "202609201200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
