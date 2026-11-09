"""Hydrating a question's files follows the principal's ``files`` read grant."""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID, uuid4

from eneo.files.file_content_loader import FileAttachmentGroup
from eneo.files.file_models import File, FileMetadata, FileType
from eneo.questions.question import Question, QuestionsFiles
from eneo.questions.question_file_projection import attach_question_files
from eneo.questions.question_protocol import to_question_public


def _file(name: str, text: str) -> File:
    now = datetime.now(timezone.utc)
    return File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        user_id=uuid4(),
        tenant_id=uuid4(),
        name=name,
        checksum="test-checksum",
        size=len(text),
        mimetype="text/plain",
        file_type=FileType.TEXT,
        text=text,
    )


def _metadata(file: File) -> FileMetadata:
    return FileMetadata(
        id=file.id,
        created_at=file.created_at,
        updated_at=file.updated_at,
        user_id=file.user_id,
        tenant_id=file.tenant_id,
        name=file.name,
        mimetype=file.mimetype,
        file_type=file.file_type,
    )


class _Loader:
    """Hydrates exactly the metadata it is asked for, and remembers the ask."""

    def __init__(self, files: Sequence[File]) -> None:
        self._files = {file.id: file for file in files}
        self.requested: list[UUID] = []

    async def load_attachment_groups(
        self, groups: Sequence[FileAttachmentGroup], **_: object
    ) -> dict[tuple[str, UUID], list[File]]:
        self.requested = [file.id for group in groups for file in group.files]
        return {
            group.key: [self._files[file.id] for file in group.files]
            for group in groups
        }


def _question(upload: File, generated: File) -> Question:
    return Question(
        id=uuid4(),
        tenant_id=upload.tenant_id,
        session_id=uuid4(),
        question="Summarise the attachment.",
        answer="Done.",
        num_tokens_question=5,
        num_tokens_answer=1,
        questions_files=[
            QuestionsFiles(type="user", file=_metadata(upload)),
            QuestionsFiles(type="assistant", file=_metadata(generated)),
        ],
    )


async def test_without_the_grant_uploads_are_neither_read_nor_attached():
    upload = _file("private-payroll.txt", "CONFIDENTIAL-PAYROLL-42")
    generated = _file("summary.txt", "GENERATED-SUMMARY")
    question = _question(upload, generated)
    loader = _Loader([upload, generated])

    await attach_question_files(
        [question],
        loader=loader,  # type: ignore[arg-type]
        include_user_uploads=False,
    )

    assert question.files == []
    assert question.generated_files == [generated]
    assert loader.requested == [generated.id]
    assert [link.type for link in question.questions_files] == ["assistant"]
    public = to_question_public(question)
    assert public.files == []
    assert "payroll" not in public.model_dump_json()


async def test_with_the_grant_uploads_and_outputs_are_attached():
    upload = _file("private-payroll.txt", "CONFIDENTIAL-PAYROLL-42")
    generated = _file("summary.txt", "GENERATED-SUMMARY")
    question = _question(upload, generated)
    loader = _Loader([upload, generated])

    await attach_question_files([question], loader=loader)  # type: ignore[arg-type]

    assert question.files == [upload]
    assert question.generated_files == [generated]
    assert loader.requested == [upload.id, generated.id]
    assert [link.type for link in question.questions_files] == ["user", "assistant"]
