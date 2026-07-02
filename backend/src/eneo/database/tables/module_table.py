from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic


class Modules(BasePublic):
    name: Mapped[str] = mapped_column(unique=True)
    # Module auth broker client config: exact-match allowlist of callback URLs
    # and the sk_ key that alone may exchange this module's login tickets.
    redirect_uris: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    service_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="SET NULL"), nullable=True
    )
