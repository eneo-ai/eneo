"""A reader's edit of a conversation document, saved as its next version.

The assistant writes documents as Markdown and the reader edits them in Eneo.
An edit is kept in the editor until the reader saves; a save makes a File
that points, through ``revises_file_id``, at the assistant's version it was
made from. There is no shared editing session and no merging: a version is a
whole document, like the ones the assistant's document tools make.

A reader's edits are one layer on the assistant's version, not a history of
their own: saving again while the newest version is already the reader's
replaces that version instead of stacking on it. The versions that remain are
the assistant's, each with at most the reader's edit of it on top.

The new version joins the same turn as the version it revises, as one of that
turn's generated files. Everything that reads a conversation's documents (the
viewer, export, the model's history) then sees it without knowing how it came
to be, and the model is told which version is current when its earlier tool
result is replayed.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from eneo.conversations.document_export import conversation_document_turn
from eneo.files.file_models import FileInUseError
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
    # The reader's earlier version this save took the place of, if any.
    replaced_file_id: UUID | None = None


def _revised_by_a_tool(conversation: "SessionInDB", file_id: UUID) -> bool:
    """Whether a document tool has made a version from this file (its ``revises`` names it)."""
    needles = (str(file_id), file_id.hex)
    for question in conversation.questions or []:
        for call in question.tool_calls or []:
            arguments: dict[str, object] = call.arguments or {}
            revises = arguments.get("revises")
            if not isinstance(revises, dict):
                continue
            url = cast("dict[str, object]", revises).get("url")
            if isinstance(url, str) and any(needle in url for needle in needles):
                return True
    return False


async def save_document_version(
    *,
    conversation: "SessionInDB",
    file_id: UUID,
    content: str,
    user_id: UUID,
    file_service: "FileService",
    question_repo: "QuestionRepository",
) -> SavedDocumentVersion:
    """Save ``content`` as the next version of a Markdown document of the conversation.

    ``file_id`` is the version the reader edited; it must be a Markdown
    document one of the conversation's turns holds. Saving the same text the
    version already has makes nothing and hands that version back. Saving
    onto the reader's own newest version replaces it, so their edits stay one
    layer on the assistant's version.
    """
    found = conversation_document_turn(conversation, file_id)
    if found is None:
        raise NotFoundException(_NOT_FOUND)
    question, base = found
    # The stored text of a document drops the file's final newline.
    if base.text is not None and base.text.rstrip("\n") == content.rstrip("\n"):
        return SavedDocumentVersion(file=base, created=False, question_id=question.id)

    # The reader's own version, still the newest: the save takes its place.
    replaces = (
        base.revises_file_id is not None
        and base.user_id == user_id
        and not _revised_by_a_tool(conversation, base.id)
    )
    file = await file_service.save_generated_document(
        content.encode("utf-8"),
        name=base.name,
        mimetype=MARKDOWN_MIME_TYPE,
        revises_file_id=base.revises_file_id if replaces else base.id,
    )
    await question_repo.add_generated_file(question_id=question.id, file=file)
    replaced: UUID | None = None
    if replaces:
        await question_repo.remove_generated_file(
            question_id=question.id, file_id=base.id
        )
        try:
            await file_service.delete_file(base.id)
            replaced = base.id
        except (FileInUseError, NotFoundException):
            # Something else still holds the old version: it stays, and the
            # new one stands beside it.
            await question_repo.add_generated_file(question_id=question.id, file=base)
    return SavedDocumentVersion(
        file=file, created=True, question_id=question.id, replaced_file_id=replaced
    )
