"""A space load builds its visible assistants and only the hidden ones it
names, without changing what a save writes or which API keys get a role.

A save writes the assistants it holds and deletes only the ones the request
removed. The one write that reaches every other assistant of the space is
pre-existing: saving clears ``is_default`` on all of them in one statement
(``SpaceRepository._set_default_assistant``), which also moves their
``updated_at``. No other field of an assistant the load did not build is
written."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceActor, SpaceRole
from eneo.assistants.assistant_factory import AssistantFactory
from eneo.authentication.auth_models import ApiKeyScopeType
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import Flows
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.runtime.transcription import resolve_transcription_model_for_step
from eneo.flows.transcription_config import FlowTranscriptionConfig
from eneo.main.exceptions import BadRequestException
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate
from tests.integration.flows.test_ai_builder_session_api_regressions import (
    _create_default_transcription_model,  # pyright: ignore[reportPrivateUsage]
    _create_proposed_ai_builder_plan,  # pyright: ignore[reportPrivateUsage]
    _create_space_with_planner_model,  # pyright: ignore[reportPrivateUsage]
    bearer_token,  # noqa: F401  (registers the fixture)
)


async def _space(client, db_container, admin_user) -> UUID:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"scoped-space-load-{uuid4().hex[:8]}",
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
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"scoped-space-load-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _flow_assistants(db_container, *, space_id: UUID, count: int) -> list[UUID]:
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space_id, name="Skrivning", description="", steps=[]
        )
        ids = []
        for index in range(count):
            assistant, _ = await flow_service.create_flow_assistant(
                flow_id=flow.id, name=f"steg-{index}"
            )
            ids.append(assistant.id)
    return ids


async def _row(db_container, assistant_id: UUID) -> dict[str, Any] | None:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(Assistants.__table__).where(Assistants.id == assistant_id)
            )
        ).one_or_none()
    return None if row is None else dict(row._mapping)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_space_save_leaves_a_hidden_assistant_it_did_not_load_untouched(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    space_id = await _space(client, db_container, admin_user)
    loaded_id, absent_id = await _flow_assistants(
        db_container, space_id=space_id, count=2
    )
    before = await _row(db_container, absent_id)

    async with db_container() as container:
        space_repo = container.space_repo()
        space = await space_repo.get_space_by_assistant(loaded_id)
        space.assistants = [a for a in space.assistants if a.id != absent_id]
        await space_repo.update(space)

    after = await _row(db_container, absent_id)
    assert before is not None and after is not None
    # Saving a space clears is_default on every other assistant of the space
    # in one statement, which touches updated_at whatever the space loaded.
    assert {**after, "updated_at": None} == {**before, "updated_at": None}


async def _hidden_and_visible(client, db_container, admin_user, *, hidden: int):
    space_id = await _space(client, db_container, admin_user)
    hidden_ids = await _flow_assistants(db_container, space_id=space_id, count=hidden)
    async with db_container() as container:
        visible, _ = await container.assistant_service().create_assistant(
            name="Synlig", space_id=space_id
        )
        default_id = (
            await container.session().scalars(
                sa.select(Assistants.id)
                .where(Assistants.space_id == space_id)
                .where(Assistants.is_default.is_(True))
            )
        ).one()
    return space_id, hidden_ids, visible.id, default_id


def _key_role(space, scope_id: UUID) -> SpaceRole | None:
    key = SimpleNamespace(
        tenant_id=space.tenant_id,
        scope_type="assistant",
        scope_id=scope_id,
        permission="write",
    )
    actor = SpaceActor(
        user=SimpleNamespace(active_api_key=key),  # type: ignore[arg-type]
        space=SpaceAccessFacts.from_space(space),
    )
    return actor._get_api_key_role()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loading_by_a_hidden_assistant_builds_it_and_the_visible_ones_only(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, (target, other), visible, _ = await _hidden_and_visible(
        client, db_container, admin_user, hidden=2
    )

    async with db_container() as container:
        space_repo = container.space_repo()
        by_target = await space_repo.get_space_by_assistant(target)
        with_other = await space_repo.get_space_by_assistant(
            target, hidden_assistant_ids={other}
        )

    assert {a.id for a in by_target.assistants} == {target, visible}
    assert {a.id for a in with_other.assistants} == {target, other, visible}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_assistant_scoped_key_roles_are_those_of_a_load_of_every_hidden_assistant(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, (target, other), visible, _ = await _hidden_and_visible(
        client, db_container, admin_user, hidden=2
    )

    async with db_container() as container:
        space = await container.space_repo().get_space_by_assistant(target)

    assert _key_role(space, target) == SpaceRole.EDITOR
    assert _key_role(space, other) == SpaceRole.EDITOR
    assert _key_role(space, visible) == SpaceRole.EDITOR
    assert _key_role(space, uuid4()) is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loading_by_the_default_assistant_keeps_every_assistant_as_its_tool(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, hidden_ids, visible, default_id = await _hidden_and_visible(
        client, db_container, admin_user, hidden=2
    )

    async with db_container() as container:
        space = await container.space_repo().get_space_by_assistant(default_id)

    assert space.default_assistant is not None
    assert {a.id for a in space.default_assistant.tool_assistants} == {
        *hidden_ids,
        visible,
    }


def _two_step_spec() -> FlowDraftSpecCore:
    def step(ref: str, source: InputSource) -> StepSpec:
        return StepSpec(
            plan_step_ref=ref,
            name=f"Steg {ref}",
            assistant_spec=AssistantSpec(instructions="Gör jobbet."),
            input_source=source,
            input_type=InputType.TEXT,
            output_mode=OutputMode.PASS_THROUGH,
            output_type=OutputType.TEXT,
        )

    return FlowDraftSpecCore(
        flow_name="Två steg",
        flow_description="Skapas ur en plan.",
        steps=[step("a", InputSource.FLOW_INPUT), step("b", InputSource.PREVIOUS_STEP)],
    )


async def _retained_hidden_assistants(db_container, *, space_id: UUID, count: int):
    """Hidden assistants a deleted flow with runs keeps in its space."""
    if count == 0:
        return
    async with db_container() as container:
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space_id, name="Raderat flöde", description="", steps=[]
        )
        for index in range(count):
            await flow_service.create_flow_assistant(
                flow_id=flow.id, name=f"kvar-{index}"
            )
        await container.session().execute(
            sa.update(Flows).where(Flows.id == flow.id).values(deleted_at=sa.func.now())
        )


async def _assistants_built_by_create(
    *,
    client,
    bearer_token,  # noqa: F811
    db_container,
    completion_model_factory,
    monkeypatch,
    retained,
) -> int:
    space_id = await _create_space_with_planner_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_name=f"Behållna dolda {retained}",
        planner_model_overrides={"nickname": f"planner-{retained}"},
    )
    await _retained_hidden_assistants(
        db_container, space_id=UUID(space_id), count=retained
    )
    _, _, plan_id, _ = await _create_proposed_ai_builder_plan(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        space_id=space_id,
        spec=_two_step_spec(),
    )
    built = 0
    original = AssistantFactory.create_space_assistant_from_db

    def counting(self, **kwargs):
        nonlocal built
        built += 1
        return original(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(AssistantFactory, "create_space_assistant_from_db", counting)
        response = await client.post(
            f"/api/v1/flows/ai-builder/plans/{plan_id}/create",
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["steps_created"] == 2
    return built


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creating_a_flow_from_a_plan_does_not_build_the_spaces_other_hidden_assistants(
    client,
    bearer_token,  # noqa: F811
    completion_model_factory,
    db_container,
    monkeypatch: pytest.MonkeyPatch,
):
    without = await _assistants_built_by_create(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        monkeypatch=monkeypatch,
        retained=0,
    )
    with_retained = await _assistants_built_by_create(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        monkeypatch=monkeypatch,
        retained=40,
    )

    assert with_retained == without


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runtime_transcription_model_resolves_through_a_hidden_step_assistant(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    space_id, (target, _), _, _ = await _hidden_and_visible(
        client, db_container, admin_user, hidden=2
    )
    model_id = await _create_default_transcription_model(
        db_container=db_container,
        space_id=str(space_id),
        tenant_id=admin_user.tenant_id,
    )

    async with db_container() as container:
        model = await resolve_transcription_model_for_step(
            space_repo=container.space_repo(),
            assistant_id=target,
            config=FlowTranscriptionConfig(
                enabled=True, model_id=model_id, language="sv", diarization=False
            ),
            step_order=1,
        )

    assert model.id == model_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_asking_through_a_hidden_tool_assistant_it_does_not_offer_is_refused_as_before(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, (hidden, _), visible, _ = await _hidden_and_visible(
        client, db_container, admin_user, hidden=2
    )

    async with db_container() as container:
        with pytest.raises(BadRequestException):
            await container.assistant_service().ask(
                question="Hej", assistant_id=visible, tool_assistant_id=hidden
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_loading_by_the_default_assistant_selects_hidden_ones_without_listing_ids(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, hidden_ids, _, default_id = await _hidden_and_visible(
        client, db_container, admin_user, hidden=40
    )
    hidden_filter_params: list[str] = []

    def record(_conn, _cursor, statement, parameters, _context, _executemany):
        if "assistants.hidden" in statement:
            hidden_filter_params.extend(str(value) for value in parameters or ())

    sa.event.listen(Engine, "before_cursor_execute", record)
    try:
        async with db_container() as container:
            space = await container.space_repo().get_space_by_assistant(default_id)
    finally:
        sa.event.remove(Engine, "before_cursor_execute", record)

    assert space.default_assistant is not None
    assert {a.id for a in space.default_assistant.tool_assistants} >= set(hidden_ids)
    assert not {str(id) for id in hidden_ids} & set(hidden_filter_params)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_space_save_keeps_a_concurrent_change_to_an_assistant_it_did_not_load(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    space_id = await _space(client, db_container, admin_user)
    loaded_id, absent_id = await _flow_assistants(
        db_container, space_id=space_id, count=2
    )

    async with db_container() as container:
        space_repo = container.space_repo()
        space = await space_repo.get_space_by_assistant(loaded_id)
        async with db_container() as concurrent:
            await concurrent.session().execute(
                sa.update(Assistants)
                .where(Assistants.id == absent_id)
                .values(name="ändrad under tiden")
            )
        await space_repo.update(space)

    after = await _row(db_container, absent_id)
    assert after is not None and after["name"] == "ändrad under tiden"


async def _invalid_on_build(db_container, assistant_id: UUID) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(completion_model_kwargs={"temperature": "not-a-number"})
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("load", ["by_other_hidden", "by_default"])
async def test_a_credential_scoped_to_a_hidden_assistant_gets_the_role_a_full_load_gives(
    client, db_container, admin_user, patch_auth_service_jwt, load: str
):
    _ = patch_auth_service_jwt
    _, (target, valid, invalid), _, default_id = await _hidden_and_visible(
        client, db_container, admin_user, hidden=3
    )
    await _invalid_on_build(db_container, invalid)

    roles: dict[UUID, SpaceRole | None] = {}
    for scope_id in (valid, invalid):
        key = SimpleNamespace(scope_type=ApiKeyScopeType.ASSISTANT, scope_id=scope_id)
        caller = admin_user.model_copy(update={"active_api_key": key})
        async with db_container(user=caller) as container:
            space = await container.space_repo().get_space_by_assistant(
                target if load == "by_other_hidden" else default_id
            )
        roles[scope_id] = _key_role(space, scope_id)

    assert roles == {valid: SpaceRole.EDITOR, invalid: None}
