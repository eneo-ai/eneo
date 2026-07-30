from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.users_table import Users


class Jobs(BasePublic):
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    task: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column()
    result_location: Mapped[Optional[str]] = mapped_column()
    name: Mapped[Optional[str]] = mapped_column()
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispatch_envelope: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    dispatch_attempted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    staging_cleaned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
