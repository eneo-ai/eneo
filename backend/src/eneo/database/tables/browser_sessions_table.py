from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, CreatedAtMixin
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class BrowserSessions(CreatedAtMixin, BaseWithTableName):
    """Server-side record of one browser sign-in, keyed by the token's sid.

    A token with a sid claim is admitted only while its row exists, matches
    the token's user and tenant, and is unexpired. Sign-out deletes the row;
    expired rows are deleted too. Only a renewal changes a row, moving
    expires_at later.
    """

    sid: Mapped[str] = mapped_column(primary_key=True)
    # Indexed for the cascade when a user, or a tenant with its users, is
    # deleted, and for deleting one user's rows.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
