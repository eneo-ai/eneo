import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from intric.assistants.api import assistant_protocol
from intric.assistants.api.assistant_models import (
    AskAssistant,
    AssistantCreatePublic,
    AssistantPublic,
    AssistantUpdatePublic,
    TokenEstimateRequest,
    TokenEstimateResponse,
    TokenEstimateBreakdown,
)
from intric.authentication.auth_models import ApiKey
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.models import NOT_PROVIDED, CursorPaginatedResponse, PaginatedResponse
from intric.prompts.api.prompt_models import PromptSparse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.sessions.session import (
    AskResponse,
    SessionFeedback,
    SessionMetadataPublic,
    SessionPublic,
)
from intric.sessions.session_protocol import (
    to_session_public,
    to_sessions_paginated_response,
)
from intric.spaces.api.space_models import TransferApplicationRequest

router = APIRouter()
logger = logging.getLogger(__name__)

# These limits keep the endpoint responsive while still supporting large-context models.
DEFAULT_CHARS_PER_TOKEN = 6  # Generous factor to cover dense languages
MAX_TOTAL_FILE_SIZE = 50_000_000  # 50 MB
MAX_ABSOLUTE_TEXT_LENGTH = 2_000_000  # 2 MB safeguard in case of misconfigured models


@router.post(
    "/",
    response_model=AssistantPublic,
    responses=responses.get_responses([404]),
    deprecated=True,
)
async def create_assistant(
    assistant: AssistantCreatePublic,
    container: Container = Depends(get_container(with_user=True)),
):
    assistant_service = container.assistant_service()
    assembler = container.assistant_assembler()

    assistant, permissions = await assistant_service.create_assistant(
        name=assistant.name, space_id=assistant.space_id
    )

    return assembler.from_assistant_to_model(assistant, permissions=permissions)


