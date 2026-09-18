# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import UUID

from fastapi import APIRouter, Request, Response

from eneo.assistants.api import assistant_protocol
from eneo.main.config import get_settings
from eneo.server.dependencies.widget_auth import (
    ActiveWidget,
    PublicContainer,
    VisitorContainer,
    client_ip,
)
from eneo.server.protocol import responses
from eneo.sessions.session import AskChatResponse, SessionFeedback, SessionPublic
from eneo.sessions.session_protocol import to_session_public
from eneo.widgets.domain.exceptions import ChallengeInvalidError
from eneo.widgets.domain.visitor import WidgetPrincipal
from eneo.widgets.domain.widget import BotProtection, frame_ancestor_sources
from eneo.widgets.presentation.public_widget_models import (
    VisitorSession,
    VisitorSessionRequest,
    WidgetAsk,
    WidgetChallenge,
    WidgetPublicConfig,
)

# Mounted under /widgets next to the admin router; the two never share a
# path shape (admin ids are UUIDs, public ids are `wgt_…`).
router = APIRouter()


def _etag(widget_id: str, updated_at: str, generation: int) -> str:
    return f'W/"{widget_id}:{updated_at}:{generation}"'


@router.get(
    "/{public_id}/config/",
    response_model=WidgetPublicConfig,
    description=(
        "Display configuration for an active widget. Cacheable for a minute;"
        " never includes origins, internal ids or model names."
    ),
    responses={
        **responses.get_responses([404]),
        304: {"description": "Not modified (matching ETag)."},
    },
)
async def get_widget_config(request: Request, response: Response, widget: ActiveWidget):
    assert widget.id is not None and widget.updated_at is not None
    etag = _etag(str(widget.id), widget.updated_at.isoformat(), widget.token_generation)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=60"
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=dict(response.headers))
    return WidgetPublicConfig(
        public_id=widget.public_id,
        name=widget.name,
        texts=widget.texts,
        theme=widget.theme,
        language=widget.language,
        bot_protection=widget.bot_protection,
        max_question_chars=widget.limits.max_question_chars,
        token_generation=widget.token_generation,
        frame_ancestors=frame_ancestor_sources(widget.allowed_origins),
    )


@router.get(
    "/{public_id}/challenge/",
    response_model=WidgetChallenge,
    description=(
        "Issue an ALTCHA proof-of-work challenge. Solve it in the browser and"
        " send the payload when creating a visitor session."
    ),
    responses=responses.get_responses([404, 429, 503]),
)
async def get_widget_challenge(
    request: Request,
    response: Response,
    widget: ActiveWidget,
    container: PublicContainer,
):
    await container.widget_limiter().check_challenge(widget, client_ip(request))
    response.headers["Cache-Control"] = "no-store"
    challenge = container.widget_altcha_service().create_challenge()
    return WidgetChallenge.model_validate(challenge)


@router.post(
    "/{public_id}/visitor-sessions/",
    response_model=VisitorSession,
    description=(
        "Mint a short-lived visitor token. A new visitor sends a solved"
        " challenge; an existing visitor rotates silently with"
        " `previous_token` while it is valid or recently expired."
    ),
    responses=responses.get_responses([400, 401, 404, 429, 503]),
)
async def create_visitor_session(
    request: Request,
    body: VisitorSessionRequest,
    widget: ActiveWidget,
    container: PublicContainer,
):
    settings = get_settings()
    limiter = container.widget_limiter()
    tokens = container.widget_visitor_token_service()
    identity = container.widget_visitor_identity()
    await limiter.check_mint(widget, client_ip(request))

    preview = False
    if body.previous_token is not None:
        claims = tokens.verify(
            body.previous_token,
            widget,
            grace_seconds=settings.widget_visitor_token_grace_seconds,
        )
        visitor_id = claims.visitor_id
        preview = claims.preview
    elif body.altcha is not None:
        await container.widget_altcha_service().verify(body.altcha)
        visitor_id = identity.resolve(widget, body.visitor_id, body.visitor_key)
    elif widget.bot_protection == BotProtection.NONE:
        visitor_id = identity.resolve(widget, body.visitor_id, body.visitor_key)
    else:
        raise ChallengeInvalidError(
            "A solved challenge is required.", code="challenge_required"
        )

    token, expires_in = tokens.mint(widget, visitor_id, preview=preview)
    return VisitorSession(
        token=token,
        expires_in=expires_in,
        visitor_id=visitor_id,
        visitor_key=identity.key_for(widget, visitor_id),
    )


def _principal(request: Request) -> WidgetPrincipal:
    return request.state.widget_principal


@router.post(
    "/{public_id}/ask/",
    response_model=AskChatResponse,
    description=(
        "Ask the widget's assistant as a visitor. Always streams Server-Sent"
        " Events. Pass `session_id` to continue one of the visitor's own"
        " sessions; tools, uploads and MCP servers are never available here."
    ),
    responses=responses.streaming_response(AskChatResponse, [400, 401, 404, 429, 503]),
)
async def ask_widget(request: Request, body: WidgetAsk, container: VisitorContainer):
    response = await container.widget_ask_service().ask(
        _principal(request),
        question=body.question,
        session_id=body.session_id,
        client_ip=client_ip(request),
    )
    # Conversation-protocol events (first_chunk/text/...) so the embed page can
    # drive the same ChatService as the rest of the app.
    return await assistant_protocol.to_conversation_response(
        response=response, stream=True, show_pricing=False
    )


@router.get(
    "/{public_id}/sessions/{session_id}/",
    response_model=SessionPublic,
    description="Restore one of the visitor's own sessions after a reload.",
    responses=responses.get_responses([401, 404]),
)
async def get_widget_session(
    request: Request, session_id: UUID, container: VisitorContainer
):
    session = await container.widget_ask_service().get_session(
        _principal(request), session_id
    )
    return to_session_public(session)


@router.post(
    "/{public_id}/sessions/{session_id}/feedback/",
    response_model=SessionPublic,
    description=(
        "Leave feedback on one of the visitor's own sessions. Free text is"
        " dropped unless the widget stores feedback text."
    ),
    responses=responses.get_responses([401, 404]),
)
async def leave_widget_feedback(
    request: Request,
    session_id: UUID,
    feedback: SessionFeedback,
    container: VisitorContainer,
):
    session = await container.widget_ask_service().leave_feedback(
        _principal(request), session_id, feedback
    )
    return to_session_public(session)
