"""What each way of writing a draft Flow does with the values it does not state.

A sparse edit (the authoring command) writes the step columns it names and
carries every other column from the saved row. A full replace (create) gives an
omitted column its default. A manual update (`PATCH /api/v1/flows/{id}/`)
replaces the steps it sends and keeps what it omits at the flow level. Each
case writes against a real database and reads the rows back with plain SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from eneo.database.tables.flow_tables import Flows
from eneo.flows.ai_builder.ai_builder_authoring_policy import AIBuilderAuthoringPolicy
from eneo.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    CreateFlowAuthoringCommand,
    EditFlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
)
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.json_types import JsonValue
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.settings.encryption_service import EncryptionService
from eneo.users.user import UserUpdate
from tests.integration.flows.test_flow_authoring_edit_step_rows import (
    _KEY,
    _ROW_COLUMNS,
    Row,
    _apply_spec,
    _edit,
    _encryption,
    _keep,
    _kept_spec,
    _rows,
    _saved_flow,
    _set_raw,
)
from tests.integration.flows.test_flow_authoring_edit_step_rows import (
    Saved as _RowsSaved,
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
            steps=[],
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
# A value an edit may write in each column of step 2. The input contract can
# only be the projection of the read, so its written value is the saved one.
_WRITTEN: dict[str, Any] = {
    "user_description": "Granska",
    "input_bindings": _reads_answer("Svaret"),
    "input_contract": _READ_ANSWER,
    "output_contract": {
        "type": "object",
        "properties": {"svar": {"type": "string"}, "motivering": {"type": "string"}},
        "required": ["svar"],
    },
    "input_config": {"retrieval": {"top_k": 5}},
    "output_config": {"citation_mode": "off", "anteckning": "ny"},
    "review_policy": {"mode": "edit", "expires_after_seconds": 7200},
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


def _spec_step(order: int, **columns: Any) -> StepSpec:
    """A saved step as a sparse caller states it: its ref, and only what the
    caller chose to put in each column."""

    columns.setdefault(
        "input_source",
        InputSource.FLOW_INPUT if order == 1 else InputSource.PREVIOUS_STEP,
    )
    return StepSpec(
        plan_step_ref=f"p{order}",
        existing_step_ref=f"existing_step_{order}",
        name=columns.pop("name", f"Steg {order}"),
        assistant_spec=AssistantSpec(instructions="Gör uppgiften."),
        **columns,
    )


def _typed_spec(step_two: StepSpec) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Skrivregler",
        flow_description="Läser, bedömer, skriver.",
        steps=[
            _spec_step(1, output_type=OutputType.JSON),
            step_two,
            _spec_step(3, input_source=InputSource.PREVIOUS_STEP),
        ],
    )


def _origin(spec: FlowDraftSpecCore) -> AIBuilderFlowAuthoringOrigin:
    return AIBuilderFlowAuthoringOrigin(
        session_id=uuid4(),
        plan_id=uuid4(),
        spec_hash=spec.spec_hash(),
        applied_at=datetime.now(timezone.utc),
    )


def _edit_command(
    saved: Saved,
    spec: FlowDraftSpecCore,
    step_fields: dict[str, set[str]],
    assistant_fields: dict[str, set[str]] | None = None,
) -> EditFlowAuthoringCommand:
    """The command a sparse caller sends: the steps it changes, and per step
    the columns and assistant fields it writes."""

    return EditFlowAuthoringCommand.model_validate(
        {
            "space_id": saved.space_id,
            "flow_id": saved.flow_id,
            "expected_revision": saved.revision,
            "spec": spec,
            "removed_existing_step_refs": frozenset(),
            "updated_existing_step_refs": frozenset(
                {*step_fields, *(assistant_fields or {})}
            ),
            "updated_assistant_fields": {
                ref: frozenset(fields)
                for ref, fields in (assistant_fields or {}).items()
            },
            "updated_step_fields": {
                ref: frozenset(fields) for ref, fields in step_fields.items()
            },
            "origin": _origin(spec),
        }
    )


async def _apply(db_container, command: EditFlowAuthoringCommand) -> None:
    async with db_container() as container:
        await FlowAuthoringCommandService().apply(
            command=command,
            flow_service=container.flow_service(),
            origin_policy=AIBuilderAuthoringPolicy(command.origin),  # type: ignore[arg-type]
        )


def _differing(before: Row, after: Row) -> set[str]:
    return {column for column in _ROW_COLUMNS if before[column] != after[column]}


def _step_two(column: str, fill: str) -> StepSpec:
    """Step 2 naming `column` with its written value; every other column holds
    None (`fill="none"`) or a written value of its own (`fill="other"`)."""

    unnamed = (lambda c: _WRITTEN[c]) if fill == "other" else (lambda c: None)
    values = {c: _WRITTEN[c] if c == column else unnamed(c) for c in _NULLABLE}
    name = (
        _WRITTEN["user_description"]
        if column == "user_description" or fill == "other"
        else "Ett annat namn"
    )
    return _spec_step(
        2,
        name=name,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        **values,
    )


@pytest.mark.parametrize("fill", ["none", "other"])
@pytest.mark.parametrize("column", ["user_description", *_NULLABLE])
async def test_a_sparse_edit_writes_only_the_column_it_names(
    db_container, typed: Saved, column: str, fill: str
) -> None:
    before = await _rows(db_container, typed.flow_id)

    await _apply(
        db_container,
        _edit_command(
            typed,
            _typed_spec(_step_two(column, fill)),
            {"existing_step_2": {column}},
        ),
    )
    after = await _rows(db_container, typed.flow_id)

    assert after[0] == before[0] and after[2] == before[2]
    written = column if before[1][column] != _WRITTEN[column] else None
    differing = _differing(before[1], after[1])
    assert differing - {"updated_at"} == ({written} if written else set())
    assert ("updated_at" in differing) == bool(written)
    if written:
        assert after[1][column] == _WRITTEN[column]


# A structured read and its contract stand or fall together, so they are
# cleared together; every other nullable column is cleared alone.
_CLEARS = [
    ("input_bindings", "input_contract"),
    ("output_contract",),
    ("input_config",),
    ("output_config",),
    ("review_policy",),
]


@pytest.mark.parametrize("columns", _CLEARS, ids=["+".join(c) for c in _CLEARS])
async def test_naming_a_nullable_column_with_null_clears_it(
    db_container, typed: Saved, columns: tuple[str, ...]
) -> None:
    """Every other column holds its saved value in the spec, as a caller that
    starts from the saved flow sends it. The output config keeps its mode and
    type, so nothing but the named null can clear it."""

    before = await _rows(db_container, typed.flow_id)
    named = set(columns)
    values = {c: None if c in named else _SAVED_TWO[c] for c in _NULLABLE}
    step_two = _spec_step(
        2,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
        **values,
    )

    await _apply(
        db_container,
        _edit_command(typed, _typed_spec(step_two), {"existing_step_2": named}),
    )
    after = await _rows(db_container, typed.flow_id)

    assert {c: after[1][c] for c in named} == dict.fromkeys(named)
    assert _differing(before[1], after[1]) == named | {"updated_at"}
    assert after[0] == before[0] and after[2] == before[2]


_UPLOAD_OUTPUT = {
    "audio": ("transcribe_only", "text"),
    "document": ("pass_through", "text"),
    "file": ("pass_through", "text"),
}


@pytest.mark.parametrize("input_type", list(_UPLOAD_OUTPUT))
async def test_an_upload_step_named_with_a_null_input_config_is_cleared_through_the_builder_policy(
    client, db_container, admin_user, patch_auth_service_jwt, input_type: str
) -> None:
    """The Builder's origin policy derives an upload configuration for a step
    that takes files. A named null is the author's clear: it stays NULL."""

    space_id, headers = await _space(client, db_container, admin_user)
    output_mode, output_type = _UPLOAD_OUTPUT[input_type]
    saved = await _flow(
        db_container,
        space_id,
        headers,
        [
            {
                "input_source": "flow_input",
                "input_type": input_type,
                "output_mode": output_mode,
                "output_type": output_type,
                "input_config": {
                    "runtime_input": {
                        "enabled": True,
                        "required": True,
                        "input_format": input_type,
                        "description": "Ladda upp underlaget.",
                    }
                },
            },
            {
                "input_source": "previous_step",
                "input_type": "text",
                "output_mode": "pass_through",
                "output_type": "text",
            },
        ],
        metadata_json={
            "wizard": {
                "transcription_enabled": True,
                "transcription_model": {"id": str(uuid4())},
            }
        }
        if input_type == "audio"
        else None,
    )
    before = await _rows(db_container, saved.flow_id)
    spec = FlowDraftSpecCore(
        flow_name="Skrivregler",
        flow_description="Läser, bedömer, skriver.",
        steps=[
            _spec_step(
                1,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType(input_type),
                output_mode=OutputMode(output_mode),
                output_type=OutputType(output_type),
                input_config=None,
            ),
            _spec_step(2, input_source=InputSource.PREVIOUS_STEP),
        ],
    )

    await _apply(
        db_container,
        _edit_command(saved, spec, {"existing_step_1": {"input_config"}}),
    )
    after = await _rows(db_container, saved.flow_id)

    assert after[0]["input_config"] is None
    assert _differing(before[0], after[0]) == {"input_config", "updated_at"}
    assert after[1] == before[1]


