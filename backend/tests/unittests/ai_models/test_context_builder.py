# flake8: noqa

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import (
    Message,
    MessageToolCall,
)
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
from intric.questions.question import ToolCallInfo

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
                tool_calls=None,
            ),
            MagicMock(
                question="Question 2 with file",
                answer="Answer 2",
                files=[file],
                tool_calls=None,
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
                tool_calls=None,
            ),
            MagicMock(
                question="Question 2 with image",
                answer="Answer 2",
                files=[image],
                tool_calls=None,
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


def _question_mock(question: str, answer: str, tool_calls=None) -> MagicMock:
    return MagicMock(
        question=question,
        answer=answer,
        files=[],
        generated_files=[],
        tool_calls=tool_calls,
    )


def test_context_replays_tool_calls_with_result(context_builder: ContextBuilder):
    tool_call = ToolCallInfo(
        server_name="Time",
        tool_name="get_current_time",
        arguments={"timezone": "Europe/Stockholm"},
        tool_call_id="call_1",
        approved=True,
        result_status="succeeded",
        result="13:28",
        mcp_tool_name="time__get_current_time",
    )
    session = MagicMock(
        questions=[_question_mock("What time?", "13:28 in Sundsvall.", [tool_call])]
    )

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert len(context.messages) == 1
    # The replayed tool_name must be the LLM-visible prefixed form — it has to
    # match the currently-registered tools. The split/display `tool_name`
    # (`get_current_time`) stays in ToolCallInfo for UI rendering only.
    assert context.messages[0].tool_calls == [
        MessageToolCall(
            tool_call_id="call_1",
            tool_name="time__get_current_time",
            arguments={"timezone": "Europe/Stockholm"},
            result="13:28",
        )
    ]


def test_tool_call_falls_back_to_split_name_for_legacy_rows(
    context_builder: ContextBuilder,
):
    # Rows persisted before mcp_tool_name existed still have `tool_name` (the
    # split form). We fall back so they remain replayable, even if the name
    # won't perfectly match the currently-registered tools.
    legacy = ToolCallInfo(
        server_name="Time",
        tool_name="get_current_time",
        arguments=None,
        tool_call_id="call_legacy",
        approved=True,
        result="13:28",
        mcp_tool_name=None,
    )
    session = MagicMock(questions=[_question_mock("What time?", "13:28.", [legacy])])

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert context.messages[0].tool_calls[0].tool_name == "get_current_time"


def test_legacy_tool_call_without_result_falls_back_to_text(
    context_builder: ContextBuilder,
):
    # Rows persisted before the `result` field existed have no result.
    legacy = ToolCallInfo(
        server_name="time",
        tool_name="get_current_time",
        arguments={"timezone": "Europe/Stockholm"},
        tool_call_id="call_legacy",
        approved=True,
        result_status="succeeded",
        result=None,
    )
    session = MagicMock(questions=[_question_mock("What time?", "13:28.", [legacy])])

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert context.messages[0].tool_calls == []


def test_denied_tool_call_is_replayed_with_denial_payload(
    context_builder: ContextBuilder,
):
    # Denied calls must still be replayed so the model knows it attempted a
    # tool call and the user refused — otherwise it confabulates about what
    # happened on the next turn.
    denied = ToolCallInfo(
        server_name="shell",
        tool_name="rm",
        arguments={"path": "/"},
        tool_call_id="call_denied",
        approved=False,
        result_status="denied",
        result='{"denied": true, "user_reason": "no"}',
    )
    session = MagicMock(questions=[_question_mock("Delete root", "Refused.", [denied])])

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert context.messages[0].tool_calls == [
        MessageToolCall(
            tool_call_id="call_denied",
            tool_name="rm",
            arguments={"path": "/"},
            result='{"denied": true, "user_reason": "no"}',
        )
    ]


def test_pending_tool_call_without_result_is_not_replayed(
    context_builder: ContextBuilder,
):
    # Pending-approval rows reach the DB with result=None. Nothing to replay.
    pending = ToolCallInfo(
        server_name="time",
        tool_name="get_current_time",
        arguments={"tz": "Europe/Stockholm"},
        tool_call_id="call_pending",
        approved=None,
        result_status=None,
        result=None,
    )
    session = MagicMock(questions=[_question_mock("Tid?", "", [pending])])

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert context.messages[0].tool_calls == []


def test_tool_call_without_id_is_not_replayed(context_builder: ContextBuilder):
    # Pairing tool_use/tool_result requires a stable id; drop if missing.
    tc = ToolCallInfo(
        server_name="time",
        tool_name="get_current_time",
        arguments=None,
        tool_call_id=None,
        approved=True,
        result_status="succeeded",
        result="13:28",
    )
    session = MagicMock(questions=[_question_mock("What time?", "13:28.", [tc])])

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert context.messages[0].tool_calls == []


def test_parallel_tool_calls_in_one_turn(context_builder: ContextBuilder):
    tc1 = ToolCallInfo(
        server_name="time",
        tool_name="get_current_time",
        arguments={"tz": "Europe/Stockholm"},
        tool_call_id="call_a",
        approved=True,
        result="13:28",
    )
    tc2 = ToolCallInfo(
        server_name="weather",
        tool_name="get_weather",
        arguments={"city": "Sundsvall"},
        tool_call_id="call_b",
        approved=True,
        result="4°C, clear",
    )
    session = MagicMock(
        questions=[_question_mock("Time and weather?", "13:28, 4°C clear.", [tc1, tc2])]
    )

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert [tc.tool_call_id for tc in context.messages[0].tool_calls] == [
        "call_a",
        "call_b",
    ]


def test_tool_result_tokens_reported_in_history_token_count(
    context_builder: ContextBuilder,
):
    # A tool result contributes to the history token budget. The test compares
    # `_build_messages` output with and without a tool result on the newest turn
    # — same max_tokens, same everything else — and asserts the tool-result
    # variant reports more tokens used.
    tc_with_result = ToolCallInfo(
        server_name="s",
        tool_name="t",
        arguments=None,
        tool_call_id="call_big",
        approved=True,
        result="x " * 500,
    )
    turn_with = _question_mock("Q", "A", tool_calls=[tc_with_result])
    turn_without = _question_mock("Q", "A", tool_calls=None)

    _, tokens_without = context_builder._build_messages(
        session=MagicMock(questions=[turn_without]),
        max_tokens=10000,
    )
    _, tokens_with = context_builder._build_messages(
        session=MagicMock(questions=[turn_with]),
        max_tokens=10000,
    )

    assert tokens_with > tokens_without


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
