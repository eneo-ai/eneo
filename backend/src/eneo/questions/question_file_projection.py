from collections.abc import Sequence

from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.questions.question import Question


async def attach_question_files(
    questions: Sequence[Question],
    *,
    loader: FileContentLoader,
) -> None:
    """Hydrate files reached through concrete Question↔File relationships."""
    groups = [
        FileAttachmentGroup(
            owner_kind="question",
            owner_id=question.id,
            tenant_id=question.tenant_id,
            files=tuple(
                question_file.file for question_file in question.questions_files
            ),
        )
        for question in questions
    ]
    loaded = await loader.load_attachment_groups(groups)
    for question in questions:
        question.attach_hydrated_files(
            {file.id: file for file in loaded[("question", question.id)]}
        )
