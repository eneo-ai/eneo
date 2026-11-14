from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants


class ConnectorInstallations(BasePublic):
    """An installation of another system that a tenant lets call Eneo over the
    connector protocol.

    The shared key is never stored, only its SHA-256: the key is shown once,
    when the installation is added, and a call is matched to its installation
    by the digest of the key it carries.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(120))
    # Where the installation publishes the keys its assertions are signed with.
    base_url: Mapped[str] = mapped_column(sa.String(2000))
    key_digest: Mapped[str] = mapped_column(sa.String(64))

    __table_args__ = (
        sa.UniqueConstraint("key_digest", name="uq_connector_installations_key_digest"),
        sa.UniqueConstraint(
            "tenant_id", "base_url", name="uq_connector_installations_tenant_base_url"
        ),
    )