async def test_an_edit_naming_only_assistant_fields_writes_no_step_row(
    db_container, typed: Saved
) -> None:
    before = await _rows(db_container, typed.flow_id)
    step_two = _spec_step(
        2,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
    ).model_copy(
        update={"assistant_spec": AssistantSpec(instructions="Bedöm svaret noga.")}
    )

    await _apply(
        db_container,
        _edit_command(
            typed,
            _typed_spec(step_two),
            {},
            assistant_fields={"existing_step_2": {"instructions"}},
        ),
    )

    assert await _rows(db_container, typed.flow_id) == before
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(typed.flow_id)
        snapshots = await service.get_flow_assistant_snapshots(flow)
    assert snapshots[flow.steps[1].assistant_id].instructions == "Bedöm svaret noga."


async def test_a_command_naming_a_column_no_layer_owns_is_refused_before_any_write(
    db_container, typed: Saved
) -> None:
    """`timeout_seconds` is a column of the row, but not one an edit writes:
    no assistant field and no step column, so the command does not exist."""

    before = await _rows(db_container, typed.flow_id)
    step_two = _spec_step(
        2,
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.JSON,
        output_type=OutputType.JSON,
    )

    with pytest.raises(ValidationError, match="updated_step_fields"):
        _edit_command(
            typed, _typed_spec(step_two), {"existing_step_2": {"timeout_seconds"}}
        )

    assert await _rows(db_container, typed.flow_id) == before
    async with db_container() as container:
        flow = await container.flow_service().get_flow(typed.flow_id)
    assert flow.draft_revision == typed.revision


