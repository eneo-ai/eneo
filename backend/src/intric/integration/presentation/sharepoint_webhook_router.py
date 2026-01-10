from typing import Any, Dict, Optional
import json
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

    # Läs och logga hela inkommande payload
    payload: Dict[str, Any] = await request.json()
    logger.info("Inkommande SharePoint-webhook payload:")
    logger.info(json.dumps(payload, indent=2, ensure_ascii=False))

    # Om du även vill logga headers (kan vara bra för felsökning):
    logger.debug(f"Request headers: {dict(request.headers)}")

    service = container.sharepoint_webhook_service()
    await service.handle_notifications(payload)

    return JSONResponse(status_code=202, content={"status": "acknowledged"})