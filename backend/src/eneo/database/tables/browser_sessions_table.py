from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, CreatedAtMixin, IdMixin
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class BrowserSessions(IdMixin, CreatedAtMixin, BaseWithTableName):
    """Server-side record of one browser sign-in.

    ``id`` is the session's stable, non-secret name (the token's
    session_ref); ``sid`` is the secret the token presents. A token with a
    sid claim is admitted only while its row exists, matches the token's
    user, tenant and session_ref (when it carries one), and is unexpired.
    Sign-out deletes the row; ``BrowserSessionService.delete_expired``
    deletes expired ones. Only a renewal changes a row, moving expires_at
    later.
    """

    sid: Mapped[str] = mapped_column(unique=True, nullable=False)
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
