"""What the run contract says about transcription, and a run's speaker choices.

Before recording, a client reads `transcription` from the run contract: whether
the flow's model can show a live preview, whether the run may turn speaker
labels on or off, and whether it may bound the speaker count. The choices are
sent with the run and stay with it.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient, Response

from eneo.database.tables.flow_tables import FlowRuns, FlowStepResults
from eneo.files.file_content_loader import FileContentLoader
from eneo.flows.api import (
    flow_run_lifecycle_router,
    flow_run_retry_router,
    flow_transcript_regeneration_router,
)
from eneo.flows.api.flow_models import FlowStepUpdateRequest
from eneo.flows.application.flow_transcript_regeneration_service import (
    render_original_segments,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.speaker_labels import build_speaker_inventory
from eneo.flows.domain.transcript_corrections import segments_content_hash
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.object_content.content import ObjectContentUnavailableError
from tests.integration.flows.test_flow_live_transcription_session import (
    _published_flow,
)
from tests.integration.flows.test_flow_transcription_choice import _connection, _grant
from tests.integration.flows.test_transcript_corrections import (
    SEGMENTS,
    _store_segments,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _speaker_service(
    client: AsyncClient, headers: Mapping[str, str], flow_id: str, *, granted: bool
) -> None:
    """Grant the flow's space one speaker service, or revoke its grants."""
    flow = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)
    assert flow.status_code == 200, flow.text
    ids = [await _connection(client, headers)] if granted else []
    await _grant(client, headers, flow.json()["space_id"], *ids)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    runs: list[UUID] = []

    async def record(*, run_id: UUID, tenant_id: UUID, expected_revision: int) -> None:
        runs.append(run_id)

    for router in (
        flow_run_lifecycle_router,
        flow_run_retry_router,
        flow_transcript_regeneration_router,
    ):
        monkeypatch.setattr(
            router, "dispatch_flow_run_recoverably_after_commit", record
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


async def _republish(
    client: AsyncClient,
    headers: Mapping[str, str],
    flow_id: str,
    wizard: Mapping[str, object],
) -> None:
    """Publish a new version of the flow with ``wizard`` merged into its settings."""
    unpublished = await client.post(
        f"/api/v1/flows/{flow_id}/unpublish/", headers=headers
    )
    assert unpublished.status_code == 200, unpublished.text
    flow = await client.get(f"/api/v1/flows/{flow_id}/", headers=headers)
    assert flow.status_code == 200, flow.text
    metadata = flow.json()["metadata_json"]
    updated = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": flow.json()["name"],
            "description": flow.json()["description"],
            "steps": [
                {
                    key: value
                    for key, value in step.items()
                    if key in FlowStepUpdateRequest.model_fields
                }
                for step in flow.json()["steps"]
            ],
            "metadata_json": {
                **metadata,
                "wizard": {**metadata["wizard"], **wizard},
            },
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    published = await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)
    assert published.status_code == 200, published.text


async def test_without_a_service_runs_transcribe_without_speaker_labels(
    client, flow_process_auth_headers, db_container, dispatched
):
    headers = dict(flow_process_auth_headers)
    # The flow's own default asks for labels; no service can give them.
    flow = await _published_flow(client, headers, db_container, input_required=False)

    contract = await _contract(client, headers, flow.flow_id)
    created = await _create_run(client, headers, flow.flow_id, {})

    assert contract["transcription"] == {
        "live": {"available": True, "reason": None},
        "speaker_labels": {"selectable": False, "required": False, "default": False},
        "max_speakers": None,
        "single_recording": True,
    }
    assert created.status_code == 201, created.text
    stored = (await _stored_inputs(db_container, flow.flow_id))[created.json()["id"]]
    assert stored["speaker_labels"] is False


async def test_the_contract_gives_the_reason_the_live_route_refuses_with(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, supports_realtime=False)

    contract = await _contract(client, headers, flow.flow_id)
    refused = await client.post(flow.sessions_path, headers=headers)

    reason = "model_not_realtime"
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

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    contract = await _contract(client, headers, flow.flow_id)

    assert contract["transcription"] == {
        "live": {"available": True, "reason": None},
        "speaker_labels": {"selectable": True, "required": False, "default": False},
        "max_speakers": {
            "form_field": None,
            "participants_field": None,
            "default": None,
        },
        "single_recording": True,
    }


