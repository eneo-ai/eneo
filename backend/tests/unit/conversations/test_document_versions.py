"""A reader's edit of a document becomes the document's next version.

The version is a new Markdown file that points at the assistant's version it
was edited from and joins that file's turn, so the conversation, its export
and the model's history see it like any version the assistant made. Saving
onto the reader's own newest version replaces it; saving unchanged text makes
nothing.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.conversations.document_versions import save_document_version
from eneo.files.file_models import FileInUseError
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.domain.entities.mcp_server import (
    DOCX_MIME_TYPE,
    MARKDOWN_MIME_TYPE,
)

MARKDOWN = "# Plan\n\nFas ett startar i maj.\n"
READER = uuid4()


def _document(*, mimetype=MARKDOWN_MIME_TYPE, text=MARKDOWN, revises=None, user=None):
    return SimpleNamespace(
        id=uuid4(),
        name="Plan.md",
        mimetype=mimetype,
        text=text,
        revises_file_id=revises,
        user_id=user or uuid4(),
    )


def _conversation(*documents, tool_calls=None):
    return SimpleNamespace(
        questions=[
            SimpleNamespace(
                id=uuid4(), generated_files=list(documents), tool_calls=tool_calls or []
            )
        ]
    )


def _services(saved=None):
    files = SimpleNamespace(
        save_generated_document=AsyncMock(return_value=saved), delete_file=AsyncMock()
    )
    questions = SimpleNamespace(
        add_generated_file=AsyncMock(), remove_generated_file=AsyncMock()
    )
    return files, questions


def _save(conversation, file_id, content, files, questions):
    return save_document_version(
        conversation=conversation,
        file_id=file_id,
        content=content,
        user_id=READER,
        file_service=files,
        question_repo=questions,
    )


async def test_edited_text_is_saved_as_a_version_of_the_document_on_its_turn():
    base = _document()
    conversation = _conversation(base)
    version = SimpleNamespace(id=uuid4())
    files, questions = _services(saved=version)

    saved = await _save(
        conversation, base.id, "# Plan\n\nFas ett startar i juni.\n", files, questions
    )

    assert saved.created is True and saved.file is version
    assert saved.replaced_file_id is None
    assert saved.question_id == conversation.questions[0].id
    files.save_generated_document.assert_awaited_once_with(
        b"# Plan\n\nFas ett startar i juni.\n",
        name="Plan.md",
        mimetype=MARKDOWN_MIME_TYPE,
        revises_file_id=base.id,
    )
    questions.add_generated_file.assert_awaited_once_with(
        question_id=conversation.questions[0].id, file=version
    )


async def test_saving_onto_the_readers_own_newest_version_replaces_it():
    base = _document()
    mine = _document(text="# Plan\n\nAndra utkastet.\n", revises=base.id, user=READER)
    conversation = _conversation(base, mine)
    version = SimpleNamespace(id=uuid4())
    files, questions = _services(saved=version)

    saved = await _save(conversation, mine.id, "# Plan\n\nTredje.\n", files, questions)

    # The new version stands on the assistant's version, as the old one did.
    assert files.save_generated_document.await_args.kwargs["revises_file_id"] == (
        base.id
    )
    questions.remove_generated_file.assert_awaited_once_with(
        question_id=conversation.questions[0].id, file_id=mine.id
    )
    files.delete_file.assert_awaited_once_with(mine.id)
    assert saved.replaced_file_id == mine.id


async def test_another_readers_version_is_not_replaced():
    base = _document()
    theirs = _document(text="# Plan\n\nDeras.\n", revises=base.id)
    files, questions = _services(saved=SimpleNamespace(id=uuid4()))

    saved = await _save(
        _conversation(base, theirs), theirs.id, "# Mitt.\n", files, questions
    )

    assert files.save_generated_document.await_args.kwargs["revises_file_id"] == (
        theirs.id
    )
    files.delete_file.assert_not_awaited()
    assert saved.replaced_file_id is None


async def test_a_version_a_tool_has_built_on_is_kept():
    base = _document()
    mine = _document(text="# Plan\n\nMitt.\n", revises=base.id, user=READER)
    conversation = _conversation(
        base,
        mine,
        tool_calls=[
            SimpleNamespace(
                arguments={
                    "revises": {"url": f"https://eneo/files/{mine.id}/original/"}
                }
            )
        ],
    )
    files, questions = _services(saved=SimpleNamespace(id=uuid4()))

    await _save(conversation, mine.id, "# Plan\n\nIgen.\n", files, questions)

    assert files.save_generated_document.await_args.kwargs["revises_file_id"] == (
        mine.id
    )
    files.delete_file.assert_not_awaited()


async def test_an_old_version_that_cannot_go_stays_beside_the_new_one():
    base = _document()
    mine = _document(text="# Plan\n\nMitt.\n", revises=base.id, user=READER)
    files, questions = _services(saved=SimpleNamespace(id=uuid4()))
    files.delete_file.side_effect = FileInUseError(
        SimpleNamespace(model_dump=lambda **_: {"can_delete": False})
    )

    saved = await _save(
        _conversation(base, mine), mine.id, "# Igen.\n", files, questions
    )

    assert saved.replaced_file_id is None
    # Linked again after the attempt to take it out.
    assert questions.add_generated_file.await_args_list[-1].kwargs["file"] is mine


async def test_unchanged_text_makes_no_version():
    base = _document()
    files, questions = _services()

    saved = await _save(_conversation(base), base.id, MARKDOWN, files, questions)

    assert saved.created is False and saved.file is base
    files.save_generated_document.assert_not_awaited()
    questions.add_generated_file.assert_not_awaited()


_WORD = _document(mimetype=DOCX_MIME_TYPE)


@pytest.mark.parametrize(
    "conversation, file_id",
    [
        # A file of another conversation.
        (_conversation(_document()), uuid4()),
        # A Word document is downloaded, not edited in Eneo.
        (_conversation(_WORD), _WORD.id),
    ],
)
async def test_only_a_markdown_document_of_the_conversation_takes_a_version(
    conversation, file_id
):
    files, questions = _services()

    with pytest.raises(NotFoundException):
        await _save(conversation, file_id, "# x\n", files, questions)

    files.save_generated_document.assert_not_awaited()
