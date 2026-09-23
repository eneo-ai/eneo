"""What the run contract says about transcription, and a run's speaker choice.

Before recording, a client reads `transcription` from the run contract: whether
the flow's model can show a live preview, and whether the run may turn speaker
labels on or off. The choice is sent with the run and stays with it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import AsyncClient, Response

from eneo.database.tables.flow_tables import FlowRuns
from eneo.flows.api import flow_run_lifecycle_router
from eneo.main.config import get_settings, set_settings
from tests.integration.flows.test_flow_live_transcription_session import (
    _published_flow,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@contextmanager
def _deployment(*, service_mode: str | None) -> Iterator[None]:
    """Settings with an external transcription service in ``service_mode``, or none."""
    original = get_settings()
    if service_mode is not None:
        set_settings(
            original.model_copy(
                update={
                    "flow_transcription_service_url": "http://speaker-service.invalid",
                    "flow_transcription_service_api_key": "service-key",
                    "flow_transcription_service_mode": service_mode,
                }
            )
        )
    try:
        yield
    finally:
        set_settings(original)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    runs: list[UUID] = []

    async def record(*, run_id: UUID, tenant_id: UUID, expected_revision: int) -> None:
        runs.append(run_id)

    monkeypatch.setattr(
        flow_run_lifecycle_router, "dispatch_flow_run_recoverably_after_commit", record
    )
    return runs


async def _contract(
    client: AsyncClient, headers: Mapping[str, str], flow_id: str
) -> dict[str, object]:
    response = await client.get(
        f"/api/v1/flows/{flow_id}/run-contract/", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_run(
    client: AsyncClient,
    headers: Mapping[str, str],
    flow_id: str,
    body: Mapping[str, object],
) -> Response:
    return await client.post(
        f"/api/v1/flows/{flow_id}/runs/", json=body, headers=headers
    )


async def _stored_inputs(db_container, flow_id: str) -> dict[str, dict[str, object]]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(FlowRuns.id, FlowRuns.input_payload_json).where(
                FlowRuns.flow_id == UUID(flow_id)
            )
        )
        return {str(run_id): payload for run_id, payload in rows}


async def test_without_a_service_the_contract_offers_live_preview_but_no_speaker_choice(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container)

    contract = await _contract(client, headers, flow.flow_id)

    assert contract["transcription"] == {
        "live": {"available": True, "reason": None},
        "speaker_labels": {"selectable": False, "required": False, "default": True},
    }


@pytest.mark.parametrize(
    ("supports_realtime", "service_mode", "reason"),
    [(False, None, "model_not_realtime"), (True, "full", "transcription_service_mode")],
)
async def test_the_contract_gives_the_reason_the_live_route_refuses_with(
    client,
    flow_process_auth_headers,
    db_container,
    supports_realtime: bool,
    service_mode: str | None,
    reason: str,
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client, headers, db_container, supports_realtime=supports_realtime
    )

    with _deployment(service_mode=service_mode):
        contract = await _contract(client, headers, flow.flow_id)
        refused = await client.post(flow.sessions_path, headers=headers)

    assert contract["transcription"]["live"] == {"available": False, "reason": reason}
    assert refused.status_code == 409, refused.text
    assert refused.json()["context"] == {"reason": reason}


async def test_with_a_service_a_run_may_choose_and_the_flow_sets_the_default(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client, headers, db_container, wizard={"transcription_diarization": False}
    )

    with _deployment(service_mode="diarize"):
        contract = await _contract(client, headers, flow.flow_id)

    assert contract["transcription"] == {
        "live": {"available": True, "reason": None},
        "speaker_labels": {"selectable": True, "required": False, "default": False},
    }


async def test_a_flow_that_transcribes_no_audio_has_no_transcription_options(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, audio=False)

    contract = await _contract(client, headers, flow.flow_id)

    assert contract["transcription"] is None


async def test_a_runs_speaker_choice_is_kept_with_the_run_and_its_idempotency_key(
    client, flow_process_auth_headers, db_container, dispatched: list[UUID]
):
    headers = dict(flow_process_auth_headers)
    keyed = {**headers, "Idempotency-Key": "meeting-with-speakers-off"}
    flow = await _published_flow(client, headers, db_container, input_required=False)

    with _deployment(service_mode="diarize"):
        chosen = await _create_run(
            client, keyed, flow.flow_id, {"speaker_labels": False}
        )
        changed = await _create_run(
            client, keyed, flow.flow_id, {"speaker_labels": True}
        )
        default = await _create_run(
            client, headers, flow.flow_id, {"speaker_labels": None}
        )

    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["input_payload_json"] == {}
    assert changed.status_code == 400, changed.text
    assert changed.json()["code"] == "flow_run_idempotency_conflict"
    assert default.status_code == 201, default.text
    stored = await _stored_inputs(db_container, flow.flow_id)
    assert stored[chosen.json()["id"]]["speaker_labels"] is False
    assert "speaker_labels" not in stored[default.json()["id"]]
    assert len(dispatched) == 2


async def test_a_speaker_choice_the_contract_does_not_offer_creates_no_run(
    client, flow_process_auth_headers, db_container, dispatched: list[UUID]
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, input_required=False)

    not_selectable = await _create_run(
        client, headers, flow.flow_id, {"speaker_labels": False}
    )
    with _deployment(service_mode="diarize"):
        smuggled = await _create_run(
            client,
            headers,
            flow.flow_id,
            {"input_payload_json": {"speaker_labels": False}},
        )

    assert not_selectable.status_code == 422, not_selectable.text
    assert not_selectable.json()["code"] == "flow_run_speaker_labels_not_selectable"
    assert smuggled.status_code == 400, smuggled.text
    assert smuggled.json()["code"] == "flow_run_reserved_input_payload_key"
    assert smuggled.json()["context"] == {"keys": ["speaker_labels"]}
    assert await _stored_inputs(db_container, flow.flow_id) == {}
    assert dispatched == []
