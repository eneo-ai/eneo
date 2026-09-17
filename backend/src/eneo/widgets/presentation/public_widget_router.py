# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from uuid import uuid4

from fastapi import APIRouter, Request, Response

from eneo.main.config import get_settings
from eneo.server.dependencies.widget_auth import (
    ActiveWidget,
    PublicContainer,
    client_ip,
)
from eneo.server.protocol import responses
from eneo.widgets.domain.exceptions import ChallengeInvalidError
from eneo.widgets.domain.widget import BotProtection
from eneo.widgets.presentation.public_widget_models import (
    VisitorSession,
    VisitorSessionRequest,
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
    await limiter.check_mint(widget, client_ip(request))

    if body.previous_token is not None:
        claims = tokens.verify(
            body.previous_token,
            widget,
            grace_seconds=settings.widget_visitor_token_grace_seconds,
        )
        visitor_id = claims.visitor_id
    elif body.altcha is not None:
        await container.widget_altcha_service().verify(body.altcha)
        visitor_id = body.visitor_id or uuid4()
    elif widget.bot_protection == BotProtection.NONE:
        visitor_id = body.visitor_id or uuid4()
    else:
        raise ChallengeInvalidError(
            "A solved challenge is required.", code="challenge_required"
        )

    token, expires_in = tokens.mint(widget, visitor_id)
    return VisitorSession(token=token, expires_in=expires_in, visitor_id=visitor_id)
