"""A reader's edit of a conversation document, saved as its next version.

The assistant writes documents as Markdown and the reader edits them in Eneo.
An edit is kept in the editor until the reader saves; a save makes a File
that points, through ``revises_file_id``, at the version it was made from.
There is no shared editing session and no merging: a version is a whole
document, like the ones the assistant's document tools make, and every save
is one more version. Nothing is replaced or deleted, so the versions read
like any editor's history: restoring an older version is a save of its text.

The new version joins the same turn as the version it revises, as one of that
turn's generated files. Everything that reads a conversation's documents (the
viewer, export, the model's history) then sees it without knowing how it came
to be, and the model is told which version is current when its earlier tool
result is replayed.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.conversations.document_export import conversation_document_turn
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.domain.entities.mcp_server import MARKDOWN_MIME_TYPE

if TYPE_CHECKING:
    from eneo.files.file_models import File
    from eneo.files.file_service import FileService
    from eneo.questions.questions_repo import QuestionRepository
    from eneo.sessions.session import SessionInDB

_NOT_FOUND = "Document not found in this conversation"


@dataclass(frozen=True)
class SavedDocumentVersion:
    """The version the reader now has: new when ``created``, else the one saved from."""

    file: "File"
    created: bool
    question_id: UUID


async def save_document_version(
    *,
    conversation: "SessionInDB",
    file_id: UUID,
    content: str,
    # The saving reader. Every reader's save is a version of its own, so the
    # id decides nothing here; the router passes it for the audit trail.
    user_id: UUID,
    file_service: "FileService",
    question_repo: "QuestionRepository",
) -> SavedDocumentVersion:
    """Save ``content`` as the next version of a Markdown document of the conversation.

    ``file_id`` is the version the reader edited; it must be a Markdown
    document one of the conversation's turns holds. Saving the same text the
    version already has makes nothing and hands that version back.
    """
    found = conversation_document_turn(conversation, file_id)
    if found is None:
        raise NotFoundException(_NOT_FOUND)
    question, base = found
    # The stored text of a document drops the file's final newline.
    if base.text is not None and base.text.rstrip("\n") == content.rstrip("\n"):
        return SavedDocumentVersion(file=base, created=False, question_id=question.id)

    file = await file_service.save_generated_document(
        content.encode("utf-8"),
        name=base.name,
        mimetype=MARKDOWN_MIME_TYPE,
        revises_file_id=base.id,
    )
    await question_repo.add_generated_file(question_id=question.id, file=file)
    return SavedDocumentVersion(file=file, created=True, question_id=question.id)