async def test_a_sparse_edit_keeps_a_manual_only_speaker_mapping_step(
    client, db_container, admin_user, patch_auth_service_jwt
) -> None:
    """Speaker mapping is authored by hand; an edit that renames the step
    keeps its configuration and its required review as saved."""

    space_id, headers = await _space(client, db_container, admin_user)
    saved = await _flow(
        db_container,
        space_id,
        headers,
        [
            {
                "input_source": "flow_input",
                "input_type": "text",
                "output_mode": "pass_through",
                "output_type": "text",
            },
            {
                "input_source": "previous_step",
                "input_type": "text",
                "output_mode": "speaker_mapping",
                "output_type": "json",
                "output_config": {"speaker_mapping": {"infer_names": True}},
                "review_policy": {"mode": "edit"},
            },
        ],
    )
    before = await _rows(db_container, saved.flow_id)
    spec = FlowDraftSpecCore(
        flow_name="Skrivregler",
        flow_description="Läser, bedömer, skriver.",
        steps=[
            _spec_step(1),
            _spec_step(
                2,
                name="Talare",
                input_source=InputSource.PREVIOUS_STEP,
                output_mode=OutputMode.SPEAKER_MAPPING,
                output_type=OutputType.JSON,
            ),
        ],
    )

    await _apply(
        db_container,
        _edit_command(saved, spec, {"existing_step_2": {"user_description"}}),
    )
    after = await _rows(db_container, saved.flow_id)

    assert _differing(before[1], after[1]) == {"user_description", "updated_at"}
    assert after[0] == before[0]


