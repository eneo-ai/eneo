# MIT License

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.authentication.auth_dependencies import require_session_auth
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException
from eneo.questions.question import MessageLogging
from eneo.questions.question_protocol import to_question_logging
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter(dependencies=[Depends(require_session_auth)])


@router.get(
    "/{message_id}/",
    response_model=MessageLogging,
    description="Get the logging details for a single message by id.",
    responses=responses.get_responses([400, 403, 404]),
)
async def get_logging_details(
    message_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> MessageLogging:
    question = await container.analysis_service().get_message_for_insights(
        message_id=message_id
    )

    if question.logging_details is None:
        raise BadRequestException("Question was not logged.")

    return to_question_logging(question)
