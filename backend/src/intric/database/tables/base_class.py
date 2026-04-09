from datetime import datetime
from typing import cast
from uuid import UUID as PyUUID

from sqlalchemy import TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, as_declarative, declared_attr, mapped_column
from sqlalchemy_mixins.serialize import SerializeMixin


@as_declarative()
class Base:
    __abstract__ = True


class BaseWithTableName(Base, SerializeMixin):
    __abstract__ = True

    # Generate __tablename__ automatically
    @declared_attr.directive
    def __tablename__(cls) -> str:
        # Camel case to snake case
        cls_name = cast(str, cls.__name__)  # type: ignore[attr-defined]
        return "".join(
            ["_" + c.lower() if c.isupper() else c for c in cls_name]
        ).lstrip("_")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IdMixin:
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


class BasePublic(IdMixin, TimestampMixin, BaseWithTableName):
    __abstract__ = True


class BaseCrossReference(TimestampMixin, BaseWithTableName):
    __abstract__ = True
