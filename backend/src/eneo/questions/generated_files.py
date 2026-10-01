"""Files an assistant's tools generated, which only its answers own.

A generated file (linked to a question with type ``assistant``) has no owner
surface besides the conversation. Questions cascade their file links but not
the ``files`` rows, so a path that deletes questions collects the generated
files first and removes the ones nothing references afterwards. Uploads are
left alone; the user manages those.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles

GENERATED_FILE_LINK_TYPE = "assistant"


async def generated_file_ids(
    session: AsyncSession, question_filter: sa.ColumnElement[bool]
) -> list[UUID]:
    """Ids of the generated files linked from the questions matching the filter."""
    return list(
        await session.scalars(
            sa.select(QuestionsFiles.file_id)
            .join(Questions, Questions.id == QuestionsFiles.question_id)
            .where(question_filter, QuestionsFiles.type == GENERATED_FILE_LINK_TYPE)
        )
    )


async def delete_unreferenced_files(
    session: AsyncSession, file_ids: Sequence[UUID]
) -> None:
    """Delete the files among ``file_ids`` that no question links any more."""
    if not file_ids:
        return
    still_referenced = sa.select(QuestionsFiles.file_id).where(
        QuestionsFiles.file_id.in_(file_ids)
    )
    await session.execute(
        sa.delete(Files).where(
            Files.id.in_(file_ids),
            Files.id.not_in(still_referenced),
        )
    )
