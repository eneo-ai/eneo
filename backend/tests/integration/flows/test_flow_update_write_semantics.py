"""What each way of writing a draft Flow does with the values it does not state.

A create through the authoring command (a flow package install) gives an
omitted column its default. A manual update (`PATCH /api/v1/flows/{id}/`)
replaces the steps it sends and keeps what it omits at the flow level. Each
case writes against a real database and reads the rows back with plain SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.flow_tables import Flows
from eneo.database.tables.transcription_services_table import (
    SpacesTranscriptionServiceConnections,
    TranscriptionServiceConnections,
)
from eneo.flows.application import flow_authoring_operations
from eneo.flows.application.flow_authoring_command import (
    CreateFlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.main.models import ModelId
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate
from tests.integration.flows.flow_seed_support import (
    ROW_COLUMNS,
    Row,
    set_step_columns,
    step_rows,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass
class Saved:
    space_id: UUID
    flow_id: UUID
    revision: int
    headers: dict[str, str]


async def _space(client, db_container, admin_user) -> tuple[UUID, dict[str, str]]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"write-semantics-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.SHARED_SPACES,
                    Permission.FLOWS_MANAGE,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"write-semantics-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"]), headers


async def _flow(
    db_container,
    space_id: UUID,
    headers: dict[str, str],
    steps: list[dict[str, Any]],
    *,
    metadata_json: dict[str, Any] | None = None,
) -> Saved:
    """A flow saved through the flow service, so every row passed validation."""

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name="Skrivregler",
            description="Läser, bedömer, skriver.",
            metadata_json=metadata_json,
        )
        rows: list[FlowStep] = []
        for order, columns in enumerate(steps, start=1):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg{order}"
            )
            rows.append(
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    **columns,
                )
            )
        flow = await service.update_flow(flow_id=flow.id, steps=rows)
    return Saved(space_id, flow.id, flow.draft_revision, headers)


# Step 2 holds a value in every nullable column. It reads step 1's structured
# answer, so its input contract is the exact projection of that read.
_ANSWER = {
    "type": "object",
    "properties": {"svar": {"type": "string"}},
    "required": ["svar"],
}
_READ_ANSWER = {
    "type": "object",
    "properties": {"svar": {"type": "string"}},
    "additionalProperties": False,
    "required": ["svar"],
}


def _reads_answer(label: str | None = None) -> dict[str, Any]:
    ref: dict[str, Any] = {"step_ref": "step_1", "output": "structured"}
    ref["field_path"] = "svar"
    if label is not None:
        ref["label"] = label
    return {"source_refs": [ref]}


_SAVED_TWO: dict[str, Any] = {
    "input_bindings": _reads_answer(),
    "input_contract": _READ_ANSWER,
    "output_contract": _ANSWER,
    "input_config": {"retrieval": {"top_k": 3}},
    "output_config": {"citation_mode": "off"},
    "review_policy": {"mode": "view", "expires_after_seconds": 3600},
}
_NULLABLE = (
    "input_bindings",
    "input_contract",
    "output_contract",
    "input_config",
    "output_config",
    "review_policy",
)


@pytest.fixture
async def typed(client, db_container, admin_user, patch_auth_service_jwt) -> Saved:
    space_id, headers = await _space(client, db_container, admin_user)
    return await _flow(
        db_container,
        space_id,
        headers,
        [
            {
                "input_source": "flow_input",
                "input_type": "text",
                "output_mode": "pass_through",
                "output_type": "json",
                "output_contract": _ANSWER,
            },
            {
                "input_source": "previous_step",
                "input_type": "json",
                "output_mode": "pass_through",
                "output_type": "json",
                **_SAVED_TWO,
            },
            {
                "input_source": "previous_step",
                "input_type": "text",
                "output_mode": "pass_through",
                "output_type": "text",
                "input_bindings": {"question": "Gör uppgiften."},
            },
        ],
    )


def _origin() -> FlowPackageAuthoringOrigin:
    return FlowPackageAuthoringOrigin(
        package_id="paket", package_version="1", content_checksum="0" * 64
    )


def _differing(before: Row, after: Row) -> set[str]:
    return {column for column in ROW_COLUMNS if before[column] != after[column]}


# A full replace gives every column it omits its default.


def _new_step_spec(ref: str, **columns: Any) -> StepSpec:
    columns.setdefault("input_source", InputSource.FLOW_INPUT)
    return StepSpec(
        plan_step_ref=ref,
        name=f"Steg {ref}",
        assistant_spec=AssistantSpec(instructions="Gör uppgiften."),
        **columns,
    )


async def test_a_create_persists_the_default_of_every_column_it_omits(
    client, db_container, admin_user, patch_auth_service_jwt
) -> None:
    space_id, _ = await _space(client, db_container, admin_user)
    spec = FlowDraftSpecCore(
        flow_name="Ny",
        flow_description="",
        steps=[
            _new_step_spec("a"),
            _new_step_spec("b", input_source=InputSource.PREVIOUS_STEP),
        ],
    )
    command_origin = _origin()
    command = CreateFlowAuthoringCommand(
        space_id=space_id, spec=spec, origin=command_origin
    )
    async with db_container() as container:
        result = await FlowAuthoringCommandService().apply(
            command=command,
            flow_service=container.flow_service(),
        )

    rows = await step_rows(db_container, result.flow_id)
    for row in rows:
        assert row["input_type"] == "text"
        assert row["output_mode"] == "pass_through"
        assert row["output_type"] == "text"
        for column in _NULLABLE:
            assert row[column] is None, column
        assert row["timeout_seconds"] is None


async def test_an_audio_flow_a_command_creates_gets_the_default_speaker_service(
    client, db_container, admin_user, patch_auth_service_jwt
) -> None:
    """An installed package goes through the same draft write as the editor,
    so it gets the organisation's default too."""
    space_id, _ = await _space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        service_id = await session.scalar(
            sa.insert(TranscriptionServiceConnections)
            .values(
                tenant_id=admin_user.tenant_id,
                name=f"vemsa-{uuid4().hex[:8]}",
                endpoint_url="https://vemsa.example.se",
                api_key_encrypted="enc:fernet:v1:not-used",
                is_default=True,
            )
            .returning(TranscriptionServiceConnections.id)
        )
        session.add(
            SpacesTranscriptionServiceConnections(
                space_id=space_id, connection_id=service_id
            )
        )
    spec = FlowDraftSpecCore(
        flow_name="Ny",
        flow_description="",
        steps=[
            _new_step_spec(
                "a",
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            )
        ],
    )
    command_origin = _origin()
    async with db_container() as container:
        result = await FlowAuthoringCommandService().apply(
            command=CreateFlowAuthoringCommand(
                space_id=space_id,
                spec=spec,
                origin=command_origin,
                default_transcription_model_id=uuid4(),
            ),
            flow_service=container.flow_service(),
        )

    async with db_container() as container:
        flow = await container.flow_service().get_flow(result.flow_id)
    assert flow.metadata_json is not None
    assert flow.metadata_json["wizard"]["transcription_speaker_service"] == {
        "id": str(service_id)
    }


