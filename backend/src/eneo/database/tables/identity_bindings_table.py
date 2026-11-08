from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, CreatedAtMixin, IdMixin
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class IdentityBindings(IdMixin, BaseWithTableName):
    """Which account a provider's subject signs in to.

    The key is the issuer, the verified audience the subject belongs to (the
    client id of a browser sign-in's ID token, or the accepted API audience of
    a provider's access token), the claim the subject was read from and the
    subject, within one tenant. A binding made under another subject claim
    never matches, since its values may name other people. A sign-in
    that presents a bound key reaches its account without its email being
    consulted. A removed account keeps its bindings: SCIM reactivation reuses
    the row, so the identity stays reserved for it.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(nullable=False)
    audience: Mapped[str] = mapped_column(nullable=False)
    subject_claim: Mapped[str] = mapped_column(nullable=False)
    subject: Mapped[str] = mapped_column(nullable=False)
    # The time of the insert, not of its transaction: a sign-in that waited
    # for its account's lock while a window opened writes a binding newer
    # than the window, so the window cannot replace it again.
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )

    __table_args__ = (
        # One account per identity. Subject before audience, so the same
        # index also finds a subject under any audience of its issuer.
        UniqueConstraint(
            "tenant_id",
            "issuer",
            "subject_claim",
            "subject",
            "audience",
            name="identity_bindings_identity_key",
        ),
        # One subject per issuer and audience for an account; also serves
        # the lookups by account and the cascade when it is deleted.
        UniqueConstraint(
            "user_id", "issuer", "audience", name="identity_bindings_account_key"
        ),
    )


class IdentityMigrationWindows(IdMixin, CreatedAtMixin, BaseWithTableName):
    """While open, an account bound under the from pair may also be bound
    under the to pair by its email. The from binding stays.

    A window from a pair to itself is for a change of subject claim: each
    account bound under the pair before the window opened may have its
    subject there replaced once, found by its email or by the new subject
    under another audience.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    from_issuer: Mapped[str] = mapped_column(nullable=False)
    from_audience: Mapped[str] = mapped_column(nullable=False)
    to_issuer: Mapped[str] = mapped_column(nullable=False)
    to_audience: Mapped[str] = mapped_column(nullable=False)
    closes_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )

    __table_args__ = (
        Index(
            "ix_identity_migration_windows_target",
            "tenant_id",
            "to_issuer",
            "to_audience",
        ),
    )
