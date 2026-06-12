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
        mimetype="application/pdf",
    )
    file.name = "test_file.pdf"

    context = context_builder.build_context(
        input_str=QUESTION, files=[file], max_tokens=10000
    )

    expected_input = f"""Below are files uploaded by the user. You should act like you can see the files themselves, and not reveal the specific formatting you see below:

FILE: {file.name} (application/pdf)
{file.text}

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

FILE: {file.name}
{file.text}

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


def test_too_long_question_is_forwarded_to_provider(context_builder: ContextBuilder):
    input_str = "This is a loooooong query, longer than 5 tokens"

    context = context_builder.build_context(input_str=input_str, max_tokens=5)

    assert context.input == input_str
    assert context.token_count > 5


def test_too_long_required_context_skips_knowledge(
    context_builder: ContextBuilder,
):
    input_str = "Short query"
    prompt_str = "This is a super long prompt string"
    chunk = MagicMock(
        text="knowledge that must not make an oversized request even larger",
        chunk_no=1,
        info_blob_id=uuid4(),
        info_blob_title="Knowledge",
    )

    context = context_builder.build_context(
        input_str=input_str,
        prompt=prompt_str,
        info_blob_chunks=[chunk],
        max_tokens=7,
    )

    assert context.input == input_str
    assert context.prompt == prompt_str
    assert context.token_count > 7


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


_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000d4944415478da63f8cfc000000301010018dd8db00000000049"
    "454e44ae426082"
)


def _image_file(blob: bytes = _PNG_1PX) -> File:
    return File(
        id=uuid4(),
        name="photo.png",
        blob=blob,
        mimetype="image/png",
        checksum="",
        size=len(blob),
        tenant_id=uuid4(),
        user_id=uuid4(),
        file_type=FileType.IMAGE,
    )


def test_image_attachment_increases_token_count(context_builder: ContextBuilder):
    without_image = context_builder.build_context(input_str=QUESTION, max_tokens=10000)
    with_image = context_builder.build_context(
        input_str=QUESTION, files=[_image_file()], max_tokens=10000
    )

    # An image costs at least the provider base cost (85 tokens on OpenAI).
    assert with_image.token_count >= without_image.token_count + 85


def test_large_image_is_counted_at_high_detail(context_builder: ContextBuilder):
    # Images are sent with detail "high"; a 2048×1024 image is tiled by
    # OpenAI's formula to ~1105 tokens — make sure we don't count the flat
    # 85-token "auto" estimate.
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2048, 1024), color=(40, 80, 120)).save(buffer, format="PNG")

    without_image = context_builder.build_context(input_str=QUESTION, max_tokens=100000)
    with_image = context_builder.build_context(
        input_str=QUESTION,
        files=[_image_file(blob=buffer.getvalue())],
        max_tokens=100000,
    )

    assert with_image.token_count >= without_image.token_count + 1000


def test_attachment_images_ride_on_current_message(context_builder: ContextBuilder):
    attachment_image = _image_file()

    context = context_builder.build_context(
        input_str=QUESTION, prompt_files=[attachment_image], max_tokens=10000
    )

    assert context.images == [attachment_image]


def test_attachment_images_dropped_without_vision(context_builder: ContextBuilder):
    context = context_builder.build_context(
        input_str=QUESTION,
        prompt_files=[_image_file()],
        max_tokens=10000,
        vision=False,
    )

    assert context.images == []


def test_attachment_images_not_duplicated_with_current(
    context_builder: ContextBuilder,
):
    image = _image_file()

    context = context_builder.build_context(
        input_str=QUESTION, files=[image], prompt_files=[image], max_tokens=10000
    )

    assert context.images == [image]


def test_history_images_increase_token_count(context_builder: ContextBuilder):
    def _session(files):
        return MagicMock(
            questions=[
                MagicMock(
                    question="Q",
                    answer="A",
                    files=files,
                    generated_files=[],
                    tool_calls=None,
                )
            ]
        )

    _, tokens_without = context_builder._build_messages(
        session=_session([]), max_tokens=10000
    )
    _, tokens_with = context_builder._build_messages(
        session=_session([_image_file()]), max_tokens=10000
    )

    assert tokens_with >= tokens_without + 85


def test_tool_definitions_increase_token_count(context_builder: ContextBuilder):
    without_tools = context_builder.build_context(input_str=QUESTION, max_tokens=10000)
    with_function = context_builder.build_context(
        input_str=QUESTION, max_tokens=10000, use_image_generation=True
    )
    with_extra_dicts = context_builder.build_context(
        input_str=QUESTION,
        max_tokens=10000,
        extra_tool_dicts=[
            {
                "type": "function",
                "function": {
                    "name": "mcp__lookup",
                    "description": "Look up a record in the registry by id.",
                    "parameters": {
                        "type": "object",
                        "properties": {"record_id": {"type": "string"}},
                        "required": ["record_id"],
                    },
                },
            }
        ],
    )

    assert with_function.token_count > without_tools.token_count
    assert with_extra_dicts.token_count > without_tools.token_count


def test_oversized_attachment_is_truncated_with_notice(
    context_builder: ContextBuilder, monkeypatch: pytest.MonkeyPatch
):
    from intric.completion_models.infrastructure import context_builder as cb_module
    from intric.completion_models.infrastructure.context_builder import (
        ATTACHMENT_TRUNCATION_NOTICE,
        build_files_string,
    )

    settings = MagicMock(attachment_max_tokens_per_file=10)
    monkeypatch.setattr(cb_module, "get_settings", lambda: settings)

    file = MagicMock(
        text="word " * 1000, file_type=FileType.TEXT, mimetype="text/plain"
    )
    file.name = "big.txt"

    result = build_files_string([file])

    assert ATTACHMENT_TRUNCATION_NOTICE in result
    assert len(result) < len(file.text)


def test_truncation_stays_within_budget_including_notice():
    from intric.completion_models.infrastructure.context_builder import (
        ATTACHMENT_TRUNCATION_NOTICE,
        _truncate_to_tokens,
    )

    max_tokens = 100
    # Token-dense text (few chars per token) — the proportional cut alone
    # would overshoot the budget.
    text = "0123456789abcdef" * 2000

    result = _truncate_to_tokens(text, max_tokens=max_tokens)

    assert ATTACHMENT_TRUNCATION_NOTICE in result
    assert count_tokens(result) <= max_tokens


def test_vision_false_drops_current_images(context_builder: ContextBuilder):
    context = context_builder.build_context(
        input_str=QUESTION, files=[_image_file()], max_tokens=10000, vision=False
    )

    assert context.images == []


def test_vision_false_drops_history_images(context_builder: ContextBuilder):
    session = MagicMock(
        questions=[
            MagicMock(
                question="Q",
                answer="A",
                files=[_image_file()],
                generated_files=[],
                tool_calls=None,
            )
        ]
    )

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000, vision=False
    )

    assert context.messages[0].images == []


def test_message_scaffolding_overhead_is_counted(context_builder: ContextBuilder):
    # The question is sent as a chat message, not raw text — the count must
    # include the per-message wrapper, so it exceeds the bare text tokens.
    context = context_builder.build_context(input_str=QUESTION, max_tokens=10000)

    assert context.token_count > count_tokens(QUESTION)


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