# The manual API: green before and after the authoring write semantics.


async def _patch(client, saved: Saved, body: dict[str, Any]):
    return await client.patch(
        f"/api/v1/flows/{saved.flow_id}/", json=body, headers=saved.headers
    )


async def _flow_columns(db_container, flow_id: UUID) -> dict[str, Any]:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(Flows.description, Flows.metadata_json).where(
                    Flows.id == flow_id
                )
            )
        ).one()
    return {"description": row.description, "metadata_json": row.metadata_json}


async def _current_revision(db_container, flow_id: UUID) -> int:
    async with db_container() as container:
        return (await container.flow_service().get_flow(flow_id)).draft_revision


def _step_item(row: Row, **changes: Any) -> dict[str, Any]:
    item = {
        "id": str(row["id"]),
        "assistant_id": str(row["assistant_id"]),
        "step_order": row["step_order"],
        "user_description": row["user_description"],
        "input_source": row["input_source"],
        "input_type": row["input_type"],
        "output_mode": row["output_mode"],
        "output_type": row["output_type"],
        "input_bindings": row["input_bindings"],
    }
    return {**item, **changes}


async def test_a_patch_without_steps_keeps_every_step_row_and_cleans_inactive_config(
    client, db_container, typed: Saved
) -> None:
    """The one change a PATCH without `steps` makes to the rows: configuration
    of a mode a step does not run is dropped, as on every save. Everything
    else, ids included, stays."""

    rows = await step_rows(db_container, typed.flow_id)
    await set_step_columns(
        db_container,
        rows[2]["id"],
        output_config={"url": "https://example.test", "body": "x"},
    )
    before = await step_rows(db_container, typed.flow_id)

    response = await _patch(
        client, typed, {"name": "Nytt namn", "expected_revision": typed.revision}
    )
    assert response.status_code == 200, response.text
    after = await step_rows(db_container, typed.flow_id)

    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert after[:2] == before[:2]
    assert after[2]["output_config"] is None
    assert _differing(before[2], after[2]) == {"output_config", "updated_at"}


