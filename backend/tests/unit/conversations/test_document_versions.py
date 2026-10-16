"""A reader's edit of a document becomes the document's next version.

The version is a new Markdown file that points at the one it was edited from
and joins that file's turn, so the conversation, its export and the model's
history see it like any version the assistant made. Saving unchanged text
makes nothing.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.conversations.document_versions import save_document_version
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.domain.entities.mcp_server import (
    DOCX_MIME_TYPE,
    MARKDOWN_MIME_TYPE,
)

MARKDOWN = "# Plan\n\nFas ett startar i maj.\n"


def _document(*, mimetype=MARKDOWN_MIME_TYPE, text=MARKDOWN):
    return SimpleNamespace(id=uuid4(), name="Plan.md", mimetype=mimetype, text=text)


def _conversation(*documents):
    return SimpleNamespace(
        questions=[SimpleNamespace(id=uuid4(), generated_files=list(documents))]
    )


def _services(saved=None):
    files = SimpleNamespace(save_generated_document=AsyncMock(return_value=saved))
    questions = SimpleNamespace(add_generated_file=AsyncMock())
    return files, questions


async def test_edited_text_is_saved_as_a_version_of_the_document_on_its_turn():
    base = _document()
    conversation = _conversation(base)
    version = SimpleNamespace(id=uuid4())
    files, questions = _services(saved=version)

    saved = await save_document_version(
        conversation=conversation,
        file_id=base.id,
        content="# Plan\n\nFas ett startar i juni.\n",
        file_service=files,
        question_repo=questions,
    )

    assert saved.created is True and saved.file is version
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


async def test_a_version_of_a_version_revises_the_version_it_was_edited_from():
    base = _document()
    first = _document(text="# Plan\n\nAndra utkastet.\n")
    conversation = _conversation(base, first)
    files, questions = _services(saved=SimpleNamespace(id=uuid4()))

    await save_document_version(
        conversation=conversation,
        file_id=first.id,
        content="# Plan\n\nTredje utkastet.\n",
        file_service=files,
        question_repo=questions,
    )

    assert files.save_generated_document.await_args.kwargs["revises_file_id"] == (
        first.id
    )


async def test_unchanged_text_makes_no_version():
    base = _document()
    files, questions = _services()

    saved = await save_document_version(
        conversation=_conversation(base),
        file_id=base.id,
        content=MARKDOWN,
        file_service=files,
        question_repo=questions,
    )

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
        await save_document_version(
            conversation=conversation,
            file_id=file_id,
            content="# x\n",
            file_service=files,
            question_repo=questions,
        )

    files.save_generated_document.assert_not_awaited()
