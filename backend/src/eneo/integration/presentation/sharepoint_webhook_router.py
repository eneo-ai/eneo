import json
from typing import Annotated, Optional, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointWebhookPayload,
)
from eneo.integration.infrastructure.detached_tasks import run_detached
from eneo.integration.infrastructure.sharepoint_subscription_worker import (
    maintain_subscriptions,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import get_container

logger = get_logger(__name__)

router = APIRouter()

# Graph batches a handful of small notifications per call; anything larger is
# not a notification and is refused before any database or Redis work.
MAX_WEBHOOK_BODY_BYTES = 256 * 1024
# Graph's validation tokens are a few hundred characters at most. The token is
# echoed back verbatim to anyone who calls the public URL, so it is bounded.
MAX_VALIDATION_TOKEN_LENGTH = 1024


def _bad_request(detail: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": detail})


def _validation_echo(validation_token: str) -> Response:
    """Graph's subscription handshake: the token back as plain text."""
    if len(validation_token) > MAX_VALIDATION_TOKEN_LENGTH:
        logger.warning(
            "Rejecting SharePoint webhook validation: token longer than %s characters",
            MAX_VALIDATION_TOKEN_LENGTH,
        )
        return _bad_request("validationToken is too long")
    return PlainTextResponse(
        content=validation_token, headers={"X-Content-Type-Options": "nosniff"}
    )


async def _read_capped_body(request: Request) -> Optional[bytes]:
    """The request body, or None once it exceeds MAX_WEBHOOK_BODY_BYTES."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_WEBHOOK_BODY_BYTES:
                return None
        except ValueError:
            return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


# Both paths serve both kinds of notification: a lifecycle event
# (reauthorization, removal, missed notifications) is told from a change by
# its lifecycleEvent field. Graph posts lifecycle events to the webhook path by
# default; the lifecycle path is for SHAREPOINT_WEBHOOK_LIFECYCLE_NOTIFICATION_URL
# pointing at it. Graph is its only caller, so it stays out of the published API.
@router.get(
    "/sharepoint/webhook/lifecycle/",
    description="Graph validation handshake for the lifecycle notification URL.",
    responses={200: {"description": "Validation token echoed as plain text."}},
    response_model=None,
    include_in_schema=False,
)
@router.get(
    "/sharepoint/webhook/",
    description=(
        "Echo the Microsoft Graph validation token (plain text) when present, "
        "otherwise report webhook endpoint health."
    ),
    responses={
        200: {
            "description": (
                "Validation token echoed as plain text, or webhook health status."
            ),
            "content": {
                "text/plain": {"schema": {"type": "string"}},
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"status": {"type": "string"}},
                        "required": ["status"],
                    }
                },
            },
        },
    },
    response_model=None,
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Graph subscription handshake is public; notification service validates subscription clientState before processing.",
)
async def sharepoint_webhook_validation(validationToken: Optional[str] = None):
    if validationToken:
        logger.debug("SharePoint webhook validation token received via GET")
        return _validation_echo(validationToken)
    return {"status": "ok"}


@router.post(
    "/sharepoint/webhook/lifecycle/",
    description=(
        "Handle Graph lifecycle notifications for SharePoint subscriptions; echo "
        "the Graph validation token (plain text) during the handshake."
    ),
    response_class=Response,
    responses={202: {"description": "Lifecycle notifications accepted."}},
    response_model=None,
    include_in_schema=False,
)
@router.post(
    "/sharepoint/webhook/",
    description=(
        "Handle SharePoint change notifications; echo the Graph validation token "
        "(plain text) during the subscription handshake."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Microsoft Graph validation token echoed as plain text.",
            "content": {"text/plain": {"schema": {"type": "string"}}},
        },
        400: {
            "description": "Body is not a JSON notification object or exceeds 256 KB.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"detail": {"type": "string"}},
                        "required": ["detail"],
                    }
                }
            },
        },
        202: {
            "description": "SharePoint notifications accepted for processing.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"status": {"type": "string"}},
                        "required": ["status"],
                    }
                }
            },
        },
    },
    response_model=None,
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Graph subscription handshake is public; notification service validates subscription clientState before processing.",
)
async def sharepoint_webhook(
    request: Request,
    container: Annotated[
        Container, Depends(get_container(with_user=False, with_transaction=False))
    ],
    validationToken: Optional[str] = None,
):
    if validationToken:
        # Microsoft Graph validation handshake
        logger.debug("SharePoint webhook validation token received")
        return _validation_echo(validationToken)

    body = await _read_capped_body(request)
    if body is None:
        logger.warning(
            "Rejecting SharePoint webhook: body exceeds %s bytes",
            MAX_WEBHOOK_BODY_BYTES,
        )
        return _bad_request("Request body too large")
    try:
        decoded = cast(object, json.loads(body))
    except (ValueError, RecursionError):
        # RecursionError: nesting deep enough to exhaust the parser's stack
        # fits well under the size cap.
        logger.warning("Rejecting SharePoint webhook: body is not JSON")
        return _bad_request("Request body must be a JSON object")
    if not isinstance(decoded, dict) or not isinstance(
        cast(dict[str, object], decoded).get("value", []), list
    ):
        logger.warning(
            "Rejecting SharePoint webhook: body is not a notification object"
        )
        return _bad_request("Request body must be a JSON object with a 'value' list")

    # Avoid logging full payload/headers since they may contain sensitive metadata.
    payload = cast(SharePointWebhookPayload, decoded)
    notifications = payload.get("value", [])
    logger.info(
        "Received SharePoint webhook with %s notification(s)", len(notifications)
    )

    # The transaction opens only for notifications carrying the configured
    # clientState, so junk or forged bodies posted at the public URL cost no
    # database connection. Rejections are acknowledged like any other body;
    # the response must not tell a sender whether its secret was right.
    service = container.sharepoint_webhook_service()
    accepted = service.authenticated_notifications(payload)
    if accepted:
        first = accepted[0]
        logger.debug(
            "SharePoint webhook sample: subscriptionId=%s resource=%s changeType=%s",
            first.get("subscriptionId"),
            first.get("resource"),
            first.get("changeType"),
        )
        session = cast(AsyncSession, container.session())
        async with session.begin():
            maintenance = await service.handle_notifications(accepted)
        if maintenance:
            # Graph wants the acknowledgement quickly; renewing or recreating a
            # subscription takes Graph calls of its own.
            run_detached(maintain_subscriptions(maintenance))

    return JSONResponse(status_code=202, content={"status": "acknowledged"})
