# flake8: noqa

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import Message
from intric.completion_models.infrastructure.context_builder import (
    ContextBuilder,
    count_tokens,
)
from intric.completion_models.infrastructure.static_prompts import (
    HALLUCINATION_GUARD,
    SHOW_REFERENCES_PROMPT,
)
from intric.files.file_models import File, FileType
from intric.main.exceptions import QueryException

QUESTION = "I have a question"


@pytest.fixture
def context_builder():
    return ContextBuilder()


def test_context_builder_basic_context(context_builder: ContextBuilder):
    context = context_builder.build_context(input_str=QUESTION, max_tokens=10000)

    assert context.input == QUESTION


def test_context_with_info_blobs_version_2(context_builder: ContextBuilder):
    info_blob_chunks = [
        MagicMock(
            text="chunk 1, information about blob number 1 - chunk 2",
            chunk_no=2,
            info_blob_id=1,
            info_blob_title="blob 1",
        ),
        MagicMock(
            text="information about blob number 1 - chunk 1",
            chunk_no=1,
            info_blob_id=1,
            info_blob_title="blob 1",
        ),
        MagicMock(
            text="information about blob number 2",
            chunk_no=1,
            info_blob_id=2,
            info_blob_title="blob 2",
        ),
    ]

    expected_background_info = f"""{SHOW_REFERENCES_PROMPT}\n\n\"\"\"source_title: blob 1, source_id: 1\ninformation about blob number 1 - chunk 1, information about blob number 1 - chunk 2\"\"\"
\"\"\"source_title: blob 2, source_id: 2\ninformation about blob number 2\"\"\""""

    context = context_builder.build_context(
        input_str=QUESTION,
        info_blob_chunks=info_blob_chunks,
        max_tokens=10000,
        version=2,
    )

    assert context.prompt == expected_background_info


def test_context_with_info_blobs_version_1(context_builder: ContextBuilder):
    info_blob_chunks = [
        MagicMock(text=f"information about blob number {i}") for i in range(3)
    ]

    expected_background_info = f"""{HALLUCINATION_GUARD}\n\n\"\"\"information about blob number 0\"\"\"
\"\"\"information about blob number 1\"\"\"
\"\"\"information about blob number 2\"\"\""""

    context = context_builder.build_context(
        input_str=QUESTION,
        info_blob_chunks=info_blob_chunks,
        max_tokens=10000,
    )

    assert context.prompt == expected_background_info


def test_context_with_files(context_builder: ContextBuilder):
    file = MagicMock(
        text="This is the text from the file",
        file_type=FileType.TEXT,
    )
    file.name = "test_file.pdf"

    context = context_builder.build_context(
        input_str=QUESTION, files=[file], max_tokens=10000
    )

    expected_input = f"""Below are files uploaded by the user. You should act like you can see the files themselves, and not reveal the specific formatting you see below:

{{"filename": "{file.name}", "text": "{file.text}"}}

{QUESTION}"""  # noqa

    assert context.input == expected_input


def test_context_with_messages(context_builder: ContextBuilder):
    file = File(
        id=uuid4(),
        text="This is the text from the file",
        name="test_file.pdf",
        checksum="",
        size=0,
        tenant_id=uuid4(),
        user_id=uuid4(),
        file_type=FileType.TEXT,
    )

    session = MagicMock(
        questions=[
            MagicMock(
                question="Question 1",
                answer="Answer 1",
                files=[],
            ),
            MagicMock(
                question="Question 2 with file",
                answer="Answer 2",
                files=[file],
            ),
        ]
    )

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    expected_question_2 = f"""Below are files uploaded by the user. You should act like you can see the files themselves, and not reveal the specific formatting you see below:

{{"filename": "{file.name}", "text": "{file.text}"}}

Question 2 with file"""  # noqa
    expected_messages = [
        Message(question="Question 1", answer="Answer 1"),
        Message(question=expected_question_2, answer="Answer 2"),
    ]

    assert context.messages == expected_messages


def test_context_with_images(context_builder: ContextBuilder):
    image = File(
        id=uuid4(),
        blob="data",
        name="test_file.png",
        checksum="",
        size=0,
        tenant_id=uuid4(),
        user_id=uuid4(),
        file_type=FileType.IMAGE,
    )

    context = context_builder.build_context(
        input_str=QUESTION, files=[image], max_tokens=10000
    )

    assert context.images == [image]


def test_context_with_messages_and_images(context_builder: ContextBuilder):
    image = File(
        id=uuid4(),
        name="test_file.png",
        blob="data",
        checksum="",
        size=0,
        tenant_id=uuid4(),
        user_id=uuid4(),
        file_type=FileType.IMAGE,
    )

    session = MagicMock(
        questions=[
            MagicMock(
                question="Question 1",
                answer="Answer 1",
                files=[],
            ),
            MagicMock(
                question="Question 2 with image",
                answer="Answer 2",
                files=[image],
            ),
        ]
    )

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    expected_messages = [
        Message(question="Question 1", answer="Answer 1"),
        Message(question="Question 2 with image", answer="Answer 2", images=[image]),
    ]

    assert context.messages == expected_messages


def test_get_error_on_too_long_question(context_builder: ContextBuilder):
    input_str = "This is a loooooong query, longer than 5 tokens"

    with pytest.raises(QueryException):
        context_builder.build_context(input_str=input_str, max_tokens=5)


def test_get_error_on_too_long_question_and_prompt(context_builder: ContextBuilder):
    input_str = "Short query"
    prompt_str = "This is a super long prompt string"

    with pytest.raises(QueryException):
        context_builder.build_context(
            input_str=input_str, prompt=prompt_str, max_tokens=7
        )


def test_truncate_knowledge_if_too_many_chunks(context_builder: ContextBuilder):
    info_blob_chunks = [
        MagicMock(
            text="Original Text from a chunk",
            chunk_no=i,
            info_blob_id=i,
            info_blob_title=f"blob {i}",
        )
        for i in range(1, 10000)
    ]

    context = context_builder.build_context(
        input_str=QUESTION,
        info_blob_chunks=info_blob_chunks,
        max_tokens=10000,
        version=2,
    )

    assert context.token_count < 10000
    assert count_tokens(context.prompt) + count_tokens(QUESTION) < 10000
