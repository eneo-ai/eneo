from collections.abc import Sequence

from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.questions.question import Question


async def attach_question_files(
    questions: Sequence[Question],
    *,
    loader: FileContentLoader | None,
    include_user_uploads: bool,
) -> None:
    """Hydrate files reached through concrete Question↔File relationships.

    ``include_user_uploads`` is the principal's ``files`` read grant. Without
    it, uploads are neither read nor attached and what tools read out of them
    is left out too (``Question.leave_out_user_uploads``); generated outputs
    still are attached.
    """
    if not include_user_uploads:
        generated_file_ids = {
            question_file.file.id
            for question in questions
            for question_file in question.questions_files
            if not question_file.is_user_upload
        }
        for question in questions:
            question.leave_out_user_uploads(generated_file_ids)
    if loader is None:
        if any(question.questions_files for question in questions):
            raise RuntimeError("Question files require FileContentLoader")
        return

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