async def test_a_flow_that_transcribes_no_audio_has_no_transcription_options(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, audio=False)

    contract = await _contract(client, headers, flow.flow_id)

    assert contract["transcription"] is None


@pytest.mark.parametrize(
    ("choice", "different_choice"),
    [
        ({"speaker_labels": False}, {"speaker_labels": True}),
        ({"max_speakers": 3}, {"max_speakers": 4}),
        ({"max_speakers": None}, {"max_speakers": 3}),
    ],
)
async def test_a_runs_speaker_choice_is_kept_with_the_run_and_its_idempotency_key(
    client,
    flow_process_auth_headers,
    db_container,
    dispatched: list[UUID],
    choice: dict[str, object],
    different_choice: dict[str, object],
):
    headers = dict(flow_process_auth_headers)
    keyed = {**headers, "Idempotency-Key": "meeting-speaker-choice"}
    flow = await _published_flow(client, headers, db_container, input_required=False)

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    chosen = await _create_run(client, keyed, flow.flow_id, choice)
    repeated = await _create_run(client, keyed, flow.flow_id, choice)
    changed = await _create_run(client, keyed, flow.flow_id, different_choice)
    default = await _create_run(client, headers, flow.flow_id, {"speaker_labels": None})
    run_path = f"/api/v1/flows/{flow.flow_id}/runs/{chosen.json()['id']}/"
    read = await client.get(run_path, headers=headers)
    evidence = await client.get(f"{run_path}evidence/", headers=headers)

    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["input_payload_json"] == {}
    assert (read.status_code, evidence.status_code) == (200, 200), evidence.text
    for run in (read.json(), evidence.json()["run"]):
        assert {key: run[key] for key in ("speaker_labels", "max_speakers")} == {
            "speaker_labels": True,
            "max_speakers": None,
            **choice,
        }
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == chosen.json()["id"]
    assert changed.status_code == 400, changed.text
    assert changed.json()["code"] == "flow_run_idempotency_conflict"
    assert default.status_code == 201, default.text
    stored = await _stored_inputs(db_container, flow.flow_id)
    ((key, value),) = choice.items()
    assert stored[chosen.json()["id"]][key] == value
    assert stored[default.json()["id"]]["speaker_labels"] is True
    assert (default.json()["speaker_labels"], default.json()["max_speakers"]) == (
        True,
        None,
    )
    assert len(dispatched) == 2


async def test_a_speaker_choice_the_contract_does_not_offer_creates_no_run(
    client, flow_process_auth_headers, db_container, dispatched: list[UUID]
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, input_required=False)

    not_selectable = await _create_run(
        client, headers, flow.flow_id, {"speaker_labels": False}
    )
    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
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


async def test_two_services_and_no_pick_leave_the_run_no_speaker_choice(
    client, flow_process_auth_headers, db_container, dispatched: list[UUID]
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, input_required=False)
    read = await client.get(f"/api/v1/flows/{flow.flow_id}/", headers=headers)
    services = [await _connection(client, headers) for _ in range(2)]
    await _grant(client, headers, read.json()["space_id"], *services)

    contract = await _contract(client, headers, flow.flow_id)
    refused = await _create_run(client, headers, flow.flow_id, {"speaker_labels": True})

    assert contract["transcription"]["speaker_labels"]["selectable"] is False
    assert contract["transcription"]["max_speakers"] is None
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "flow_run_speaker_labels_not_selectable"
    assert dispatched == []


@pytest.mark.parametrize(
    ("first_service", "second_service", "body", "speaker_mapping"),
    [
        (False, True, {}, False),
        (False, True, {"input_payload_json": {"antal_talare": 4}}, True),
        (True, False, {}, False),
        (True, False, {"max_speakers": 3}, False),
    ],
)
async def test_replay_keeps_request_identity_across_service_changes(
    client,
    flow_process_auth_headers,
    db_container,
    dispatched,
    first_service,
    second_service,
    body,
    speaker_mapping,
):
    headers = {**flow_process_auth_headers, "Idempotency-Key": "same-recording"}
    flow = await _published_flow(
        client,
        headers,
        db_container,
        input_required=False,
        speaker_mapping=speaker_mapping,
    )
    # Replay identity is the submitted request: a service that appears or goes
    # away between the two calls must not turn the same request into a conflict.
    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=first_service
    )
    original = await _create_run(client, headers, flow.flow_id, body)
    assert original.status_code == 201, original.text
    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=second_service
    )
    replayed = await _create_run(client, headers, flow.flow_id, body)
    assert replayed.status_code == 201, replayed.text
    assert replayed.json()["id"] == original.json()["id"]
    assert len(dispatched) == 1


