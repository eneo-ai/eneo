from sqlalchemy import TIMESTAMP, Column, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import as_declarative, declared_attr
from sqlalchemy_mixins.serialize import SerializeMixin


@as_declarative()
class Base:
    __abstract__ = True


class BaseWithTableName(Base, SerializeMixin):
    __name__: str
    __abstract__ = True

    # Generate __tablename__ automatically
    @declared_attr
    def __tablename__(cls) -> str:
        # Camel case to snake case
        return "".join(
            ["_" + c.lower() if c.isupper() else c for c in cls.__name__]
        ).lstrip("_")


class TimestampMixin:
    created_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IdMixin:
    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


class BasePublic(IdMixin, TimestampMixin, BaseWithTableName):
    __abstract__ = True


class BaseCrossReference(TimestampMixin, BaseWithTableName):
    __abstract__ = True
