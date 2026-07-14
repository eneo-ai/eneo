# MIT License

from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.questions.question import MessageLogging
from eneo.questions.question_protocol import to_question_logging
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.get(
    "/{message_id}/",
    response_model=MessageLogging,
    description="Get the logging details for a single message by id.",
    responses=responses.get_responses([400, 404]),
)
async def get_logging_details(
    message_id: UUID,
    container: Container = Depends(
        get_container(with_user=True)  # pyright: ignore[reportCallInDefaultInitializer]  # FastAPI DI; evaluated at request time
    ),
) -> MessageLogging:
    question = await container.question_repo().get(message_id)
    if question is None or question.session_id is None:
        # Service questions have no session and no conversation surface.
        raise NotFoundException("Question not found")

    # Access follows the session the message belongs to: the session owner may
    # read it, and insight-permitted admins may read it (the admin insights
    # view renders these logging details). Both failures collapse to 404 so
    # the endpoint does not leak message existence across tenants.
    try:
        await container.session_service().get_session_by_uuid(question.session_id)
    except (NotFoundException, UnauthorizedException, BadRequestException):
        try:
            await container.analysis_service().get_insight_session(
                session_id=question.session_id
            )
        except (NotFoundException, UnauthorizedException, BadRequestException):
            raise NotFoundException("Question not found")

    if question.logging_details is None:
        raise BadRequestException("Question was not logged.")

    return to_question_logging(question)
