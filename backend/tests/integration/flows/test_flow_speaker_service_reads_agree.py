"""The graph, the run contract and run admission agree on whether the service
a flow chose labels its speakers, however much of the space each reads: the
graph only what that answer needs, the contract the whole space."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from eneo.flows.api import flow_run_lifecycle_router
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.spaces.space_repo import SpaceRepository
from eneo.users.user import UserAdd, UserState
from tests.integration.flows.speaker_service_support import (
    classify_below,
    grant,
    personal_space,
    published_speaker_flow,
    shared_space,
    speaker_service,
    switch_off,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

Change = Callable[..., Awaitable[None]]


async def _unchanged(client, headers, db_container, tenant_id, spaces, service):
    _ = (client, headers, db_container, tenant_id, spaces, service)


async def _revoked(client, headers, db_container, tenant_id, spaces, service):
    _ = (db_container, tenant_id, service)
    _flow_space, granted_space = spaces
    await grant(client, headers, granted_space)


async def _switched_off(client, headers, db_container, tenant_id, spaces, service):
    _ = (db_container, tenant_id, spaces)
    await switch_off(client, headers, service)


async def _classified_below(client, headers, db_container, tenant_id, spaces, service):
    _ = (client, headers)
    flow_space, _granted_space = spaces
    await classify_below(
        db_container, tenant_id=tenant_id, space_id=flow_space, service_id=service
    )


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def skip(*, run_id, tenant_id, expected_revision) -> None:
        _ = (run_id, tenant_id, expected_revision)

    monkeypatch.setattr(
        flow_run_lifecycle_router, "dispatch_flow_run_recoverably_after_commit", skip
    )


def _audio_marker(graph: dict[str, Any]) -> object:
    [audio] = [node for node in graph["nodes"] if node["input_type"] == "audio"]
    return audio["speaker_identification"]


async def _ok(response) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("personal", "change", "identifiable"),
    [
        (False, _unchanged, True),
        (False, _revoked, False),
        (False, _switched_off, False),
        (False, _classified_below, False),
        # A personal space may use every service, granted or not.
        (True, _unchanged, True),
        (True, _revoked, True),
        (True, _switched_off, False),
        (True, _classified_below, False),
    ],
    ids=[
        "shared",
        "shared-revoked",
        "shared-switched-off",
        "shared-classified-below",
        "personal-never-granted",
        "personal-revoked-elsewhere",
        "personal-switched-off",
        "personal-classified-below",
    ],
)
async def test_the_graph_the_contract_and_admission_agree(
    client: AsyncClient,
    db_container,
    admin_user,
    flow_process_auth_headers,
    personal: bool,
    change: Change,
    identifiable: bool,
):
    headers = dict(flow_process_auth_headers)
    service = await speaker_service(client, headers)
    if personal:
        space_id = await personal_space(
            db_container, admin_user.id, admin_user.tenant_id
        )
        # A grant in another space gives a personal space nothing to lose.
        other = await shared_space(client, headers)
        await grant(client, headers, other, service)
        granted = other
    else:
        space_id = granted = await shared_space(client, headers)
        await grant(client, headers, space_id, service)
    flow_id = await published_speaker_flow(
        client, headers, db_container, space_id=space_id, service_id=service
    )
    base = f"/api/v1/flows/{flow_id}"
    # Started while the service labels speakers, so the run asks for labels.
    labelled = await client.post(
        f"{base}/runs/", json={"speaker_labels": True}, headers=headers
    )
    assert labelled.status_code == 201, labelled.text

    await change(
        client,
        headers,
        db_container,
        admin_user.tenant_id,
        (space_id, granted),
        service,
    )

    graph = await _ok(await client.get(f"{base}/graph/", headers=headers))
    run_graph = await _ok(
        await client.get(
            f"{base}/graph/?run_id={labelled.json()['id']}", headers=headers
        )
    )
    contract = await _ok(await client.get(f"{base}/run-contract/", headers=headers))
    admitted = await client.post(
        f"{base}/runs/", json={"speaker_labels": True}, headers=headers
    )

    marker = True if identifiable else None
    assert (_audio_marker(graph), _audio_marker(run_graph)) == (marker, marker)
    speaker_labels = contract["transcription"]["speaker_labels"]
    assert speaker_labels["selectable"] is identifiable
    assert speaker_labels["unavailable_reason"] == (
        None if identifiable else "picked_unavailable"
    )
    if identifiable:
        assert admitted.status_code == 201, admitted.text
    else:
        assert admitted.status_code == 422, admitted.text
        assert admitted.json()["code"] == (
            FlowApiErrorCode.RUN_SPEAKER_LABELS_NOT_SELECTABLE.value
        )


async def test_a_caller_who_may_not_read_the_space_never_reaches_the_speaker_read(
    client: AsyncClient,
    db_container,
    admin_user,
    flow_process_auth_headers,
    monkeypatch: pytest.MonkeyPatch,
):
    headers = dict(flow_process_auth_headers)
    service = await speaker_service(client, headers)
    space_id = await shared_space(client, headers)
    await grant(client, headers, space_id, service)
    flow_id = await published_speaker_flow(
        client, headers, db_container, space_id=space_id, service_id=service
    )
    labelled = await client.post(
        f"/api/v1/flows/{flow_id}/runs/", json={"speaker_labels": True}, headers=headers
    )
    assert labelled.status_code == 201, labelled.text
    suffix = uuid4().hex[:8]
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"Flow viewer {suffix}",
                permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_RUN],
                tenant_id=admin_user.tenant_id,
            )
        )
        stranger = await container.user_repo().add(
            UserAdd(
                email=f"stranger-{suffix}@example.com",
                username=f"stranger_{suffix}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        token = container.auth_service().create_access_token_for_user(stranger)
    reads: list[UUID] = []
    lean_read = SpaceRepository.get_transcription_space

    async def counted(self, space_id: UUID):
        reads.append(space_id)
        return await lean_read(self, space_id)

    monkeypatch.setattr(SpaceRepository, "get_transcription_space", counted)
    stranger_headers = {"Authorization": f"Bearer {token}"}

    refused = [
        await client.get(f"/api/v1/flows/{flow_id}/graph/", headers=stranger_headers),
        await client.get(
            f"/api/v1/flows/{flow_id}/graph/?run_id={labelled.json()['id']}",
            headers=stranger_headers,
        ),
        await client.post(
            f"/api/v1/flows/{flow_id}/runs/",
            json={"speaker_labels": True},
            headers=stranger_headers,
        ),
    ]
    readable = await client.get(f"/api/v1/flows/{flow_id}/graph/", headers=headers)

    assert [response.status_code for response in refused] == [403, 403, 403], [
        response.text for response in refused
    ]
    assert readable.status_code == 200, readable.text
    # Only the reader who may see the space read it.
    assert reads == [UUID(space_id)]
