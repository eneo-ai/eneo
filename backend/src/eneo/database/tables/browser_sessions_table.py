from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, false
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
    deletes expired ones. A renewal moves expires_at later, and a change of
    the organisation's MFA rule sets mfa to no; nothing else changes a row.
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
    # Whether the sign-in that started the session met the organisation's
    # MFA rule. Decided once, at sign-in, and never changed from no to yes: a
    # person who needs MFA signs in again and gets a new session.
    mfa: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=false()
    )