@router.get("/", response_model=PaginatedResponse[AssistantPublic])
async def get_assistants(
    name: str = None,
    for_tenant: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    """Requires Admin permission if `for_tenant` is `true`."""
    service = container.assistant_service()
    assembler = container.assistant_assembler()

    assistants = await service.get_assistants(name, for_tenant)

    assistants = [
        assembler.from_assistant_to_model(assistant)
        for assistant in assistants
        if assistant.completion_model is not None
    ]

    return protocol.to_paginated_response(assistants)


@router.get(
    "/{id}/",
    response_model=AssistantPublic,
    responses=responses.get_responses([400, 404]),
)
async def get_assistant(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.assistant_service()
    assembler = container.assistant_assembler()

    assistant, permissions = await service.get_assistant(assistant_id=id)

    return assembler.from_assistant_to_model(assistant=assistant, permissions=permissions)


@router.post(
    "/{id}/",
    response_model=AssistantPublic,
    responses=responses.get_responses([400, 404]),
)
async def update_assistant(
    id: UUID,
    assistant: AssistantUpdatePublic,
    container: Container = Depends(get_container(with_user=True)),
):
    """Omitted fields are not updated"""
    service = container.assistant_service()
    assembler = container.assistant_assembler()

    attachment_ids = None
    if assistant.attachments is not None:
        attachment_ids = [attachment.id for attachment in assistant.attachments]

    groups = None
    if assistant.groups is not None:
        groups = [group.id for group in assistant.groups]

    websites = None
    if assistant.websites is not None:
        websites = [website.id for website in assistant.websites]

    integration_knowledge_ids = None
    if assistant.integration_knowledge_list is not None:
        integration_knowledge_ids = [i.id for i in assistant.integration_knowledge_list]

    completion_model_id = None
    if assistant.completion_model is not None:
        completion_model_id = assistant.completion_model.id

    completion_model_kwargs = None
    if assistant.completion_model_kwargs is not None:
        completion_model_kwargs = assistant.completion_model_kwargs

    # get original request dict to check if description was actually provided
    # (@partial_model overrides NOT_PROVIDED with None)
    request_dict = assistant.model_dump(exclude_unset=True)
    description = assistant.description
    metadata_json = assistant.metadata_json

    # if description wasn't in the original request, use NOT_PROVIDED
    if "description" not in request_dict:
        description = NOT_PROVIDED

    if "metadata_json" not in request_dict:
        metadata_json = NOT_PROVIDED

    assistant, permissions = await service.update_assistant(
        assistant_id=id,
        name=assistant.name,
        prompt=assistant.prompt,
        completion_model_id=completion_model_id,
        completion_model_kwargs=completion_model_kwargs,
        logging_enabled=assistant.logging_enabled,
        attachment_ids=attachment_ids,
        groups=groups,
        websites=websites,
        integration_knowledge_ids=integration_knowledge_ids,
        description=description,
        insight_enabled=assistant.insight_enabled,
        data_retention_days=assistant.data_retention_days,
        metadata_json=metadata_json,
    )

    return assembler.from_assistant_to_model(assistant, permissions=permissions)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_assistant(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.assistant_service()
    await service.delete_assistant(id)


@router.post(
    "/{id}/sessions/",
    response_model=AskResponse,
    responses=responses.streaming_response(AskResponse, [400, 404]),
)
async def ask_assistant(
    id: UUID,
    ask: AskAssistant,
    version: int = Query(default=1, ge=1, le=2),
    container: Container = Depends(get_container(with_user_from_assistant_api_key=True)),
    db_session: AsyncSession = Depends(get_session_with_transaction),
):
    """Streams the response as Server-Sent Events if stream == true"""
    service = container.assistant_service()

    file_ids = [file.id for file in ask.files]
    tool_assistant_id = None
    if ask.tools is not None and ask.tools.assistants:
        tool_assistant_id = ask.tools.assistants[0].id
    response = await service.ask(
        question=ask.question,
        assistant_id=id,
        file_ids=file_ids,
        stream=ask.stream,
        tool_assistant_id=tool_assistant_id,
        version=version,
    )

    return await assistant_protocol.to_response(
        response=response, db_session=db_session, stream=ask.stream
    )


@router.get(
    "/{id}/sessions/",
    response_model=CursorPaginatedResponse[SessionMetadataPublic],
    responses=responses.get_responses([400, 404]),
)
async def get_assistant_sessions(
    id: UUID,
    limit: int = Query(default=None, gt=0),
    cursor: datetime = None,
    previous: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    assistant_service = container.assistant_service()
    session_service = container.session_service()

    assistant_in_db, _ = await assistant_service.get_assistant(id)

    sessions, total_count = await session_service.get_sessions_by_assistant(
        assistant_id=assistant_in_db.id,
        limit=limit,
        cursor=cursor,
        previous=previous,
    )
    return to_sessions_paginated_response(
        sessions=sessions,
        limit=limit,
        cursor=cursor,
        previous=previous,
        total_count=total_count,
    )


@router.get(
    "/{id}/sessions/{session_id}/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def get_assistant_session(
    id: UUID,
    session_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    session_service = container.session_service()
    session = await session_service.get_session_by_uuid(session_id, assistant_id=id)

    return to_session_public(session)


@router.delete(
    "/{id}/sessions/{session_id}/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def delete_assistant_session(
    id: UUID,
    session_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    session_service = container.session_service()
    session = await session_service.delete(session_id, assistant_id=id)

    return to_session_public(session)


@router.post(
    "/{id}/sessions/{session_id}/",
    response_model=AskResponse,
    responses=responses.streaming_response(AskResponse, [400, 404]),
)
async def ask_followup(
    id: UUID,
    session_id: UUID,
    ask: AskAssistant,
    version: int = Query(default=1, ge=1, le=2),
    container: Container = Depends(get_container(with_user_from_assistant_api_key=True)),
    db_session: AsyncSession = Depends(get_session_with_transaction),
):
    """Streams the response as Server-Sent Events if stream == true"""
    service = container.assistant_service()

    file_ids = [file.id for file in ask.files]
    tool_assistant_id = None
    if ask.tools is not None and ask.tools.assistants:
        tool_assistant_id = ask.tools.assistants[0].id
    response = await service.ask(
        question=ask.question,
        assistant_id=id,
        file_ids=file_ids,
        stream=ask.stream,
        session_id=session_id,
        tool_assistant_id=tool_assistant_id,
        version=version,
    )

    return await assistant_protocol.to_response(
        response=response, db_session=db_session, stream=ask.stream
    )


@router.post(
    "/{id}/sessions/{session_id}/feedback/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def leave_feedback(
    id: UUID,
    session_id: UUID,
    feedback: SessionFeedback,
    container: Container = Depends(get_container(with_user_from_assistant_api_key=True)),
):
    session_service = container.session_service()
    session = await session_service.leave_feedback(
        session_id=session_id, assistant_id=id, feedback=feedback
    )

    return to_session_public(session)


@router.get("/{id}/api-keys/", response_model=ApiKey)
async def generate_read_only_assistant_key(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Generates a read-only api key for this assistant.

    This api key can only be used on `POST /api/v1/assistants/{id}/sessions/`
    and `POST /api/v1/assistants/{id}/sessions/{session_id}/`."""
    service = container.assistant_service()
    return await service.generate_api_key(id)


@router.post("/{id}/transfer/", status_code=204)
async def transfer_assistant_to_space(
    id: UUID,
    transfer_req: TransferApplicationRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.resource_mover_service()
    await service.move_assistant_to_space(
        assistant_id=id,
        space_id=transfer_req.target_space_id,
        move_resources=transfer_req.move_resources,
    )


@router.get(
    "/{id}/prompts/",
    response_model=PaginatedResponse[PromptSparse],
    include_in_schema=get_settings().dev,
)
async def get_prompts(id: UUID, container: Container = Depends(get_container(with_user=True))):
    service = container.assistant_service()
    assembler = container.prompt_assembler()

    prompts = await service.get_prompts_by_assistant(id)
    prompts = [assembler.from_prompt_to_model(prompt) for prompt in prompts]

    return protocol.to_paginated_response(prompts)


@router.post(
    "/{id}/publish/",
    response_model=AssistantPublic,
    responses=responses.get_responses([403, 404]),
)
async def publish_assistant(
    id: UUID,
    published: bool,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.assistant_service()
    assembler = container.assistant_assembler()

    assistant, permissions = await service.publish_assistant(assistant_id=id, publish=published)

    return assembler.from_assistant_to_model(assistant=assistant, permissions=permissions)


@router.post(
    "/{id}/token-estimate",
    response_model=TokenEstimateResponse,
    responses=responses.get_responses([400, 404]),
    summary="Estimate token usage for text and files",
)
async def estimate_tokens(
    id: UUID,
    payload: TokenEstimateRequest,
    container: Container = Depends(get_container(with_user=True)),
) -> TokenEstimateResponse:
    """Estimate token usage for the given text and files for this assistant.

    The Space Actor + FileService stack already enforces tenant and ownership
    boundaries; this endpoint adds lightweight guardrails to keep the operation
    responsive while supporting large-context models.
    """

    from intric.tokens.token_utils import count_tokens, count_assistant_prompt_tokens

    service = container.assistant_service()
    file_service = container.file_service()

    assistant, _ = await service.get_assistant(assistant_id=id)

    if not assistant.completion_model:
        raise HTTPException(status_code=400, detail="Assistant has no model configured")

    model_name = assistant.completion_model.name
    token_limit = assistant.completion_model.token_limit

    max_chars = min(
        MAX_ABSOLUTE_TEXT_LENGTH,
        int(token_limit * DEFAULT_CHARS_PER_TOKEN) if token_limit else MAX_ABSOLUTE_TEXT_LENGTH,
    )

    text = payload.text or ""
    if len(text) > max_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                "Text input is too large for this assistant's context window. "
                f"Reduce the size below {max_chars:,} characters."
            ),
        )

    file_ids = payload.file_ids or []

    prompt_tokens = 0
    if assistant.prompt:
        prompt_text = getattr(assistant.prompt, "prompt", None) or getattr(
            assistant.prompt, "text", None
        )
        if prompt_text:
            prompt_tokens = count_assistant_prompt_tokens(prompt_text, model_name)

    text_tokens = count_tokens(text, model_name) if text else 0

    file_tokens = 0
    file_token_details: dict[str, int] = {}
    if file_ids:
        files = await file_service.get_files_for_token_estimate(file_ids)
        accessible_ids = {file.id for file in files}
        missing_ids = [str(file_id) for file_id in file_ids if file_id not in accessible_ids]
        if missing_ids:
            logger.debug("Skipped token estimate for filtered file IDs: %s", missing_ids)

        total_file_size = sum(file.size for file in files if file.size is not None)
        if total_file_size > MAX_TOTAL_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Combined file content exceeds 50 MB limit. "
                    "Remove one or more files and try again."
                ),
            )

        for file in files:
            tokens = 0
            if file.text:
                try:
                    tokens = count_tokens(file.text, model_name)
                except Exception as exc:  # pragma: no cover - defensive logging path
                    logger.error("Failed to count tokens for file %s: %s", file.id, exc)
                    tokens = len(file.text) // 4

            file_tokens += tokens
            file_token_details[str(file.id)] = tokens

    total_tokens = prompt_tokens + text_tokens + file_tokens
    percentage = (total_tokens / token_limit) * 100 if token_limit > 0 else 0

    return TokenEstimateResponse(
        tokens=total_tokens,
        percentage=round(percentage, 2),
        limit=token_limit,
        breakdown=TokenEstimateBreakdown(
            prompt=prompt_tokens,
            text=text_tokens,
            files=file_tokens,
            file_details=file_token_details,
        ),
    )
