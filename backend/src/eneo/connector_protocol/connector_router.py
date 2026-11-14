"""The connector protocol's routes: Eneo as a connector of another system.

Mounted under one base path, which is the address an administrator registers
in the calling system. The paths below it are the protocol's own and carry no
trailing slash. Requests are read from their raw body (the caller's assertion
is bound to those bytes) and every refusal has the protocol's error shape.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sse_starlette import ServerSentEvent

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.connector_protocol import errors
from eneo.connector_protocol.answer_events import answer_events
from eneo.connector_protocol.errors import ConnectorProtocolError
from eneo.connector_protocol.manifest import ASSISTANTS, MANIFEST, MAX_ASSISTANTS
from eneo.conversations.question_quote import QuestionContext
from eneo.database.database import AsyncSession
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose
from eneo.server.dependencies.connector_auth import ConnectorCall, VerifiedCall
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.server.protocol.sse import ClosingEventSourceResponse

logger = get_logger(__name__)

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
_CONNECTOR_REASON = (
    "Called by an installation the tenant trusts, for one person: the shared "
    "key and the installation's signed, request-bound assertion are verified "
    "first, then the person's own identity-provider token is admitted like a "
    "bearer request's, and the assistant and session services decide what that "
    "person may list and ask."
)
# What an answer may not do in the calling system's conversation: produce
# files. These functions are left out of the turn.
_NO_FILES: list[CapabilityPurpose] = [
    "image_generation",
    "file_creation",
    "file_analysis",
    "compute",
    "charts",
]
_MAX_NAME = 120
_MAX_DESCRIPTION = 400


class _ContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=12_000)]


class _Ask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant: UUID
    session: UUID | None = None
    # Exactly as the person typed it.
    question: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    context: list[_ContextItem] = Field(default=[], max_length=8)


class _AskBody(BaseModel):
    # ``actor`` is the caller's view of the person, verified with the
    # assertion and never used to decide access.
    ask: _Ask


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        parsed: object = json.loads(body)
    except (ValueError, RecursionError) as exc:
        raise errors.invalid() from exc
    if not isinstance(parsed, dict):
        raise errors.invalid()
    return cast(dict[str, Any], parsed)


@router.get(
    "/clew/manifest",
    description=(
        "The connector manifest: what a calling installation may ask of Eneo. "
        "Answers 404 until an administrator has added an installation."
    ),
    response_model=None,
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason=(
        "The protocol reads the manifest before it has credentials. It is the "
        "same fixed document for everyone and names no tenant, person or "
        "assistant."
    ),
)
async def get_manifest(
    container: Annotated[Container, Depends(get_container())],
) -> JSONResponse:
    if not await container.connector_installation_repo().any_exists():
        raise errors.not_found("Okänd adress.")
    return JSONResponse(MANIFEST, headers=_NO_STORE)


async def _list_assistants(container: Container) -> dict[str, Any]:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        offered = await container.assistant_service().get_external_client_assistants()
    return {
        "assistants": [
            {
                "ref": str(assistant.id),
                "name": _clip(assistant.name, _MAX_NAME),
                **(
                    {"description": _clip(assistant.description, _MAX_DESCRIPTION)}
                    if assistant.description
                    else {}
                ),
            }
            for assistant, _space in offered[:MAX_ASSISTANTS]
        ]
    }


@router.post(
    "/clew/capabilities/{name}",
    description=(
        "One read for one person. `eneo.assistants` lists the assistants the "
        "person may ask from other systems."
    ),
    response_model=None,
    responses=responses.get_responses([400, 401, 403, 404, 503]),
)
@endpoint_access(
    authentication=Authentication.CONNECTOR,
    authorization=Authorization.CONNECTOR,
    reason=_CONNECTOR_REASON,
)
async def call_capability(name: str, call: VerifiedCall) -> JSONResponse:
    body = _json_object(call.body)
    if name != ASSISTANTS:
        raise errors.not_found("Okänd förmåga.")
    # The read takes no input; anything sent is not for it.
    if body.get("input") not in (None, {}):
        raise errors.invalid()
    container = await call.as_person()
    return JSONResponse(
        {"output": await _list_assistants(container)}, headers=_NO_STORE
    )


def _conversation_link(assistant_id: UUID, session_id: UUID) -> str | None:
    """Where the person continues the conversation in Eneo's own interface."""
    origin = get_settings().public_origin
    if not origin or not origin.startswith("https://"):
        return None
    return f"{origin.rstrip('/')}/dashboard/{assistant_id}/{session_id}"


