from eneo.info_blobs.info_blob import InfoBlobMetadata, InfoBlobPublicNoText
from eneo.logging import logging_protocol
from eneo.questions.question import (
    Message,
    MessageLogging,
    Question,
    ToolAssistant,
    UseTools,
)


def to_question_public(question: Question) -> Message:
    assistants: list[ToolAssistant] = []

    # Add assistant if it exists
    if question.assistant_id and question.assistant_name:
        assistants.append(
            ToolAssistant(id=question.assistant_id, handle=question.assistant_name)
        )

    tools = UseTools(assistants=assistants)
    public_tool_calls = [
        tool_call.model_copy(update={"result": None, "structured_content": None})
        for tool_call in (question.tool_calls or [])
    ]

    return Message(
        **question.model_dump(
            exclude={
                "references",
                "assistant_id",
                "assistant_name",
                "mcp_tool_references",
                "skill_activation",
                "tool_calls",
                "consultations",
                "num_tokens_question",
                "num_tokens_answer",
            }
        ),
        references=[
            InfoBlobPublicNoText(
                **blob.model_dump(),
                metadata=InfoBlobMetadata(**blob.model_dump()),
            )
            for blob in question.info_blobs
        ],
        tools=tools,
        mcp_tool_references=list(question.mcp_tool_references),
        tool_calls=public_tool_calls,
        consultations=[item.public() for item in question.consultations or []],
        num_tokens_question=question.num_tokens_question
        + sum(item.input_tokens or 0 for item in question.consultations or []),
        num_tokens_answer=question.num_tokens_answer
        + sum(item.output_tokens or 0 for item in question.consultations or []),
    )


def to_question_logging(question: Question) -> MessageLogging:
    question_public = to_question_public(question)
    # Caller guarantees logging_details is not None before calling this function
    assert question.logging_details is not None
    return MessageLogging(
        **question_public.model_dump(),
        logging_details=logging_protocol.from_domain(question.logging_details),
    )
