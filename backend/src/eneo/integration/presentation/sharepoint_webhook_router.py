import json
from typing import Annotated, Optional, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.integration.infrastructure.content_service.types import (
    SharePointWebhookPayload,
)
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import get_container

logger = get_logger(__name__)

router = APIRouter()

# Graph batches a handful of small notifications per call; anything larger is
# not a notification and is refused before any database or Redis work.
MAX_WEBHOOK_BODY_BYTES = 256 * 1024


def _bad_request(detail: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": detail})


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
        return PlainTextResponse(content=validationToken)
    return {"status": "ok"}


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
    container: Annotated[Container, Depends(get_container(with_user=False))],
    validationToken: Optional[str] = None,
):
    if validationToken:
        # Microsoft Graph validation handshake
        logger.debug("SharePoint webhook validation token received")
        return PlainTextResponse(content=validationToken)

    body = await _read_capped_body(request)
    if body is None:
        logger.warning(
            "Rejecting SharePoint webhook: body exceeds %s bytes",
            MAX_WEBHOOK_BODY_BYTES,
        )
        return _bad_request("Request body too large")
    try:
        decoded = cast(object, json.loads(body))
    except ValueError:
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
    if notifications:
        first = notifications[0]
        logger.debug(
            "SharePoint webhook sample: subscriptionId=%s resource=%s changeType=%s",
            first.get("subscriptionId"),
            first.get("resource"),
            first.get("changeType"),
        )

    service = container.sharepoint_webhook_service()
    await service.handle_notifications(payload)

    return JSONResponse(status_code=202, content={"status": "acknowledged"})