def _sse(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[ServerSentEvent]:
    async def stream() -> AsyncIterator[ServerSentEvent]:
        async for event in events:
            yield ServerSentEvent(
                data=json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            )

    return stream()


async def _audit_question(
    call: ConnectorCall, ask: _Ask, session_id: UUID, assistant: Any, space: Any
) -> None:
    """Record which installation a question came through. Never its text."""
    user = call.container.user()
    await call.container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.CONNECTOR_QUESTION_ASKED,
        entity_type=EntityType.ASSISTANT,
        entity_id=ask.assistant,
        description="Asked an assistant through a connected installation",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            space=space,
            extra={
                "installation_id": str(call.installation.id),
                "installation_name": call.installation.name,
                "session_id": str(session_id),
                "follow_up": ask.session is not None,
            },
        ),
    )


@router.post(
    "/clew/ask",
    description=(
        "One question from one person to one assistant, answered as a stream "
        "of events: the answer's text, the sources it cites, then `done` with "
        "the session to continue in, or `error`."
    ),
    responses=responses.streaming_response(response_codes=[400, 401, 403, 404, 503]),
)
@endpoint_access(
    authentication=Authentication.CONNECTOR,
    authorization=Authorization.CONNECTOR,
    reason=_CONNECTOR_REASON,
)
async def ask_assistant(call: VerifiedCall):
    try:
        ask = _AskBody.model_validate(_json_object(call.body)).ask
    except ValidationError as exc:
        raise errors.invalid() from exc
    container = await call.as_person()

    session = cast(AsyncSession, container.session())
    try:
        async with session.begin():
            # The calling system listed the assistant for the person a moment
            # ago, but its key could leak: decide here too, by the same rule.
            offered = (
                await container.assistant_service().get_external_client_assistants(
                    assistant_id_filter=ask.assistant
                )
            )
            if not offered:
                raise errors.not_found(
                    "Assistenten finns inte eller kan inte frågas härifrån."
                )
            assistant, space = offered[0]
            if ask.session is not None:
                # The person's own conversation with this very assistant.
                await container.session_service().get_session_by_uuid(
                    ask.session, assistant_id=ask.assistant
                )
            response = await container.conversation_service().ask_conversation(
                question=ask.question,
                context=[
                    QuestionContext(label=item.label, text=item.text)
                    for item in ask.context
                ],
                session_id=ask.session,
                assistant_id=None if ask.session is not None else ask.assistant,
                stream=True,
                version=2,
                require_tool_approval=False,
                disabled_capabilities=_NO_FILES,
            )
    except ConnectorProtocolError:
        raise
    except UnauthorizedException as exc:
        if ask.session is not None:
            # Whose a conversation is stays unsaid.
            raise errors.not_found("Konversationen finns inte.") from exc
        raise errors.denied() from exc
    except NotFoundException as exc:
        raise errors.not_found(
            "Assistenten eller konversationen finns inte längre i Eneo."
        ) from exc
    except BadRequestException as exc:
        raise errors.invalid() from exc
    except Exception as exc:
        logger.exception("A question from a calling installation could not be asked")
        raise errors.unavailable() from exc

    await _audit_question(call, ask, response.session.id, assistant, space)
    return ClosingEventSourceResponse(
        _sse(
            answer_events(
                response,
                link=_conversation_link(ask.assistant, response.session.id),
            )
        ),
        ping=15,
        sep="\n",
        headers=_NO_STORE,
        closes=[response.answer],
    )