async def test_required_labels_are_persisted_when_the_wizard_default_is_off(
    client,
    flow_process_auth_headers,
    db_container,
    dispatched,
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client,
        headers,
        db_container,
        input_required=False,
        speaker_mapping=True,
        wizard={"transcription_diarization": False},
    )
    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    created = await _create_run(client, headers, flow.flow_id, {"max_speakers": 3})
    assert created.status_code == 201, created.text
    stored = (await _stored_inputs(db_container, flow.flow_id))[created.json()["id"]]
    assert stored["speaker_labels"] is True
    assert stored["max_speakers"] == 3
    assert created.json()["speaker_labels"] is True


@pytest.mark.parametrize("default", [True, False])
async def test_a_run_keeps_the_flow_default_it_took_after_a_republish(
    client,
    flow_process_auth_headers,
    db_container,
    dispatched: list[UUID],
    default: bool,
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client,
        headers,
        db_container,
        input_required=False,
        wizard={"transcription_diarization": default},
    )

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    created = await _create_run(client, headers, flow.flow_id, {})
    await _republish(
        client, headers, flow.flow_id, {"transcription_diarization": not default}
    )
    later = await _create_run(client, headers, flow.flow_id, {})
    read = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{created.json()['id']}/", headers=headers
    )

    assert (created.status_code, later.status_code) == (201, 201), later.text
    assert read.status_code == 200, read.text
    assert (read.json()["speaker_labels"], later.json()["speaker_labels"]) == (
        default,
        not default,
    )
    stored = await _stored_inputs(db_container, flow.flow_id)
    assert stored[created.json()["id"]]["speaker_labels"] is default


async def test_a_run_started_again_from_its_speaker_options_survives_a_republish(
    client, flow_process_auth_headers, db_container, dispatched: list[UUID]
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, input_required=False)

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    original = await _create_run(client, headers, flow.flow_id, {"max_speakers": 3})
    await _republish(
        client, headers, flow.flow_id, {"transcription_diarization": False}
    )
    contract = await _contract(client, headers, flow.flow_id)
    read = await client.get(
        f"/api/v1/flows/{flow.flow_id}/runs/{original.json()['id']}/",
        headers=headers,
    )
    again = await _create_run(
        client,
        headers,
        flow.flow_id,
        {key: read.json()[key] for key in ("speaker_labels", "max_speakers")},
    )

    assert original.status_code == 201, original.text
    assert contract["transcription"]["speaker_labels"] == {
        "selectable": True,
        "required": False,
        "default": False,
    }
    assert (read.json()["speaker_labels"], read.json()["max_speakers"]) == (True, 3)
    assert again.status_code == 201, again.text
    stored = (await _stored_inputs(db_container, flow.flow_id))[again.json()["id"]]
    assert (stored["speaker_labels"], stored["max_speakers"]) == (True, 3)


async def test_a_flow_that_asks_for_the_count_advertises_its_form_field(
    client, flow_process_auth_headers, db_container
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, speaker_mapping=True)

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    contract = await _contract(client, headers, flow.flow_id)

    assert contract["transcription"]["speaker_labels"] == {
        "selectable": False,
        "required": True,
        "default": True,
    }
    assert contract["transcription"]["max_speakers"] == {
        "form_field": "antal_talare",
        "participants_field": "deltagare",
        "default": None,
    }


@pytest.mark.parametrize(
    ("speaker_mapping", "body", "stored_bound"),
    [
        (False, {"max_speakers": 3}, 3),
        (False, {}, None),
        (False, {"max_speakers": None}, None),
        (True, {"input_payload_json": {"antal_talare": 4}}, 4),
        (True, {"input_payload_json": {"antal_talare": 4}, "max_speakers": 2}, 2),
        (True, {"input_payload_json": {"antal_talare": 4}, "max_speakers": None}, None),
        (True, {"input_payload_json": {"deltagare": ["Anna", "Bo", "Cid"]}}, None),
    ],
)
async def test_a_runs_speaker_count_is_settled_once_and_kept_with_the_run(
    client,
    flow_process_auth_headers,
    db_container,
    dispatched: list[UUID],
    speaker_mapping: bool,
    body: dict[str, object],
    stored_bound: int | None,
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client,
        headers,
        db_container,
        input_required=False,
        speaker_mapping=speaker_mapping,
    )

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    created = await _create_run(client, headers, flow.flow_id, body)

    assert created.status_code == 201, created.text
    stored = await _stored_inputs(db_container, flow.flow_id)
    assert "max_speakers" in stored[created.json()["id"]]
    assert stored[created.json()["id"]]["max_speakers"] == stored_bound
    assert "max_speakers" not in created.json()["input_payload_json"]


