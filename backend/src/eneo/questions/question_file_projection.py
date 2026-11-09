from collections.abc import Sequence

from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.questions.question import Question, QuestionsFiles


async def attach_question_files(
    questions: Sequence[Question],
    *,
    loader: FileContentLoader,
    include_user_uploads: bool = True,
) -> None:
    """Hydrate files reached through concrete Question↔File relationships.

    ``include_user_uploads`` is the principal's ``files`` read grant. Without
    it, uploads are neither read nor attached; generated outputs still are.
    """

    def readable(question_file: QuestionsFiles) -> bool:
        return include_user_uploads or question_file.type != "user"

    groups = [
        FileAttachmentGroup(
            owner_kind="question",
            owner_id=question.id,
            tenant_id=question.tenant_id,
            files=tuple(
                question_file.file
                for question_file in question.questions_files
                if readable(question_file)
            ),
        )
        for question in questions
    ]
    loaded = await loader.load_attachment_groups(groups)
    for question in questions:
        question.attach_hydrated_files(
            {file.id: file for file in loaded[("question", question.id)]},
            include_user_uploads=include_user_uploads,
        )
