"""Conversation cascade children come from the schema, not a hand-kept list."""

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_retention import (
    ConversationRootKind,
)
from eneo.data_retention.infrastructure.conversation_retention_repo import (
    ConversationCascadeError,
    ConversationRetentionRepository,
    collect_conversation_children,
)


@pytest.mark.parametrize(
    "kind, expected",
    [
        (
            ConversationRootKind.QUESTION,
            {
                ("info_blob_references", "question_id"),
                ("mcp_tool_references", "question_id"),
                ("question_feedback", "question_id"),
                ("questions_files", "question_id"),
            },
        ),
        (ConversationRootKind.APP_RUN, {("app_runs_files", "app_run_id")}),
    ],
)
def test_each_root_proves_every_relation_that_references_it(
    kind: ConversationRootKind, expected: set[tuple[str, str]]
) -> None:
    """Mutant: the repository keeps its own list instead of the metadata scan."""
    repository = ConversationRetentionRepository(
        AsyncSession(), kind=kind, now=datetime.now(timezone.utc)
    )

    assert {(column.table.name, column.name) for column in repository.children} == (
        expected
    )


def test_a_reference_without_cascade_fails_the_scan() -> None:
    """Mutant: a restricting foreign key to a root is tolerated."""
    metadata = sa.MetaData()
    root = sa.Table("roots", metadata, sa.Column("id", sa.Uuid, primary_key=True))
    sa.Table(
        "cascading",
        metadata,
        sa.Column("root_id", sa.Uuid, sa.ForeignKey("roots.id", ondelete="CASCADE")),
    )
    assert [
        column.table.name for column in collect_conversation_children(metadata, root)
    ] == ["cascading"]
    sa.Table(
        "restricting",
        metadata,
        sa.Column("root_id", sa.Uuid, sa.ForeignKey("roots.id")),
    )

    with pytest.raises(ConversationCascadeError):
        collect_conversation_children(metadata, root)
