"""Hydrating a question's files follows the principal's ``files`` read grant."""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from eneo.files.file_content_loader import FileAttachmentGroup
from eneo.files.file_models import File, FileMetadata, FileType
from eneo.files.model_file_references import file_handle
from eneo.questions.question import (
    McpToolReferencePublic,
    Question,
    QuestionsFiles,
    ToolCallInfo,
)
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

    await attach_question_files(
        [question],
        loader=loader,  # type: ignore[arg-type]
        include_user_uploads=True,
    )

    assert question.files == [upload]
    assert question.generated_files == [generated]
    assert loader.requested == [upload.id, generated.id]
    assert [link.type for link in question.questions_files] == ["user", "assistant"]


def _reference(tool_call_id: str, content: str) -> McpToolReferencePublic:
    now = datetime.now(timezone.utc)
    return McpToolReferencePublic(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        uri="resource://captured",
        content=content,
        tool_call_id=tool_call_id,
    )


def _with_tool_calls(question: Question, upload: File, generated: File) -> Question:
    """The turn read its upload with a tool, edited its own output and searched."""
    question.tool_calls = [
        ToolCallInfo(
            server_name="files",
            tool_name="read_file",
            tool_call_id="read-upload",
            arguments={
                "url": f"https://eneo.test/api/v1/files/{upload.id}"
                "/original/download?token=REDACTED"
            },
            result=f"File: {upload.name} (text/plain)\n\n{upload.text}",
            structured_content={"text": upload.text},
        ),
        ToolCallInfo(
            server_name="images",
            tool_name="edit",
            tool_call_id="edit-generated",
            arguments={"image": file_handle(generated.id), "prompt": "Crop it"},
            result="[Image 1]",
        ),
        ToolCallInfo(
            server_name="web",
            tool_name="search",
            tool_call_id="search",
            arguments={"query": "payroll law"},
            result="Three results.",
        ),
    ]
    question.mcp_tool_references = [
        _reference("read-upload", upload.text or ""),
        _reference("search", "A public page."),
    ]
    return question


async def test_without_the_grant_what_a_tool_read_out_of_an_upload_is_left_out():
    upload = _file("private-payroll.txt", "CONFIDENTIAL-PAYROLL-42")
    generated = _file("summary.txt", "GENERATED-SUMMARY")
    question = _with_tool_calls(_question(upload, generated), upload, generated)

    await attach_question_files(
        [question],
        loader=_Loader([upload, generated]),  # type: ignore[arg-type]
        include_user_uploads=False,
    )

    assert question.tool_calls is not None
    read, edit, search = question.tool_calls
    assert (read.arguments, read.result, read.structured_content) == (None, None, None)
    assert read.tool_call_id == "read-upload"
    assert edit.result == "[Image 1]"
    assert search.result == "Three results."
    assert [ref.tool_call_id for ref in question.mcp_tool_references] == ["search"]
    stored = question.model_dump_json()
    assert "PAYROLL-42" not in stored
    assert "private-payroll" not in stored
    assert str(upload.id) not in stored


async def test_with_the_grant_tool_calls_are_untouched():
    upload = _file("private-payroll.txt", "CONFIDENTIAL-PAYROLL-42")
    generated = _file("summary.txt", "GENERATED-SUMMARY")
    question = _with_tool_calls(_question(upload, generated), upload, generated)
    before = question.model_dump(include={"tool_calls", "mcp_tool_references"})

    await attach_question_files(
        [question],
        loader=_Loader([upload, generated]),  # type: ignore[arg-type]
        include_user_uploads=True,
    )

    assert question.model_dump(include={"tool_calls", "mcp_tool_references"}) == before


async def test_a_file_from_another_turn_counts_as_an_upload():
    """Only the turns in hand say what was generated, so a reference to any
    other file is masked rather than trusted."""
    upload = _file("private-payroll.txt", "CONFIDENTIAL-PAYROLL-42")
    generated = _file("summary.txt", "GENERATED-SUMMARY")
    question = _with_tool_calls(_question(upload, generated), upload, generated)
    question.questions_files = []

    await attach_question_files([question], loader=None, include_user_uploads=False)

    assert question.tool_calls is not None
    assert [call.result for call in question.tool_calls] == [
        None,
        None,
        "Three results.",
    ]


async def test_without_a_loader_only_the_files_left_to_read_need_one():
    upload = _file("private-payroll.txt", "CONFIDENTIAL-PAYROLL-42")
    generated = _file("summary.txt", "GENERATED-SUMMARY")
    only_upload = _question(upload, generated)
    only_upload.questions_files = only_upload.questions_files[:1]

    await attach_question_files([only_upload], loader=None, include_user_uploads=False)
    assert only_upload.files == []
    assert only_upload.questions_files == []

    with pytest.raises(RuntimeError, match="require FileContentLoader"):
        await attach_question_files(
            [_question(upload, generated)], loader=None, include_user_uploads=False
        )