@pytest.mark.parametrize(
    ("service", "speaker_mapping", "body", "status", "code"),
    [
        (False, False, {"max_speakers": 3}, 422, "flow_run_max_speakers_not_available"),
        (
            True,
            False,
            {"speaker_labels": False, "max_speakers": 3},
            422,
            "flow_run_max_speakers_not_available",
        ),
        (True, False, {"max_speakers": True}, 422, "request_validation_error"),
        (True, False, {"max_speakers": 2.5}, 422, "request_validation_error"),
        (True, False, {"max_speakers": 0}, 422, "request_validation_error"),
        (
            True,
            False,
            {"input_payload_json": {"max_speakers": 3}},
            400,
            "flow_run_reserved_input_payload_key",
        ),
        (
            True,
            True,
            {"input_payload_json": {"antal_talare": 2.5}},
            400,
            "flow_input_invalid_number",
        ),
        (
            True,
            True,
            {"input_payload_json": {"antal_talare": 0}},
            400,
            "flow_input_invalid_number",
        ),
    ],
)
async def test_a_speaker_count_the_run_cannot_use_creates_no_run(
    client,
    flow_process_auth_headers,
    db_container,
    dispatched: list[UUID],
    service: bool,
    speaker_mapping: bool,
    body: dict[str, object],
    status: int,
    code: str,
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client,
        headers,
        db_container,
        input_required=False,
        speaker_mapping=speaker_mapping,
    )

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=service
    )
    refused = await _create_run(client, headers, flow.flow_id, body)

    assert refused.status_code == status, refused.text
    assert refused.json()["code"] == code
    assert await _stored_inputs(db_container, flow.flow_id) == {}
    assert dispatched == []


@pytest.mark.parametrize(
    ("choice", "form_count", "replay_service"),
    [
        ({"speaker_labels": False}, None, False),
        ({"max_speakers": 3}, None, False),
        ({"max_speakers": None}, None, False),
        ({"max_speakers": 3}, 0, True),
        ({"max_speakers": None}, 0, True),
    ],
)
async def test_retry_and_regeneration_keep_the_source_speaker_decision(
    client,
    flow_process_auth_headers,
    db_container,
    admin_user,
    dispatched: list[UUID],
    choice: dict[str, object],
    form_count: int | None,
    replay_service: bool,
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client,
        headers,
        db_container,
        input_required=False,
        summarize=True,
        speaker_mapping=form_count is not None,
    )
    body = dict(choice)
    if form_count is not None:
        body["input_payload_json"] = {"antal_talare": form_count}
    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )
    created = [await _create_run(client, headers, flow.flow_id, body) for _ in range(2)]
    failed_id, completed_id = (UUID(run.json()["id"]) for run in created)
    async with db_container() as container:
        session = container.session()
        for run_id in (failed_id, completed_id):
            await _store_segments(
                session=session,
                run_id=run_id,
                step_id=UUID(flow.step_id),
                segments=SEGMENTS,
            )
            await session.execute(
                sa.update(FlowStepResults)
                .where(
                    FlowStepResults.flow_run_id == run_id,
                    FlowStepResults.step_order == 1,
                )
                .values(
                    status="completed",
                    output_payload_json={"text": render_original_segments(SEGMENTS)},
                )
            )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == completed_id)
            .values(status="completed", finished_at=sa.func.now())
        )
        if form_count is not None:
            source_text = render_original_segments(SEGMENTS)
            transcript_attempt = await session.scalar(
                sa.select(FlowStepResults.current_attempt_no).where(
                    FlowStepResults.flow_run_id == completed_id,
                    FlowStepResults.step_order == 1,
                )
            )
            await session.execute(
                sa.update(FlowStepResults)
                .where(
                    FlowStepResults.flow_run_id == completed_id,
                    FlowStepResults.step_order == 2,
                )
                .values(
                    status="completed",
                    output_payload_json={
                        "text": source_text,
                        "structured": {"speakers": []},
                        "speaker_mapping": {
                            "source_step_id": flow.step_id,
                            "source_step_order": 1,
                            "source_attempt_no": transcript_attempt,
                            "participants_field": "deltagare",
                            "participants": [],
                            "infer_names": False,
                            "inventory": build_speaker_inventory(source_text),
                        },
                    },
                )
            )
        await container.flow_run_terminalizer().terminalize_run(
            run_id=failed_id,
            tenant_id=admin_user.tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError(
                code=FlowApiErrorCode.STEP_EXECUTION_FAILED,
                message="The summary failed.",
            ),
        )
        completed_revision = await session.scalar(
            sa.select(FlowRuns.revision).where(FlowRuns.id == completed_id)
        )

    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=replay_service
    )
    retried = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/{failed_id}/retry/",
        headers={**headers, "Idempotency-Key": "retry-speaker-decision"},
    )
    regenerated = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/{completed_id}/steps/{flow.step_id}"
        "/transcript-regenerations/",
        headers={**headers, "Idempotency-Key": "regenerate-speaker-decision"},
        json={
            "expected_run_revision": completed_revision,
            "expected_correction_revision": None,
            "segments_hash": segments_content_hash(SEGMENTS),
        },
    )

    assert (retried.status_code, regenerated.status_code) == (201, 201), (
        retried.text,
        regenerated.text,
    )
    stored = await _stored_inputs(db_container, flow.flow_id)
    ((key, value),) = choice.items()
    source_labels = stored[str(failed_id)]["speaker_labels"]
    for child in (retried.json()["run"], regenerated.json()["run"]):
        assert key in stored[child["id"]]
        assert stored[child["id"]][key] == value
        assert stored[child["id"]]["speaker_labels"] is source_labels


