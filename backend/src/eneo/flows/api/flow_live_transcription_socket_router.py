"""The live transcription WebSocket: redeem a ticket, then relay.

Mounted outside the flows router because FastAPI builds ``Request``-based
dependencies (the user container, route guards) only for HTTP. Everything
those would check already happened when the ticket was issued; this endpoint
checks the Origin (the CORS middleware skips WebSockets), redeems the
single-use ticket, and re-reads the model so a capability or provider switched
off in the meantime is honoured.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from dependency_injector import providers
from fastapi import APIRouter, WebSocket, status

from eneo.allowed_origins.get_origin_callback import get_origin
from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.flows.api.flow_live_transcription_models import (
    LIVE_TRANSCRIPTION_SOCKET_PATH,
    LIVE_TRANSCRIPTION_SUBPROTOCOL,
    LIVE_TRANSCRIPTION_TICKET_PREFIX,
)
from eneo.flows.runtime.live_transcription.relay import (
    LiveSessionEnded,
    LiveSessionStats,
    relay_live_session,
)
from eneo.flows.runtime.live_transcription.tickets import (
    LiveTranscriptionGrant,
    LiveTranscriptionTicketStore,
)
from eneo.flows.runtime.live_transcription.upstream import realtime_websocket_url
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    ProviderInactiveException,
    ProviderNotFoundException,
)
from eneo.main.logging import get_logger
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_provider_kwargs,
    load_active_litellm_provider,
)
from eneo.transcription_models.domain.realtime import speaks_realtime_dialect

logger = get_logger(__name__)

router = APIRouter()
__all__ = ["router"]


@dataclass(frozen=True)
class _UpstreamTarget:
    url: str
    api_key: str | None
    model_name: str


@router.websocket(LIVE_TRANSCRIPTION_SOCKET_PATH)
async def live_transcription_socket(websocket: WebSocket) -> None:
    offered = [
        protocol.strip()
        for protocol in (websocket.headers.get("sec-websocket-protocol") or "").split(
            ","
        )
    ]
    ticket = next(
        (
            protocol.removeprefix(LIVE_TRANSCRIPTION_TICKET_PREFIX)
            for protocol in offered
            if protocol.startswith(LIVE_TRANSCRIPTION_TICKET_PREFIX)
        ),
        None,
    )
    if (
        LIVE_TRANSCRIPTION_SUBPROTOCOL not in offered
        or not ticket
        or not await _origin_allowed(websocket)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    grant = await LiveTranscriptionTicketStore(Container.redis_client()).redeem(ticket)
    if grant is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept(subprotocol=LIVE_TRANSCRIPTION_SUBPROTOCOL)
    stats = LiveSessionStats()
    try:
        target = await _load_upstream_target(grant)
        outcome = await relay_live_session(
            websocket,
            upstream_url=target.url,
            api_key=target.api_key,
            model_name=target.model_name,
            max_seconds=grant.max_seconds,
            stats=stats,
        )
    except LiveSessionEnded as ended:
        await websocket.send_json(
            {
                "type": "error",
                "code": ended.code,
                "message": ended.message,
                "retryable": ended.retryable,
            }
        )
        outcome = ended.code
    logger.info(
        "flow live transcription session ended",
        extra={
            "outcome": outcome,
            "tenant_id": str(grant.tenant_id),
            "flow_id": str(grant.flow_id),
            "step_id": str(grant.step_id),
            "model_id": str(grant.model_id),
            "audio_seconds": round(stats.audio_seconds, 1),
        },
    )
    await _close_quietly(websocket)


async def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if origin is None:
        return True  # server-side clients (a module backend) send no Origin
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    return await get_origin(
        origin, websocket.headers, False, websocket.url.replace(scheme=scheme)
    )


async def _load_upstream_target(grant: LiveTranscriptionGrant) -> _UpstreamTarget:
    unavailable = LiveSessionEnded(
        "model_unavailable",
        "The transcription model is no longer available for live use.",
    )
    async with sessionmanager.session() as session, session.begin():
        container = Container(session=providers.Object(session))
        row = (
            await session.execute(
                sa.select(
                    TranscriptionModels.model_name,
                    TranscriptionModels.provider_id,
                    TranscriptionModels.supports_realtime,
                ).where(
                    TranscriptionModels.id == grant.model_id,
                    TranscriptionModels.tenant_id == grant.tenant_id,
                    TranscriptionModels.is_enabled.is_(True),
                    TranscriptionModels.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None or not row.supports_realtime or row.provider_id is None:
            raise unavailable
        try:
            provider = await load_active_litellm_provider(
                session=session, provider_id=row.provider_id, tenant_id=grant.tenant_id
            )
            if not speaks_realtime_dialect(provider.provider_type):
                raise unavailable
            kwargs = build_litellm_provider_kwargs(
                provider.create_credential_resolver(container.encryption_service())
            )
            url = realtime_websocket_url(str(kwargs["api_base"]))
        except (
            APIKeyNotConfiguredException,
            ProviderInactiveException,
            ProviderNotFoundException,
            KeyError,
            ValueError,
        ) as exc:
            raise unavailable from exc
    return _UpstreamTarget(
        url=url, api_key=kwargs.get("api_key"), model_name=row.model_name
    )


async def _close_quietly(websocket: WebSocket) -> None:
    try:
        await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
    except RuntimeError:
        pass  # already closed by the client