@pytest.mark.parametrize(
    "active", [True, False], ids=["encryption on", "encryption off"]
)
async def test_a_sparse_edit_keeps_the_stored_credential_of_the_step_it_names(
    db_container, typed: Saved, active: bool
) -> None:
    """Step 3 delivers its answer over HTTP with a stored token. The edit
    renames it: the token is the stored ciphertext, byte for byte, neither
    encrypted again nor refused as newly typed."""

    with _encryption(True):
        async with db_container() as container:
            service = container.flow_service()
            flow = await service.get_flow(typed.flow_id)
            steps = list(flow.steps)
            steps[2] = steps[2].model_copy(
                update={
                    "output_mode": "http_post",
                    "output_config": {
                        "url": "https://example.test/svar",
                        "auth": {"mode": "bearer_token", "token": "lagrad-hemlighet"},
                        "timeout_seconds": 30,
                    },
                }
            )
            flow = await service.update_flow(
                flow_id=flow.id, steps=steps, expected_revision=flow.draft_revision
            )
    typed.revision = flow.draft_revision
    before = await _rows(db_container, typed.flow_id)
    stored = before[2]["output_config"]["auth"]["token"]
    assert EncryptionService(_KEY).decrypt(stored) == "lagrad-hemlighet"
    spec = _typed_spec(
        _spec_step(
            2,
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.JSON,
            output_type=OutputType.JSON,
        )
    )
    steps = list(spec.steps)
    steps[2] = _spec_step(3, name="Skicka", input_source=InputSource.PREVIOUS_STEP)
    spec = spec.model_copy(update={"steps": steps})

    with _encryption(active):
        await _apply(
            db_container,
            _edit_command(typed, spec, {"existing_step_3": {"user_description"}}),
        )
    after = await _rows(db_container, typed.flow_id)

    assert after[2]["output_config"]["auth"]["token"] == stored
    assert after[2]["output_config"] == before[2]["output_config"]
    assert _differing(before[2], after[2]) == {"user_description", "updated_at"}
    assert after[:2] == before[:2]


@pytest.fixture
async def three_steps(client, db_container, admin_user, patch_auth_service_jwt):
    from tests.integration.flows.test_flow_authoring_edit_step_rows import (
        _space as _rows_space,
    )

    return await _saved_flow(
        db_container, await _rows_space(client, db_container, admin_user)
    )


_LEGACY_FORM = {
    "fields": [
        {"name": "epost", "type": "email", "label": "E-post", "required": True},
        {"name": "namn", "type": "string", "label": "Namn", "order": 2},
        {"name": "beskrivning", "type": "textarea"},
    ]
}


async def _saved_metadata(db_container, flow_id: UUID) -> dict[str, JsonValue] | None:
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(Flows.metadata_json).where(Flows.id == flow_id)
        )


async def test_an_unrelated_edit_keeps_legacy_form_field_types_byte_identical(
    db_container, three_steps: _RowsSaved
) -> None:
    """`email`, `string` and `textarea` are types older writers saved; the
    platform reads them as text. An edit through the whole Builder chain that
    names no form field stores the form exactly as it was saved."""

    async with db_container() as container:
        await container.session().execute(
            sa.update(Flows)
            .where(Flows.id == three_steps.flow_id)
            .values(metadata_json={"form_schema": _LEGACY_FORM})
        )

    await _edit(db_container, three_steps, [_keep(1, name="Läs"), _keep(2), _keep(3)])

    metadata = await _saved_metadata(db_container, three_steps.flow_id)
    assert metadata is not None
    assert metadata["form_schema"] == _LEGACY_FORM


def _form_edit(*fields: FormFieldSpec) -> FlowDraftSpecCore:
    return _kept_spec(1, 2, 3).model_copy(update={"form_fields": list(fields)})


_EPOST = FormFieldSpec(name="epost", type="text", label="E-post", required=True)
_NAMN = FormFieldSpec(name="namn", type="text", label="Namn")
_BESKRIVNING = FormFieldSpec(name="beskrivning", type="text", label="Beskrivning")
_LABELLED_LEGACY_FORM = {
    "fields": [
        {
            "name": "epost",
            "type": "email",
            "label": "E-post",
            "required": True,
            "order": 1,
        },
        {
            "name": "namn",
            "type": "string",
            "label": "Namn",
            "required": False,
            "order": 2,
        },
        {"name": "beskrivning", "type": "textarea", "label": "Beskrivning", "order": 3},
    ]
}


