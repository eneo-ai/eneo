from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.container import get_container

logger = get_logger(__name__)

router = APIRouter()


@router.get("/sharepoint/webhook/")
async def sharepoint_webhook_validation(validationToken: Optional[str] = None):
    if validationToken:
        logger.debug("SharePoint webhook validation token received via GET")
        return PlainTextResponse(content=validationToken)
    return {"status": "ok"}


@router.post("/sharepoint/webhook/")
async def sharepoint_webhook(
    request: Request,
    validationToken: Optional[str] = None,
    container: Container = Depends(get_container(with_user=False)),
):
    if validationToken:
        # Microsoft Graph validation handshake
        logger.debug("SharePoint webhook validation token received")
        return PlainTextResponse(content=validationToken)

    # Avoid logging full payload/headers since they may contain sensitive metadata.
    payload: Dict[str, Any] = await request.json()
    notifications = payload.get("value", [])
    logger.info("Received SharePoint webhook with %s notification(s)", len(notifications))
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
