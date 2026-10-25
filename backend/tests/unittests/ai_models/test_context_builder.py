# flake8: noqa

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    FunctionDefinition,
    Message,
    MessageToolCall,
)
from eneo.completion_models.infrastructure.context_builder import (
    ContextBuilder,
    ContextWindowExceededError,
    count_tokens,
)
from eneo.completion_models.infrastructure.static_prompts import (
    ATTACHED_FILE_REFERENCES_INSTRUCTION,
    HALLUCINATION_GUARD,
    SHOW_REFERENCES_PROMPT,
    TOOL_NAMING_INSTRUCTION,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import File, FileType
from eneo.questions.question import ToolCallInfo

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
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
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
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
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
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
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


def test_too_long_question_can_be_rejected_by_strict_callers(
    context_builder: ContextBuilder,
):
    input_str = "This is a loooooong query, longer than 5 tokens"

    with pytest.raises(ContextWindowExceededError) as exc_info:
        context_builder.build_context(
            input_str=input_str,
            max_tokens=5,
            reject_over_limit=True,
        )

    assert exc_info.value.estimated_tokens > 5
    assert exc_info.value.max_tokens == 5


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
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
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
        input_str=QUESTION,
        max_tokens=10000,
        mcp_tools=[
            FunctionDefinition(
                name="lookup_record",
                description="Look up a record in the registry by id.",
                schema={
                    "type": "object",
                    "properties": {"record_id": {"type": "string"}},
                    "required": ["record_id"],
                },
            )
        ],
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


def test_attachment_text_is_sent_whole():
    from eneo.completion_models.infrastructure.context_builder import (
        build_files_string,
    )

    file = MagicMock(
        text="word " * 1000, file_type=FileType.TEXT, mimetype="text/plain"
    )
    file.name = "big.txt"

    result = build_files_string([file])

    # No silent truncation: the whole document text is inlined, with its header.
    assert file.text in result
    assert "FILE: big.txt" in result


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


def test_tool_naming_instruction_is_added_when_tools_are_advertised(
    context_builder: ContextBuilder,
):
    context = context_builder.build_context(
        input_str=QUESTION,
        max_tokens=10000,
        prompt="You are a helpful assistant.",
        extra_tool_dicts=[
            {
                "type": "function",
                "function": {
                    "name": "files__ingest_urls",
                    "description": "Fetch files from HTTPS links.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert TOOL_NAMING_INSTRUCTION in context.prompt
    assert context.prompt.startswith("You are a helpful assistant.")


def test_tool_naming_instruction_is_absent_without_tools(
    context_builder: ContextBuilder,
):
    context = context_builder.build_context(
        input_str=QUESTION,
        max_tokens=10000,
        prompt="You are a helpful assistant.",
    )

    assert context.prompt == "You are a helpful assistant."


_URL_TOOL_DICT = {
    "type": "function",
    "function": {
        "name": "files__read_file",
        "description": "Read an attached file.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def test_file_reference_instruction_requires_references_and_tools(
    context_builder: ContextBuilder,
):
    # The arbitration rule is stated once in the system prompt (the
    # per-message reference block carries mechanics only), and only when
    # there is both a reference to arbitrate and a tool to pass it to.
    file_id = uuid4()
    file = MagicMock(spec=File)
    file.id = file_id
    file.name = "report.csv"
    file.mimetype = "text/csv"
    file.size = 10
    file.file_type = FileType.TEXT
    file.text = "a,b"

    with_both = context_builder.build_context(
        input_str=QUESTION,
        max_tokens=10000,
        prompt="You are a helpful assistant.",
        files=[file],
        file_reference_urls={file_id: "https://x/dl"},
        extra_tool_dicts=[_URL_TOOL_DICT],
    )
    assert ATTACHED_FILE_REFERENCES_INSTRUCTION in with_both.prompt

    without_tools = context_builder.build_context(
        input_str=QUESTION,
        max_tokens=10000,
        prompt="You are a helpful assistant.",
        files=[file],
        file_reference_urls={file_id: "https://x/dl"},
    )
    assert ATTACHED_FILE_REFERENCES_INSTRUCTION not in without_tools.prompt

    without_references = context_builder.build_context(
        input_str=QUESTION,
        max_tokens=10000,
        prompt="You are a helpful assistant.",
        extra_tool_dicts=[_URL_TOOL_DICT],
    )
    assert ATTACHED_FILE_REFERENCES_INSTRUCTION not in without_references.prompt


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


def test_skill_activation_call_is_not_replayed(context_builder: ContextBuilder):
    # The activation tool is rebuilt per turn from the Skill runtime and may
    # not be registered later, so a persisted activation step must not become
    # a tool_use in history.
    tc = ToolCallInfo(
        server_name="skills",
        tool_name="skill-1",
        arguments={"skill_key": "skill-1"},
        tool_call_id="activate-1",
        approved=True,
        result_status="completed",
        result='{"activated": true}',
        mcp_tool_name="eneo_activate_skill",
    )
    session = MagicMock(questions=[_question_mock("Q?", "A.", [tc])])

    context = context_builder.build_context(
        input_str=QUESTION, session=session, max_tokens=10000
    )

    assert context.messages[0].tool_calls == []


def _text_file(text: str = "Text from the file", name: str = "notes.txt") -> File:
    return File(
        id=uuid4(),
        text=text,
        name=name,
        mimetype="text/plain",
        checksum="",
        size=len(text),
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
        file_type=FileType.TEXT,
    )


_LOOKUP_FUNCTION = FunctionDefinition(
    name="lookup_record",
    description="Look up a record in the registry by id.",
    schema={
        "type": "object",
        "properties": {"record_id": {"type": "string"}},
        "required": ["record_id"],
    },
)


def _preflight_shapes() -> dict[str, dict]:
    url_only_attachment = _text_file("Opened with a tool", name="guide.txt")
    current_file = _text_file()
    return {
        "text_only": {},
        "images": {
            "files": [_image_file()],
            "prompt_files": [_image_file()],
        },
        "inline_files_and_attachments": {
            "files": [_text_file()],
            "prompt_files": [_text_file("Attachment text", name="policy.txt")],
            "transcription_inputs": ["A transcribed recording"],
        },
        "url_only_files": {
            "files": [current_file],
            "prompt_files": [url_only_attachment],
            "file_reference_urls": {
                current_file.id: "https://files.example/current",
                url_only_attachment.id: "https://files.example/guide",
            },
            "url_only_prompt_file_ids": {url_only_attachment.id},
            "inline_file_text": False,
        },
        "tools": {
            "mcp_tools": [_LOOKUP_FUNCTION],
            "extra_tool_dicts": [
                {
                    "type": "function",
                    "function": {
                        "name": "mcp__lookup",
                        "description": "Look up a record.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        },
        "knowledge_catalog": {"knowledge_catalog": "- Handbook: staff rules"},
        "long_prompt": {"prompt": "Follow the house style. " * 2000},
    }


@pytest.mark.parametrize("shape", list(_preflight_shapes()))
def test_skipped_accounting_builds_the_same_request(
    context_builder: ContextBuilder, shape: str
):
    # Without history or knowledge the count sizes no budget, so skipping it
    # must leave every part of the request as it is.
    request = {"input_str": QUESTION, "max_tokens": 10000, "version": 2}
    request |= _preflight_shapes()[shape]

    counted = context_builder.build_context(**request)
    skipped = context_builder.build_context(**request, account_tokens=False)

    assert skipped.input == counted.input
    assert skipped.prompt == counted.prompt
    assert skipped.messages == counted.messages
    assert skipped.images == counted.images
    assert skipped.function_definitions == counted.function_definitions
    assert skipped.knowledge_trace == counted.knowledge_trace
    assert counted.token_count > 0
    assert skipped.token_count == 0


def test_skipped_accounting_calls_no_token_counter(
    context_builder: ContextBuilder, monkeypatch: pytest.MonkeyPatch
):
    module = "eneo.completion_models.infrastructure.context_builder"
    calls: list[str] = []
    for name in (
        "count_message_tokens",
        "count_tool_tokens",
        "count_image_tokens_from_blob",
        "count_tokens",
    ):

        def spy(*args, _name=name, **kwargs):
            calls.append(_name)
            return 1

        monkeypatch.setattr(f"{module}.{name}", spy)
    request = {
        "input_str": QUESTION,
        "max_tokens": 10000,
        "prompt": "Be concise.",
        "files": [_image_file()],
        "prompt_files": [_text_file()],
        "mcp_tools": [_LOOKUP_FUNCTION],
    }

    context_builder.build_context(**request, account_tokens=False)
    assert calls == []

    context_builder.build_context(**request)
    assert {
        "count_message_tokens",
        "count_tool_tokens",
        "count_image_tokens_from_blob",
    } <= set(calls)


@pytest.mark.parametrize(
    "budgeted",
    [
        {"session": MagicMock(questions=[])},
        {"info_blob_chunks": [MagicMock(text="knowledge", chunk_no=1)]},
        {"reject_over_limit": True},
    ],
    ids=["session", "knowledge", "reject_over_limit"],
)
def test_accounting_cannot_be_skipped_when_it_sizes_a_budget(
    context_builder: ContextBuilder, budgeted: dict
):
    with pytest.raises(ValueError):
        context_builder.build_context(
            input_str=QUESTION, max_tokens=10000, account_tokens=False, **budgeted
        )


def test_skipped_accounting_logs_no_over_limit_estimate(
    context_builder: ContextBuilder, caplog: pytest.LogCaptureFixture
):
    input_str = "This is a loooooong query, longer than 5 tokens"
    with caplog.at_level("WARNING"):
        context_builder.build_context(input_str=input_str, max_tokens=5)
    assert "Estimated context exceeds configured model limit" in caplog.text

    caplog.clear()
    with caplog.at_level("WARNING"):
        context = context_builder.build_context(
            input_str=input_str, max_tokens=5, account_tokens=False
        )
    assert context.input == input_str
    assert "Estimated context exceeds" not in caplog.text
