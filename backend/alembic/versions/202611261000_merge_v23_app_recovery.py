"""Join the 2.3.3 app recovery indexes to the develop migration history.

Both paths build the same named indexes concurrently. A database coming
from 2.3.3 still needs the develop migrations after 202610261200.

202611201305 joined these paths while the specialist and group chat
retirement revisions were among its ancestors, so a database stamped with
it has those applied. This revision joins the paths without them and must
keep an id of its own.
"""

from collections.abc import Sequence

revision: str = "202611261000"
down_revision: tuple[str, str] = ("202611190900", "202611201300")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