async def test_the_contract_and_the_live_route_read_no_attachment_content(
    client, flow_process_auth_headers, db_container, monkeypatch: pytest.MonkeyPatch
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container)
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": ("policy.txt", b"Intern policy", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    published = await client.get(f"/api/v1/flows/{flow.flow_id}/", headers=headers)
    assert published.status_code == 200, published.text
    draft = await client.post(
        "/api/v1/flows/",
        json={
            "space_id": published.json()["space_id"],
            "name": f"Unrelated {uuid4().hex[:8]}",
            "steps": [],
        },
        headers=headers,
    )
    assert draft.status_code == 201, draft.text
    unrelated = await client.post(
        f"/api/v1/flows/{draft.json()['id']}/assistants/",
        json={"name": f"unrelated-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert unrelated.status_code == 201, unrelated.text
    attached = await client.patch(
        f"/api/v1/flows/{draft.json()['id']}/assistants/{unrelated.json()['id']}/",
        json={"attachments": [{"id": upload.json()["id"]}]},
        headers=headers,
    )
    assert attached.status_code == 200, attached.text
    load_attachment_groups = FileContentLoader.load_attachment_groups

    async def unreadable_attachment_content(self, groups, **kwargs):
        if any(group.files for group in groups):
            raise ObjectContentUnavailableError("Attachment content is unreadable.")
        return await load_attachment_groups(self, groups, **kwargs)

    monkeypatch.setattr(
        FileContentLoader, "load_attachment_groups", unreadable_attachment_content
    )

    contract = await _contract(client, headers, flow.flow_id)
    session = await client.post(flow.sessions_path, headers=headers)

    assert contract["transcription"]["live"] == {"available": True, "reason": None}
    assert session.status_code == 201, session.text


async def test_a_run_without_a_bound_takes_the_flows_default_speaker_count(
    client, flow_process_auth_headers, db_container, dispatched
):
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(
        client,
        headers,
        db_container,
        input_required=False,
        wizard={"transcription_max_speakers": 3},
    )
    await _speaker_service(
        client, flow_process_auth_headers, flow.flow_id, granted=True
    )

    contract = await _contract(client, headers, flow.flow_id)
    defaulted = await _create_run(client, headers, flow.flow_id, {})
    chosen = await _create_run(client, headers, flow.flow_id, {"max_speakers": 5})

    assert defaulted.status_code == 201, defaulted.text
    assert chosen.status_code == 201, chosen.text
    stored = await _stored_inputs(db_container, flow.flow_id)
    assert stored[defaulted.json()["id"]]["max_speakers"] == 3
    assert stored[chosen.json()["id"]]["max_speakers"] == 5
    # Callers learn the bound an empty run takes before they send one.
    assert contract["transcription"]["max_speakers"]["default"] == 3