@pytest.mark.parametrize(
    ("edited", "expected"),
    [
        pytest.param(
            [_EPOST.model_copy(update={"label": "Din e-post"}), _NAMN, _BESKRIVNING],
            {"epost": ("email", "Din e-post", True)},
            id="label",
        ),
        pytest.param(
            [_EPOST, _NAMN.model_copy(update={"required": True}), _BESKRIVNING],
            {"namn": ("string", "Namn", True)},
            id="required",
        ),
        pytest.param(
            [_BESKRIVNING, _EPOST, _NAMN],
            {
                "beskrivning": ("textarea", "Beskrivning", False),
                "epost": ("email", "E-post", True),
                "namn": ("string", "Namn", False),
            },
            id="reorder",
        ),
        pytest.param(
            [_EPOST, _NAMN.model_copy(update={"type": "number"}), _BESKRIVNING],
            {"namn": ("number", "Namn", False), "epost": ("email", "E-post", True)},
            id="a real type change writes the new type",
        ),
    ],
)
async def test_an_edit_of_one_form_field_keeps_the_saved_legacy_type_of_every_field_whose_type_it_leaves(
    db_container,
    three_steps: _RowsSaved,
    edited: list[FormFieldSpec],
    expected: dict[str, tuple[str, str, bool]],
) -> None:
    """A label, a requiredness or an order is edited on a form saved with the
    types an older writer gave it: each field whose normalized type is
    unchanged keeps the type it was saved with, and carries the edited value;
    a field whose type is changed is written with the new one."""

    async with db_container() as container:
        await container.session().execute(
            sa.update(Flows)
            .where(Flows.id == three_steps.flow_id)
            .values(metadata_json={"form_schema": _LABELLED_LEGACY_FORM})
        )

    await _apply_spec(
        db_container,
        three_steps,
        _form_edit(*edited),
        removed=frozenset(),
        updated=frozenset(),
    )

    metadata = await _saved_metadata(db_container, three_steps.flow_id)
    assert metadata is not None
    written = {
        field["name"]: (field["type"], field["label"], field.get("required", False))
        for field in metadata["form_schema"]["fields"]
    }
    assert (
        written
        == {
            "epost": ("email", "E-post", True),
            "namn": ("string", "Namn", False),
            "beskrivning": ("textarea", "Beskrivning", False),
        }
        | expected
    )
    assert [f["name"] for f in metadata["form_schema"]["fields"]] == [
        f.name for f in edited
    ]


# A full replace gives every column it omits its default.


def _new_step_spec(ref: str, **columns: Any) -> StepSpec:
    columns.setdefault("input_source", InputSource.FLOW_INPUT)
    return StepSpec(
        plan_step_ref=ref,
        name=f"Steg {ref}",
        assistant_spec=AssistantSpec(instructions="Gör uppgiften."),
        **columns,
    )


