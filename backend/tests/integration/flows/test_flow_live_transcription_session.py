"""Live transcription preview: admission over HTTP, then the WebSocket relay.

The WebSocket half runs against the application served by uvicorn on a local
port and a local server speaking vLLM's realtime schema, so ticket redemption,
the Origin check, the provider's stored credentials and the relay run exactly
as a browser or a module backend meets them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
import uvicorn
from fastapi import FastAPI
from httpx import AsyncClient
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from websockets.typing import Origin, Subprotocol

from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.spaces_table import SpacesTranscriptionModels
from eneo.flows.api import flow_live_transcription_socket_router
from eneo.flows.runtime.live_transcription import tickets
from eneo.main.config import get_settings, set_settings
from eneo.users.user import UserAdd, UserState
from tests.integration.module_session_support import (
    enable_module,
    install_module,
    module_login,
)
from tests.unittests.flows.live_transcription_test_support import (
    FakeRealtimeServer,
    fake_realtime_server,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PROVIDER_API_KEY = "live-provider-secret"
TENTH_OF_A_SECOND = b"\x01\x00" * 1600
UNREACHABLE_ENDPOINT = "http://127.0.0.1:9/v1"


@dataclass(frozen=True)
class LiveFlow:
    flow_id: str
    step_id: str
    model_id: str
    model_name: str

    @property
    def sessions_path(self) -> str:
        return f"/api/v1/flows/{self.flow_id}/steps/{self.step_id}/live-transcription-sessions/"


@dataclass(frozen=True)
class LiveStack:
    client: AsyncClient
    headers: dict[str, str]
    flow: LiveFlow
    model_server: FakeRealtimeServer
    base_url: str
    server: uvicorn.Server

    async def open_session(self) -> dict[str, object]:
        response = await self.client.post(self.flow.sessions_path, headers=self.headers)
        assert response.status_code == 201, response.text
        return response.json()

    def socket_url(self, session: Mapping[str, object]) -> str:
        return f"{self.base_url}{session['websocket_path']}"


def _subprotocols(ticket: object) -> list[Subprotocol]:
    return [Subprotocol("eneo-live.v1"), Subprotocol(f"ticket.{ticket}")]


def _provider_endpoint(model_server: FakeRealtimeServer) -> str:
    return model_server.url.replace("ws://", "http://").removesuffix("/realtime")


async def _create_space(client: AsyncClient, headers: Mapping[str, str]) -> str:
    response = await client.post(
        "/api/v1/spaces/", json={"name": f"live-{uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_transcription_model(
    client: AsyncClient,
    headers: Mapping[str, str],
    *,
    endpoint: str,
    supports_realtime: bool,
) -> dict[str, str]:
    provider = await client.post(
        "/api/v1/admin/model-providers/",
        headers=headers,
        json={
            "name": f"vadsa-{uuid4().hex[:8]}",
            "provider_type": "vllm",
            "credentials": {"api_key": PROVIDER_API_KEY},
            "config": {"endpoint": endpoint},
        },
    )
    assert provider.status_code == 200, provider.text
    model_name = f"realtime-asr-{uuid4().hex[:6]}"
    model = await client.post(
        "/api/v1/admin/tenant-models/transcription/",
        headers=headers,
        json={
            "provider_id": provider.json()["id"],
            "name": model_name,
            "display_name": f"Live ASR {uuid4().hex[:8]}",
            "supports_realtime": supports_realtime,
        },
    )
    assert model.status_code == 200, model.text
    return {"id": model.json()["id"], "model_name": model_name}


async def _published_flow(
    client: AsyncClient,
    headers: Mapping[str, str],
    db_container,
    *,
    endpoint: str = UNREACHABLE_ENDPOINT,
    supports_realtime: bool = True,
    audio: bool = True,
    input_required: bool = True,
    wizard: Mapping[str, object] | None = None,
    summarize: bool = False,
) -> LiveFlow:
    space_id = await _create_space(client, headers)
    model = await _create_transcription_model(
        client, headers, endpoint=endpoint, supports_realtime=supports_realtime
    )
    async with db_container() as container:
        container.session().add(
            SpacesTranscriptionModels(
                space_id=UUID(space_id), transcription_model_id=UUID(model["id"])
            )
        )

    created = await client.post(
        "/api/v1/flows/",
        json={"space_id": space_id, "name": f"Live {uuid4().hex[:8]}", "steps": []},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]
    assistant = await client.post(
        f"/api/v1/flows/{flow_id}/assistants/",
        json={"name": f"live-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert assistant.status_code == 201, assistant.text

    step: dict[str, object] = {
        "assistant_id": assistant.json()["id"],
        "step_order": 1,
        "user_description": "Transkribera mötet",
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
    }
    if audio:
        step |= {
            "input_type": "audio",
            "output_mode": "transcribe_only",
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": input_required,
                    "input_format": "audio",
                    "description": "Spela in mötet.",
                }
            },
        }
    steps = [step]
    if summarize:
        steps.append(
            {
                "assistant_id": assistant.json()["id"],
                "step_order": 2,
                "user_description": "Sammanfatta mötet",
                "input_source": "previous_step",
                "input_type": "text",
                "output_mode": "pass_through",
                "output_type": "text",
            }
        )
    updated = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": f"Live {flow_id[:8]}",
            "description": None,
            "steps": steps,
            "metadata_json": {
                "wizard": {
                    "transcription_enabled": audio,
                    "transcription_model": {"id": model["id"]},
                    "transcription_language": "sv",
                    **(wizard or {}),
                }
            },
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    published = await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)
    assert published.status_code == 200, published.text
    return LiveFlow(
        flow_id=flow_id,
        step_id=updated.json()["steps"][0]["id"],
        model_id=model["id"],
        model_name=model["model_name"],
    )


async def _started_audit_extras(db_container, flow_id: str) -> list[dict[str, object]]:
    async with db_container() as container:
        rows = await container.session().scalars(
            sa.select(AuditLogTable.log_metadata).where(
                AuditLogTable.action
                == ActionType.FLOW_LIVE_TRANSCRIPTION_STARTED.value,
                AuditLogTable.entity_id == UUID(flow_id),
            )
        )
        return [metadata["extra"] for metadata in rows]


async def _started_audit_actors(
    db_container, flow_id: str
) -> list[tuple[str, UUID | None]]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(AuditLogTable.actor_type, AuditLogTable.actor_id).where(
                AuditLogTable.action
                == ActionType.FLOW_LIVE_TRANSCRIPTION_STARTED.value,
                AuditLogTable.entity_id == UUID(flow_id),
            )
        )
        return [(str(row.actor_type), row.actor_id) for row in rows]


def _bearer(headers: Mapping[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


@asynccontextmanager
async def _served(app: FastAPI) -> AsyncIterator[tuple[str, uvicorn.Server]]:
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=0, lifespan="off", log_level="warning"
        )
    )
    serving = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if serving.done():
                serving.result()
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}", server
    finally:
        server.should_exit = True
        await serving


@pytest.fixture
async def live_stack(
    client, app, flow_process_auth_headers, db_container
) -> AsyncIterator[LiveStack]:
    headers = dict(flow_process_auth_headers)
    async with (
        fake_realtime_server() as model_server,
        _served(app) as (base_url, server),
    ):
        flow = await _published_flow(
            client, headers, db_container, endpoint=_provider_endpoint(model_server)
        )
        yield LiveStack(client, headers, flow, model_server, base_url, server)


async def test_an_admitted_session_streams_the_preview_through_the_flows_model(
    live_stack: LiveStack, db_container
):
    session = await live_stack.open_session()

    async with connect(
        live_stack.socket_url(session), subprotocols=_subprotocols(session["ticket"])
    ) as socket:
        assert socket.subprotocol == "eneo-live.v1"
        ready = json.loads(await socket.recv())
        await socket.send(TENTH_OF_A_SECOND)
        await socket.send(TENTH_OF_A_SECOND)
        await socket.send(json.dumps({"type": "stop"}))
        events = [json.loads(message) async for message in socket]

    max_seconds = get_settings().flow_audio_max_duration_seconds
    assert session["websocket_path"] == "/api/v1/live-transcription"
    assert session["subprotocol"] == "eneo-live.v1"
    assert session["sample_rate"] == 16000
    assert session["max_seconds"] == max_seconds
    assert session["model"]["id"] == live_stack.flow.model_id
    assert ready == {"type": "ready", "sample_rate": 16000, "max_seconds": max_seconds}
    assert events == [
        {"type": "transcript.delta", "text": "Hej"},
        {"type": "transcript.delta", "text": " världen"},
        {"type": "transcript.done", "text": "Hej världen"},
    ]
    assert live_stack.model_server.received[0] == {
        "type": "session.update",
        "model": live_stack.flow.model_name,
    }
    assert live_stack.model_server.authorization == f"Bearer {PROVIDER_API_KEY}"
    [extra] = await _started_audit_extras(db_container, live_stack.flow.flow_id)
    assert extra["step_id"] == live_stack.flow.step_id
    assert extra["model_id"] == live_stack.flow.model_id


async def test_a_ticket_opens_one_socket_only(live_stack: LiveStack):
    session = await live_stack.open_session()
    url = live_stack.socket_url(session)

    async with connect(url, subprotocols=_subprotocols(session["ticket"])) as socket:
        assert json.loads(await socket.recv())["type"] == "ready"

    with pytest.raises(InvalidStatus) as refused:
        async with connect(url, subprotocols=_subprotocols(session["ticket"])):
            pass
    assert refused.value.response.status_code == 403


async def test_an_expired_ticket_is_refused(
    live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(tickets, "LIVE_TRANSCRIPTION_TICKET_TTL_SECONDS", 1)
    session = await live_stack.open_session()
    assert datetime.fromisoformat(str(session["expires_at"])) <= datetime.now(
        timezone.utc
    ) + timedelta(seconds=1)
    await asyncio.sleep(1.5)

    with pytest.raises(InvalidStatus) as refused:
        async with connect(
            live_stack.socket_url(session),
            subprotocols=_subprotocols(session["ticket"]),
        ):
            pass
    assert refused.value.response.status_code == 403


async def test_a_page_on_an_unlisted_origin_cannot_open_the_socket(
    live_stack: LiveStack,
):
    session = await live_stack.open_session()

    with pytest.raises(InvalidStatus) as refused:
        async with connect(
            live_stack.socket_url(session),
            subprotocols=_subprotocols(session["ticket"]),
            origin=Origin("https://unlisted.example"),
        ):
            pass
    assert refused.value.response.status_code == 403


async def test_a_page_on_the_apis_own_host_opens_the_socket_behind_a_proxy(
    live_stack: LiveStack,
):
    session = await live_stack.open_session()

    async with connect(
        live_stack.socket_url(session),
        subprotocols=_subprotocols(session["ticket"]),
        origin=Origin("https://eneo.example.se"),
        additional_headers={"X-Forwarded-Host": "eneo.example.se"},
    ) as socket:
        assert json.loads(await socket.recv())["type"] == "ready"


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


async def test_a_browser_that_leaves_mid_session_ends_the_socket_cleanly(
    live_stack: LiveStack,
):
    records = _Records()
    uvicorn_errors = logging.getLogger("uvicorn.error")
    uvicorn_errors.addHandler(records)
    try:
        session = await live_stack.open_session()
        async with connect(
            live_stack.socket_url(session),
            subprotocols=_subprotocols(session["ticket"]),
        ) as socket:
            assert json.loads(await socket.recv())["type"] == "ready"
            await socket.send(TENTH_OF_A_SECOND)
        # the browser is gone; wait until the server has finished the connection
        async with asyncio.timeout(5):
            while live_stack.server.server_state.tasks:
                await asyncio.sleep(0.01)
    finally:
        uvicorn_errors.removeHandler(records)

    assert records.messages == []


async def test_realtime_switched_off_after_admission_ends_the_session(
    live_stack: LiveStack,
):
    session = await live_stack.open_session()
    switched_off = await live_stack.client.put(
        f"/api/v1/admin/tenant-models/transcription/{live_stack.flow.model_id}/",
        headers=live_stack.headers,
        json={"supports_realtime": False},
    )
    assert switched_off.status_code == 200, switched_off.text

    async with connect(
        live_stack.socket_url(session), subprotocols=_subprotocols(session["ticket"])
    ) as socket:
        events = [json.loads(message) async for message in socket]

    assert [event["code"] for event in events] == ["model_unavailable"]
    assert live_stack.model_server.received == []


async def test_a_model_without_realtime_support_is_refused_with_its_reason(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, supports_realtime=False)

    response = await client.post(flow.sessions_path, headers=headers)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "flow_live_transcription_unavailable"
    assert response.json()["context"] == {"reason": "model_not_realtime"}
    assert await _started_audit_extras(db_container, flow.flow_id) == []


@pytest.mark.parametrize(("mode", "status"), [("full", 409), ("diarize", 201)])
async def test_live_preview_needs_the_flows_own_model_to_transcribe(
    client, flow_process_auth_headers, db_container, mode: str, status: int
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container)
    original = get_settings()
    set_settings(
        original.model_copy(
            update={
                "flow_transcription_service_url": "http://speaker-service.invalid",
                "flow_transcription_service_api_key": "service-key",
                "flow_transcription_service_mode": mode,
            }
        )
    )
    try:
        response = await client.post(flow.sessions_path, headers=headers)
    finally:
        set_settings(original)

    assert response.status_code == status, response.text
    if status == 409:
        assert response.json()["context"] == {"reason": "transcription_service_mode"}


async def test_a_step_without_audio_is_refused(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, audio=False)

    response = await client.post(flow.sessions_path, headers=headers)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "flow_run_unknown_step_input"


async def test_a_key_for_another_space_is_forbidden_and_nothing_is_audited(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container)
    other_space_id = await _create_space(client, headers)
    key = await client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={
            "name": f"live-key-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "space",
            "scope_id": other_space_id,
            "ownership": "service",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "resource_permissions": {"flows": "write"},
        },
    )
    assert key.status_code == 201, key.text

    response = await client.post(
        flow.sessions_path, headers={"X-API-Key": key.json()["secret"]}
    )

    assert response.status_code == 403, response.text
    assert await _started_audit_extras(db_container, flow.flow_id) == []


async def test_a_module_session_starts_live_transcription_as_the_human(
    live_stack: LiveStack, admin_user, db_container
):
    module_key = await enable_module(db_container, tenant_id=admin_user.tenant_id)
    admin_token = _bearer(live_stack.headers)
    secret = await install_module(
        live_stack.client, admin_token=admin_token, module_key=module_key
    )
    module_token = await module_login(
        live_stack.client,
        service_key=secret,
        user_token=admin_token,
        module_key=module_key,
    )

    response = await live_stack.client.post(
        live_stack.flow.sessions_path,
        headers={"X-API-Key": secret, "Authorization": f"Bearer {module_token}"},
    )

    assert response.status_code == 201, response.text
    # a service key would be audited as an api_key actor without a user
    assert await _started_audit_actors(db_container, live_stack.flow.flow_id) == [
        ("user", admin_user.id)
    ]


async def test_a_module_session_cannot_start_live_transcription_its_human_may_not_run(
    live_stack: LiveStack, admin_user, db_container
):
    module_key = await enable_module(db_container, tenant_id=admin_user.tenant_id)
    secret = await install_module(
        live_stack.client,
        admin_token=_bearer(live_stack.headers),
        module_key=module_key,
    )
    async with db_container() as container:
        outsider = await container.user_repo().add(
            UserAdd(
                email=f"outsider-{uuid4().hex[:8]}@example.com",
                username=f"outsider-{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
            )
        )
        outsider_token = container.auth_service().create_access_token_for_user(outsider)
    module_token = await module_login(
        live_stack.client,
        service_key=secret,
        user_token=outsider_token,
        module_key=module_key,
    )

    response = await live_stack.client.post(
        live_stack.flow.sessions_path,
        headers={"X-API-Key": secret, "Authorization": f"Bearer {module_token}"},
    )

    # the tenant-wide key alone could run this flow; the human in the session cannot
    assert response.status_code == 403, response.text
    assert await _started_audit_actors(db_container, live_stack.flow.flow_id) == []


async def test_an_unexpected_failure_still_ends_the_session_with_an_error(
    live_stack: LiveStack, monkeypatch: pytest.MonkeyPatch
):
    async def broken(_grant):
        raise RuntimeError("database went away")

    monkeypatch.setattr(
        flow_live_transcription_socket_router, "_load_upstream_target", broken
    )
    session = await live_stack.open_session()

    async with connect(
        live_stack.socket_url(session), subprotocols=_subprotocols(session["ticket"])
    ) as socket:
        events = [json.loads(message) async for message in socket]
        close_code = socket.close_code

    assert [event["code"] for event in events] == ["internal_error"]
    assert close_code == 1000
