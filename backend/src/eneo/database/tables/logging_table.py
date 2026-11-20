from sqlalchemy import UUID, Column, Index, MetaData, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import registry

from eneo.database.tables.base_class import Base

mapper_registry = registry()


def create_logging_table(metadata_obj: MetaData) -> type:
    table = Table(
        "logging",
        metadata_obj,
        Column(  # pyright: ignore[reportUnknownArgumentType]  # untyped Column in Table constructor
            "id",
            UUID,
            primary_key=True,
            server_default=func.gen_random_uuid(),
        ),
        Column("context", String),
        Column("model_kwargs", JSONB),
        Column("json_body", JSONB),
        # The conversation whose removals clear this log, while it holds
        # content. The database sets it when the log is linked to its
        # question and unsets it when a removal clears the log.
        Column("session_id", UUID),  # pyright: ignore[reportUnknownArgumentType]  # untyped Column in Table constructor
        Index(
            "ix_logging_session_id",
            "session_id",
            postgresql_where=text("session_id IS NOT NULL"),
        ),
    )

    class Logging:
        pass

    mapper_registry.map_imperatively(Logging, table)

    return Logging


logging_table = create_logging_table(Base.metadata)  # type: ignore[attr-defined]