async def test_a_patch_clears_a_null_description_and_keeps_an_omitted_one(
    client, db_container, typed: Saved
) -> None:
    response = await _patch(
        client, typed, {"name": "Skrivregler", "expected_revision": typed.revision}
    )
    assert response.status_code == 200, response.text
    assert (await _flow_columns(db_container, typed.flow_id))[
        "description"
    ] == "Läser, bedömer, skriver."

    response = await _patch(
        client,
        typed,
        {
            "description": None,
            "expected_revision": await _current_revision(db_container, typed.flow_id),
        },
    )
    assert response.status_code == 200, response.text
    assert (await _flow_columns(db_container, typed.flow_id))["description"] is None


async def test_a_patch_keeps_omitted_metadata_and_clears_null_metadata(
    client, db_container, typed: Saved
) -> None:
    metadata = {"form_schema": {"fields": [{"name": "namn", "type": "text"}]}}
    response = await _patch(
        client,
        typed,
        {"metadata_json": metadata, "expected_revision": typed.revision},
    )
    assert response.status_code == 200, response.text
    response = await _patch(
        client,
        typed,
        {
            "name": "Skrivregler",
            "expected_revision": await _current_revision(db_container, typed.flow_id),
        },
    )
    assert response.status_code == 200, response.text
    assert (await _flow_columns(db_container, typed.flow_id))[
        "metadata_json"
    ] == metadata

    response = await _patch(
        client,
        typed,
        {
            "metadata_json": None,
            "expected_revision": await _current_revision(db_container, typed.flow_id),
        },
    )
    assert response.status_code == 200, response.text
    assert (await _flow_columns(db_container, typed.flow_id))["metadata_json"] is None


async def test_a_patch_replaces_the_step_list_it_sends(
    client, db_container, typed: Saved
) -> None:
    """A saved step left out of `steps` is deleted, the others keep their ids,
    and a column a step item omits is stored as NULL."""

    rows = await step_rows(db_container, typed.flow_id)
    await set_step_columns(db_container, rows[0]["id"], timeout_seconds=30)
    rows = await step_rows(db_container, typed.flow_id)
    first = _step_item(rows[0], output_type="text")
    third = _step_item(rows[2], step_order=2)

    response = await _patch(
        client,
        typed,
        {"steps": [first, third], "expected_revision": typed.revision},
    )
    assert response.status_code == 200, response.text
    after = await step_rows(db_container, typed.flow_id)

    assert [row["id"] for row in after] == [rows[0]["id"], rows[2]["id"]]
    for column in ("output_contract", "review_policy", "timeout_seconds"):
        assert after[0][column] is None, column


