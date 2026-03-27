from eneo.info_blobs.info_blob import InfoBlobMetadata, InfoBlobPublicNoText
from eneo.logging import logging_protocol
from eneo.questions.question import (
    Message,
    MessageLogging,
    Question,
    ToolAssistant,
    UseTools,
    WebSearchResultPublic,
)


def to_question_public(question: Question):
    assistants = []

    # Add assistant if it exists
    if question.assistant_id and question.assistant_name:
        assistants.append(
            ToolAssistant(id=question.assistant_id, handle=question.assistant_name)
        )

    tools = UseTools(assistants=assistants)

    return Message(
        **question.model_dump(exclude={"references", "assistant_id", "assistant_name"}),
        references=[
            InfoBlobPublicNoText(
                **blob.model_dump(),
                metadata=InfoBlobMetadata(**blob.model_dump()),
            )
            for blob in question.info_blobs
        ],
        tools=tools,
        web_search_references=[
            WebSearchResultPublic(
                id=web_search_result.id,
                title=web_search_result.title,
                url=web_search_result.url,
            )
            for web_search_result in question.web_search_results
        ],
    )


def to_question_logging(question: Question):
    question_public = to_question_public(question)
    return MessageLogging(
        **question_public.model_dump(),
        logging_details=logging_protocol.from_domain(question.logging_details),
    )
