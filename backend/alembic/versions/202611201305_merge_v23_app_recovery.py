"""Join the 2.3.3 app recovery indexes to the develop migration history.

Both paths build the same named indexes concurrently. A database coming
from 2.3.3 still needs the develop migrations after 202610261200.
"""

from collections.abc import Sequence

revision: str = "202611201305"
down_revision: tuple[str, str] = ("202611201210", "202611201300")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