async def test_a_patch_on_a_stale_revision_is_refused_and_writes_nothing(
    client, db_container, typed: Saved
) -> None:
    before = await step_rows(db_container, typed.flow_id)

    response = await _patch(
        client,
        typed,
        {"name": "Sent", "description": None, "expected_revision": typed.revision - 1},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "stale_revision"
    assert await step_rows(db_container, typed.flow_id) == before
    assert (await _flow_columns(db_container, typed.flow_id))[
        "description"
    ] == "Läser, bedömer, skriver."


async def test_a_patch_without_a_revision_is_fenced_on_the_revision_it_was_authorized_at(
    client, db_container, typed: Saved, monkeypatch
) -> None:
    """Someone else allows evidence export after this request was authorized
    and before it writes. The request is refused; were it accepted, its audit
    entry would say that it changed the setting."""
    authorize = flow_authoring_operations.require_flow_edit_access

    async def authorize_then_be_overtaken(request, container, *, flow_id: UUID):
        access = await authorize(request, container, flow_id=flow_id)
        async with db_container() as other:
            service = other.flow_service()
            flow = await service.get_flow(flow_id)
            await service.update_flow(
                flow_id=flow_id,
                metadata_json={
                    **(flow.metadata_json or {}),
                    "evidence_policy": {"allow_export": True},
                },
            )
        return access

    monkeypatch.setattr(
        flow_authoring_operations,
        "require_flow_edit_access",
        authorize_then_be_overtaken,
    )

    response = await _patch(client, typed, {"name": "Sent", "description": None})

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "stale_revision"
    columns = await _flow_columns(db_container, typed.flow_id)
    assert columns["metadata_json"]["evidence_policy"] == {"allow_export": True}
    assert columns["description"] == "Läser, bedömer, skriver."


# Reads keep their meaning through a full replacement, renames and form changes.

_KOMMUN_FORM = {"form_schema": {"fields": [{"name": "kommun", "type": "text"}]}}
_READING_STEPS: list[dict[str, Any]] = [
    {
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
    },
    {
        "input_source": "previous_step",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
        "input_bindings": {"question": "Läs {{ step_1.output.text }}."},
    },
    {
        "input_source": "previous_step",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
        "input_bindings": {"question": "Skriv från {{ Steg 2 }}."},
    },
]
_THIRD_PROMPT = "Utgå från {{step_2.output.text}} i {{ flow_input.kommun }}."


@pytest.fixture
async def reading(client, db_container, admin_user, patch_auth_service_jwt) -> Saved:
    """Step 2 reads step 1 by alias; step 3 reads step 2 by name, and its
    prompt reads step 2 by alias and the run form field `kommun`."""

    space_id, headers = await _space(client, db_container, admin_user)
    saved = await _flow(
        db_container, space_id, headers, _READING_STEPS, metadata_json=_KOMMUN_FORM
    )
    rows = await step_rows(db_container, saved.flow_id)
    async with db_container() as container:
        service = container.flow_service()
        _, _, revision = await service.update_flow_assistant(
            flow_id=saved.flow_id,
            assistant_id=rows[2]["assistant_id"],
            update=AssistantUpdateCommand(prompt=PromptCreate(text=_THIRD_PROMPT)),
        )
    saved.revision = revision
    return saved


async def _assistant_prompt(client, saved: Saved, assistant_id: UUID) -> str:
    response = await client.get(
        f"/api/v1/flows/{saved.flow_id}/assistants/{assistant_id}/",
        headers=saved.headers,
    )
    assert response.status_code == 200, response.text
    return (response.json().get("prompt") or {}).get("text") or ""


def _record_audit(monkeypatch: pytest.MonkeyPatch) -> list[ActionType]:
    actions: list[ActionType] = []
    log_async = AuditService.log_async

    async def record(self: AuditService, **kwargs: Any) -> Any:
        actions.append(kwargs["action"])
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return actions


async def test_a_full_replacement_that_inserts_a_step_moves_every_read(
    client, db_container, reading: Saved
) -> None:
    rows = await step_rows(db_container, reading.flow_id)
    new_assistant = await client.post(
        f"/api/v1/flows/{reading.flow_id}/assistants/",
        json={"name": "Hälsa"},
        headers=reading.headers,
    )
    assert new_assistant.status_code == 201, new_assistant.text
    revision = await _current_revision(db_container, reading.flow_id)
    steps = [
        {
            "assistant_id": new_assistant.json()["id"],
            "step_order": 1,
            "user_description": "Hälsa",
            "input_source": "flow_input",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "text",
        },
        _step_item(rows[0], step_order=2, input_source="previous_step"),
        _step_item(rows[1], step_order=3),
        _step_item(rows[2], step_order=4),
    ]

    response = await _patch(
        client, reading, {"steps": steps, "expected_revision": revision}
    )

    assert response.status_code == 200, response.text
    assert response.json()["draft_revision"] == revision + 1
    after = await step_rows(db_container, reading.flow_id)
    assert [row["id"] for row in after[1:]] == [row["id"] for row in rows]
    assert after[2]["input_bindings"] == {"question": "Läs {{ step_2.output.text }}."}
    assert after[3]["input_bindings"] == {"question": "Skriv från {{ Steg 2 }}."}
    assert await _assistant_prompt(client, reading, rows[2]["assistant_id"]) == (
        "Utgå från {{step_3.output.text}} i {{ flow_input.kommun }}."
    )


async def test_a_full_replacement_that_removes_a_read_step_is_refused(
    client, db_container, reading: Saved
) -> None:
    rows = await step_rows(db_container, reading.flow_id)

    response = await _patch(
        client,
        reading,
        {
            "steps": [_step_item(rows[0]), _step_item(rows[2], step_order=2)],
            "expected_revision": reading.revision,
        },
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "flow_step_read_lost_producer"
    assert body["context"]["reason"] == "producer_removed"
    assert body["context"]["step_id"] == str(rows[2]["id"])
    assert await step_rows(db_container, reading.flow_id) == rows
    assert await _current_revision(db_container, reading.flow_id) == reading.revision


async def test_renaming_a_step_in_a_full_replacement_renames_its_reads(
    client, db_container, reading: Saved
) -> None:
    rows = await step_rows(db_container, reading.flow_id)

    response = await _patch(
        client,
        reading,
        {
            "steps": [
                _step_item(rows[0]),
                _step_item(rows[1], user_description="Granska"),
                _step_item(rows[2]),
            ],
            "expected_revision": reading.revision,
        },
    )

    assert response.status_code == 200, response.text
    after = await step_rows(db_container, reading.flow_id)
    assert after[2]["input_bindings"] == {"question": "Skriv från {{ Granska }}."}


async def test_a_renamed_form_field_takes_its_reads_and_a_read_one_cannot_go(
    client, db_container, reading: Saved
) -> None:
    rows = await step_rows(db_container, reading.flow_id)
    renamed_form = {"form_schema": {"fields": [{"name": "ort", "type": "text"}]}}

    renamed = await _patch(
        client,
        reading,
        {
            "metadata_json": renamed_form,
            "form_field_renames": {"kommun": "ort"},
            "expected_revision": reading.revision,
        },
    )

    assert renamed.status_code == 200, renamed.text
    assert await _assistant_prompt(client, reading, rows[2]["assistant_id"]) == (
        "Utgå från {{step_2.output.text}} i {{ flow_input.ort }}."
    )

    removed = await _patch(
        client,
        reading,
        {
            "metadata_json": {"form_schema": {"fields": []}},
            "expected_revision": renamed.json()["draft_revision"],
        },
    )

    assert removed.status_code == 400, removed.text
    body = removed.json()
    assert body["code"] == "flow_form_field_still_read"
    assert body["context"]["fields"] == ["ort"]
    assert body["context"]["readers"] == [
        {
            "field": "ort",
            "step_id": str(rows[2]["id"]),
            "step_order": 3,
            "site": "prompt",
        }
    ]
    assert (await _flow_columns(db_container, reading.flow_id))[
        "metadata_json"
    ] == renamed_form


async def test_a_refused_editor_change_leaves_no_assistant_audit_entry(
    client, db_container, reading: Saved, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await step_rows(db_container, reading.flow_id)
    audited = _record_audit(monkeypatch)

    response = await client.patch(
        f"/api/v1/flows/{reading.flow_id}/editor/",
        json={
            "expected_revision": reading.revision,
            "definition": {},
            "assistants": [
                {
                    "assistant_id": str(rows[0]["assistant_id"]),
                    "changes": {"prompt": {"text": "Ändrad men aldrig sparad."}},
                }
            ],
            # Step 3 reads step 2, which this order leaves out.
            "step_order": [
                {"step_id": str(rows[0]["id"])},
                {"step_id": str(rows[2]["id"])},
            ],
        },
        headers=reading.headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "flow_step_read_lost_producer"
    assert audited == []
    assert await _assistant_prompt(client, reading, rows[0]["assistant_id"]) == ""


async def test_editing_the_assistant_a_step_shares_gives_it_its_own_copy(
    client, db_container, reading: Saved, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await step_rows(db_container, reading.flow_id)
    shared = rows[0]["assistant_id"]
    sharing = await _patch(
        client,
        reading,
        {
            "steps": [
                _step_item(rows[0]),
                _step_item(rows[1], assistant_id=str(shared)),
                _step_item(rows[2]),
            ],
            "expected_revision": reading.revision,
        },
    )
    assert sharing.status_code == 200, sharing.text
    audited = _record_audit(monkeypatch)

    response = await client.patch(
        f"/api/v1/flows/{reading.flow_id}/editor/",
        json={
            "expected_revision": sharing.json()["draft_revision"],
            "definition": {},
            "assistants": [
                {
                    "assistant_id": str(shared),
                    "step_id": str(rows[1]["id"]),
                    "changes": {"prompt": {"text": "Bara för steg 2."}},
                }
            ],
        },
        headers=reading.headers,
    )

    assert response.status_code == 200, response.text
    saved_steps = response.json()["steps"]
    assert saved_steps[0]["assistant_id"] == str(shared)
    copy_id = UUID(saved_steps[1]["assistant_id"])
    assert copy_id != shared
    after = await step_rows(db_container, reading.flow_id)
    assert [row["assistant_id"] for row in after] == [
        shared,
        copy_id,
        rows[2]["assistant_id"],
    ]
    assert await _assistant_prompt(client, reading, shared) == ""
    assert await _assistant_prompt(client, reading, copy_id) == "Bara för steg 2."
    assert audited == [ActionType.ASSISTANT_CREATED, ActionType.FLOW_UPDATED]


async def test_unpublishing_a_flow_that_is_not_published_is_refused_with_a_code(
    client, reading: Saved
) -> None:
    response = await client.post(
        f"/api/v1/flows/{reading.flow_id}/unpublish/", headers=reading.headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "flow_not_published"