@pytest.mark.parametrize("origin", ["package", "builder"])
async def test_a_create_persists_the_default_of_every_column_it_omits(
    client, db_container, admin_user, patch_auth_service_jwt, origin: str
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
    command_origin = (
        _origin(spec)
        if origin == "builder"
        else FlowPackageAuthoringOrigin(
            package_id="paket", package_version="1", content_checksum="0" * 64
        )
    )
    command = CreateFlowAuthoringCommand(
        space_id=space_id, spec=spec, origin=command_origin
    )
    async with db_container() as container:
        result = await FlowAuthoringCommandService().apply(
            command=command,
            flow_service=container.flow_service(),
            origin_policy=AIBuilderAuthoringPolicy(command_origin)
            if isinstance(command_origin, AIBuilderFlowAuthoringOrigin)
            else None,
        )

    rows = await _rows(db_container, result.flow_id)
    for row in rows:
        assert row["input_type"] == "text"
        assert row["output_mode"] == "pass_through"
        assert row["output_type"] == "text"
        for column in _NULLABLE:
            assert row[column] is None, column
        assert row["timeout_seconds"] is None


@pytest.mark.parametrize("input_type", ["audio", "document", "file"])
async def test_a_builder_create_derives_the_upload_configuration_of_a_file_step(
    client, db_container, admin_user, patch_auth_service_jwt, input_type: str
) -> None:
    space_id, _ = await _space(client, db_container, admin_user)
    output_mode, output_type = _UPLOAD_OUTPUT[input_type]
    spec = FlowDraftSpecCore(
        flow_name="Ny",
        flow_description="",
        steps=[
            _new_step_spec(
                "a",
                input_type=InputType(input_type),
                output_mode=OutputMode(output_mode),
                output_type=OutputType(output_type),
            )
        ],
    )
    origin = _origin(spec)
    async with db_container() as container:
        result = await FlowAuthoringCommandService().apply(
            command=CreateFlowAuthoringCommand(
                space_id=space_id,
                spec=spec,
                origin=origin,
                default_transcription_model_id=uuid4()
                if input_type == "audio"
                else None,
            ),
            flow_service=container.flow_service(),
            origin_policy=AIBuilderAuthoringPolicy(origin),
        )

    (row,) = await _rows(db_container, result.flow_id)
    runtime_input = row["input_config"]["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["input_format"] == input_type
    for column in ("input_bindings", "output_contract", "review_policy"):
        assert row[column] is None, column


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

    rows = await _rows(db_container, typed.flow_id)
    await _set_raw(
        db_container,
        rows[2]["id"],
        output_config={"url": "https://example.test", "body": "x"},
    )
    before = await _rows(db_container, typed.flow_id)

    response = await _patch(
        client, typed, {"name": "Nytt namn", "expected_revision": typed.revision}
    )
    assert response.status_code == 200, response.text
    after = await _rows(db_container, typed.flow_id)

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

    rows = await _rows(db_container, typed.flow_id)
    await _set_raw(db_container, rows[0]["id"], timeout_seconds=30)
    rows = await _rows(db_container, typed.flow_id)
    first = _step_item(rows[0], output_type="text")
    third = _step_item(rows[2], step_order=2)

    response = await _patch(
        client,
        typed,
        {"steps": [first, third], "expected_revision": typed.revision},
    )
    assert response.status_code == 200, response.text
    after = await _rows(db_container, typed.flow_id)

    assert [row["id"] for row in after] == [rows[0]["id"], rows[2]["id"]]
    for column in ("output_contract", "review_policy", "timeout_seconds"):
        assert after[0][column] is None, column


async def test_a_patch_on_a_stale_revision_is_refused_and_writes_nothing(
    client, db_container, typed: Saved
) -> None:
    before = await _rows(db_container, typed.flow_id)

    response = await _patch(
        client,
        typed,
        {"name": "Sent", "description": None, "expected_revision": typed.revision - 1},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "stale_revision"
    assert await _rows(db_container, typed.flow_id) == before
    assert (await _flow_columns(db_container, typed.flow_id))[
        "description"
    ] == "Läser, bedömer, skriver."


async def test_a_named_step_whose_producer_moves_keeps_its_credential_beside_the_new_alias(
    db_container, three_steps: _RowsSaved
) -> None:
    """Step 3 delivers over HTTP to a URL that reads step 2. The edit adds a
    step before step 2 and renames step 3: its config is carried with the alias
    renumbered, so it is no longer the stored one, and its token is still the
    stored credential, not encrypted a second time."""

    with _encryption(True) as encryption:
        async with db_container() as container:
            service = container.flow_service()
            flow = await service.get_flow(three_steps.flow_id)
            steps = list(flow.steps)
            steps[2] = steps[2].model_copy(
                update={
                    "output_mode": "http_post",
                    "output_config": {
                        "url": "https://example.test/{{step_2.output.text}}",
                        "auth": {"mode": "bearer_token", "token": "lagrad-hemlighet"},
                        "timeout_seconds": 30,
                    },
                }
            )
            flow = await service.update_flow(
                flow_id=flow.id, steps=steps, expected_revision=flow.draft_revision
            )
        stored = (await _rows(db_container, three_steps.flow_id))[2]["output_config"]
        spec = FlowDraftSpecCore(
            flow_name="Tre steg",
            flow_description="Läser, bedömer, skriver.",
            steps=[
                _spec_step(1),
                _new_step_spec("ny", input_source=InputSource.PREVIOUS_STEP),
                _spec_step(2),
                _spec_step(3, name="Skicka"),
            ],
        )
        await _apply(
            db_container,
            _edit_command(
                Saved(
                    three_steps.space_id, three_steps.flow_id, flow.draft_revision, {}
                ),
                spec,
                {"existing_step_3": {"user_description"}},
            ),
        )
    written = (await _rows(db_container, three_steps.flow_id))[3]["output_config"]

    assert encryption is not None
    assert written["auth"]["token"] == stored["auth"]["token"]
    assert encryption.decrypt(written["auth"]["token"]) == "lagrad-hemlighet"
    assert written["url"] == "https://example.test/{{step_3.output.text}}"
