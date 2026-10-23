"""The side-effect-free preview evaluates candidate editor state with the save's rule."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from eneo.assistants.assistant import AssistantOrigin
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.flows.api import flow_security_classification_router as router_module
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import (
    FlowAssistantUpdateRequest,
    FlowStepUpdateRequest,
)
from eneo.flows.api.flow_request_body import read_body_within, replay_body
from eneo.flows.api.flow_security_classification_models import (
    FlowSecurityClassificationAssistantCandidate,
    FlowSecurityClassificationPreviewPublic,
    FlowSecurityClassificationPreviewRequest,
)
from eneo.flows.api.flow_security_classification_router import (
    preview_flow_security_classification,
)
from eneo.flows.api.flow_security_classification_router import (
    router as preview_router,
)
from eneo.flows.application.flow_service import CandidateAssistantChange, FlowService
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.enums import FlowInputSource
from eneo.flows.flow_authoring_spec import (
    MAX_FLOW_AUTHORING_REQUEST_BYTES,
    MAX_FLOW_AUTHORING_STEPS,
)
from eneo.main.exceptions import (
    BadRequestException,
    FileTooLargeException,
    UnauthorizedException,
)
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.roles.permissions import Permission
from eneo.server.exception_handlers import add_exception_handlers
from tests.unit.api_key_test_utils import flatten_routes
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _request,
)
from tests.unittests.flows.test_tool_publish_pin import _Facts, _facts

MISMATCH = "flow_step_security_classification_mismatch"
TOOL_WRITE_DOWN = "flow_step_tool_arguments_classification_write_down"


def _classification(level: int):
    return SimpleNamespace(security_level=level)


def _model(level: int):
    return SimpleNamespace(
        id=uuid4(), security_classification=_classification(level), can_access=True
    )


class _Space:
    """The parts of a space the classification rule and the candidate builder read."""

    def __init__(self, *, level: int | None, models, collections=()):
        self.security_classification = (
            _classification(level) if level is not None else None
        )
        self.completion_models = list(models)
        self._collections = {item.id: item for item in collections}

    def get_completion_model(self, model_id: UUID):
        return next(model for model in self.completion_models if model.id == model_id)

    def get_collection(self, collection_id: UUID):
        return self._collections[collection_id]


def _knowledge(level: int):
    return SimpleNamespace(
        id=uuid4(),
        embedding_model=SimpleNamespace(security_classification=_classification(level)),
    )


def _assistant(model, *, prompt: str = ""):
    return SimpleNamespace(
        id=uuid4(),
        completion_model=model,
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        get_prompt_text=lambda: prompt,
    )


def _step(order: int, assistant_id: UUID, **updates) -> FlowStep:
    values = {
        "id": uuid4(),
        "assistant_id": assistant_id,
        "step_order": order,
        "user_description": f"Step {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
    }
    values.update(updates)
    return FlowStep(**values)


class _World:
    """A saved two-step flow.

    By default step 2 reads only its own literal question. With
    ``second_reads_first`` it reads step 1 through the previous-step source, on
    a model that clears step 1's level.
    """

    def __init__(
        self,
        user,
        *,
        second_reads_first: bool = False,
        security_enabled: bool = True,
    ):
        user.tenant.security_enabled = security_enabled
        self.strong_model = _model(3)
        self.weak_model = _model(1)
        self.knowledge = _knowledge(3)
        self.space = _Space(
            level=1,
            models=[self.weak_model, self.strong_model],
            collections=[self.knowledge],
        )
        self.strong = _assistant(self.strong_model)
        self.weak = _assistant(
            self.strong_model if second_reads_first else self.weak_model
        )
        self.first = _step(
            1,
            self.strong.id,
            input_source="flow_input",
            output_classification_override=3,
        )
        self.second = (
            _step(2, self.weak.id, input_source="previous_step")
            if second_reads_first
            else _step(
                2,
                self.weak.id,
                # Its explicit question is its whole input: it reads no step.
                input_source="previous_step",
                input_bindings={"question": "Fast text."},
            )
        )
        now = datetime.now(timezone.utc)
        self.flow = Flow(
            id=uuid4(),
            tenant_id=user.tenant_id,
            space_id=uuid4(),
            name="Draft",
            description=None,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            published_version=None,
            metadata_json=None,
            data_retention_days=None,
            created_at=now,
            updated_at=now,
            steps=[self.first, self.second],
        )
        self.assistants = {self.strong.id: self.strong, self.weak.id: self.weak}
        self.flow_repo = AsyncMock()
        self.flow_repo.get.return_value = self.flow
        self.flow_repo.get_assistant_scope_rows.side_effect = (
            lambda assistant_ids, space_id, tenant_id: [
                SimpleNamespace(
                    id=assistant_id,
                    origin="flow_managed",
                    managing_flow_id=self.flow.id,
                )
                for assistant_id in assistant_ids
                if assistant_id in self.assistants
            ]
        )
        self.space_service = AsyncMock()
        self.space_service.get_space.return_value = self.space
        self.assistant_service = AsyncMock()
        self.assistant_service.get_assistant.side_effect = lambda assistant_id: (
            self.assistants[assistant_id],
            [],
        )
        self.service = FlowService(
            user=user,
            flow_repo=self.flow_repo,
            flow_version_repo=AsyncMock(),
            assistant_service=self.assistant_service,
            space_service=self.space_service,
        )

    def candidate_steps(self, **second_updates) -> list[FlowStep]:
        return [
            self.first,
            self.second.model_copy(update=second_updates),
        ]

    async def preview(self, **kwargs):
        return await self.service.preview_step_security_classification(
            flow_id=self.flow.id, **kwargs
        )


@pytest.fixture
def world(user) -> _World:
    return _World(user)


@pytest.fixture
def reading_world(user) -> _World:
    return _World(user, second_reads_first=True)


@pytest.fixture
def unclassified_world(user) -> _World:
    """The organization has security classifications turned off."""
    return _World(user, security_enabled=False)


def _violation_code(preview, order: int) -> str | None:
    item = next(item for item in preview if item.step_order == order)
    return None if item.violation is None else item.violation.code.value


def _sends_step_1_to_a_tool(
    world: _World, *, server_level: int, server_exists: bool = True
) -> _Facts:
    """Makes step 2 of the saved flow a tool step whose argument sends step 1's
    level-3 output to a tool on a server of ``server_level``."""
    stored = _facts(server={"security_classification": _classification(server_level)})
    assert stored.server is not None and stored.tool is not None
    reader = _Facts(stored if server_exists else replace(stored, server=None))
    world.service.tool_facts_reader = reader
    world.service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    world.flow.steps = world.candidate_steps(
        input_source="tool",
        input_config={
            "tool": {
                "mcp_server_id": str(stored.server.id),
                "tool_id": str(stored.tool.id),
                "arguments": {"case": "{{step_1.output.text}}"},
            }
        },
    )
    return reader


@pytest.mark.asyncio
async def test_preview_save_and_publish_refuse_arguments_above_the_tool_server(
    reading_world,
):
    # Kills the mutants that leave the preview, the save, the change of a
    # step's assistant or the publish without the server's level, ask about
    # another tenant, space, server or tool, let publish ask the chain and pin
    # before the classification has refused (a fifth read), or answer the
    # preview with another level than the server's.
    world = reading_world
    reader = _sends_step_1_to_a_tool(world, server_level=2)
    world.weak.origin = AssistantOrigin.FLOW_MANAGED
    world.weak.managing_flow_id = world.flow.id

    preview = await world.preview()
    with pytest.raises(BadRequestException) as saved:
        await world.service.update_flow(flow_id=world.flow.id, steps=world.flow.steps)
    with pytest.raises(BadRequestException) as assistant_changed:
        await world.service.update_flow_assistant(
            flow_id=world.flow.id,
            assistant_id=world.weak.id,
            update=AssistantUpdateCommand(prompt=PromptCreate(text="Skriv kort.")),
        )
    with pytest.raises(BadRequestException) as published:
        await world.service.publish_flow(flow_id=world.flow.id)

    assert _violation_code(preview, 2) == TOOL_WRITE_DOWN
    public = FlowSecurityClassificationPreviewPublic.from_explanations(preview)
    assert [step.external_source_level for step in public.steps] == [None, 2]
    for refused in (saved, assistant_changed, published):
        assert refused.value.code == TOOL_WRITE_DOWN
        assert refused.value.context == {
            "issue_code": TOOL_WRITE_DOWN,
            "step_order": 2,
            "step_id": str(world.second.id),
            "required_level": 3,
            "current_level": 2,
            "cause": "reads",
            "source_step_orders": [1],
        }
    ids = world.flow.steps[1].input_config["tool"]
    assert reader.asked == 4 * [
        {
            "tenant_id": world.flow.tenant_id,
            "space_id": world.flow.space_id,
            "mcp_server_id": UUID(ids["mcp_server_id"]),
            "tool_id": UUID(ids["tool_id"]),
        }
    ]
    world.flow_repo.update.assert_not_awaited()
    world.assistant_service.update_assistant.assert_not_awaited()
    world.service.flow_version_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_deleted_tool_server_is_refused_by_the_chain_at_publish(reading_world):
    # Kills the mutant that reads a deleted server as an unclassified one: the
    # author would be told about a classification, not that the server is gone.
    # A save asks no chain, so the draft is stored and publish refuses it.
    world = reading_world
    reader = _sends_step_1_to_a_tool(world, server_level=4, server_exists=False)

    preview = await world.preview()
    await world.service.update_flow(flow_id=world.flow.id, steps=world.flow.steps)
    with pytest.raises(BadRequestException) as published:
        await world.service.publish_flow(flow_id=world.flow.id)

    assert _violation_code(preview, 2) is None
    assert preview[1].external_source_level is None
    world.flow_repo.update.assert_awaited_once()
    assert published.value.code == "typed_io_tool_not_allowed"
    assert published.value.context is not None
    assert published.value.context["refusal"] == "server_not_found"
    # The preview's read, the save's, then one for the publish: its
    # classification rule and the chain judge the same read.
    assert len(reader.asked) == 3


@pytest.mark.asyncio
async def test_while_classifications_are_off_the_tool_server_is_not_read(user):
    # Kills the mutant that reads and compares the server's level for a tenant
    # that has classifications turned off.
    world = _World(user, second_reads_first=True, security_enabled=False)
    reader = _sends_step_1_to_a_tool(world, server_level=2)

    preview = await world.preview()

    assert _violation_code(preview, 2) is None
    assert preview[1].external_source_level is None
    assert reader.asked == []


@pytest.mark.asyncio
async def test_preview_without_candidate_state_explains_the_saved_flow(world):
    preview = await world.preview()

    assert [item.step_order for item in preview] == [1, 2]
    assert _violation_code(preview, 2) is None
    assert preview[1].reads == ()
    assert preview[0].effective_output_level == 3


@pytest.mark.asyncio
async def test_preview_evaluates_candidate_steps_the_saved_flow_does_not_have(world):
    saved = await world.preview()
    candidate = await world.preview(
        steps=world.candidate_steps(input_source="previous_step", input_bindings=None)
    )

    assert _violation_code(saved, 2) is None
    assert _violation_code(candidate, 2) == MISMATCH
    assert candidate[1].reads == (1,)
    assert candidate[1].required_model_level == 3
    assert candidate[1].model_level == 1
    assert candidate[1].qualifying_model_ids == (world.strong_model.id,)


@pytest.mark.asyncio
async def test_preview_evaluates_a_candidate_model_change(reading_world):
    world = reading_world
    saved = await world.preview()
    candidate = await world.preview(
        assistant_changes=[
            CandidateAssistantChange(
                assistant_id=world.weak.id,
                update=AssistantUpdateCommand(completion_model_id=world.weak_model.id),
            )
        ]
    )

    assert _violation_code(saved, 2) is None
    assert saved[1].model_level == 3
    assert _violation_code(candidate, 2) == MISMATCH
    assert candidate[1].model_level == 1


@pytest.mark.asyncio
async def test_preview_evaluates_a_candidate_prompt(world):
    saved = await world.preview()
    candidate = await world.preview(
        assistant_changes=[
            CandidateAssistantChange(
                assistant_id=world.weak.id,
                update=AssistantUpdateCommand(
                    prompt=PromptCreate(text="Bakgrund: {{ step_1.output.text }}")
                ),
            )
        ]
    )

    assert saved[1].reads == ()
    assert candidate[1].reads == (1,)
    assert _violation_code(candidate, 2) == MISMATCH


@pytest.mark.asyncio
async def test_preview_evaluates_candidate_knowledge(world):
    saved = await world.preview()
    candidate = await world.preview(
        assistant_changes=[
            CandidateAssistantChange(
                assistant_id=world.weak.id,
                update=AssistantUpdateCommand(groups=[world.knowledge.id]),
            )
        ]
    )

    assert saved[1].knowledge_level is None
    assert candidate[1].knowledge_level == 3
    assert candidate[1].required_model_level == 3
    assert _violation_code(candidate, 2) == MISMATCH


@pytest.mark.asyncio
async def test_preview_writes_nothing(world):
    await world.preview(
        steps=world.candidate_steps(input_source="previous_step", input_bindings=None),
        assistant_changes=[
            CandidateAssistantChange(
                assistant_id=world.weak.id,
                update=AssistantUpdateCommand(
                    completion_model_id=world.strong_model.id,
                    prompt=PromptCreate(text="Skriv kort."),
                ),
            )
        ],
    )

    assert {call[0] for call in world.flow_repo.mock_calls} <= {
        "get",
        "get_assistant_scope_rows",
    }
    assert {call[0] for call in world.assistant_service.mock_calls} <= {"get_assistant"}
    assert {call[0] for call in world.space_service.mock_calls} <= {"get_space"}
    assert world.flow.steps == [world.first, world.second]


@pytest.mark.asyncio
async def test_save_refuses_the_candidate_the_preview_flagged_with_the_same_facts(
    world,
):
    world.service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    candidate = world.candidate_steps(input_source="previous_step", input_bindings=None)
    preview = await world.preview(steps=candidate)
    violation = preview[1].violation
    assert violation is not None

    with pytest.raises(BadRequestException) as exc_info:
        await world.service.update_flow(flow_id=world.flow.id, steps=candidate)

    assert exc_info.value.code == violation.code.value
    assert str(exc_info.value) == violation.message
    context = exc_info.value.context
    assert context is not None
    assert context["required_level"] == violation.required_level
    assert context["current_level"] == violation.current_level
    assert context["cause"] == violation.cause.value
    assert context["qualifying_model_ids"] == [
        str(model_id) for model_id in preview[1].qualifying_model_ids
    ]
    world.flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_refuses_a_step_whose_assistant_the_flow_does_not_own(world):
    stranger = uuid4()
    with pytest.raises(BadRequestException):
        await world.preview(steps=[world.first, _step(2, stranger)])

    world.assistant_service.get_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_refuses_a_change_for_an_assistant_no_step_uses(world):
    with pytest.raises(BadRequestException):
        await world.preview(
            assistant_changes=[
                CandidateAssistantChange(
                    assistant_id=uuid4(),
                    update=AssistantUpdateCommand(completion_model_id=uuid4()),
                )
            ]
        )


def _shared_steps(world: _World) -> list[FlowStep]:
    """Steps 2 and 3 share an assistant whose model clears the level 3 that
    step 1's output carries, and each reads the step before it."""
    return [
        world.first,
        world.second,
        _step(3, world.weak.id, input_source="previous_step"),
    ]


def _weak_model(world: _World, step_id: UUID | None = None) -> CandidateAssistantChange:
    return CandidateAssistantChange(
        assistant_id=world.weak.id,
        step_id=step_id,
        update=AssistantUpdateCommand(completion_model_id=world.weak_model.id),
    )


@pytest.mark.asyncio
async def test_a_change_for_one_step_of_a_shared_assistant_explains_its_own_copy(
    reading_world,
):
    world = reading_world
    steps = _shared_steps(world)

    for_the_step = await world.preview(
        steps=steps, assistant_changes=[_weak_model(world, steps[2].id)]
    )
    for_every_step = await world.preview(
        steps=steps, assistant_changes=[_weak_model(world)]
    )

    assert [_violation_code(for_the_step, order) for order in (2, 3)] == [
        None,
        MISMATCH,
    ]
    assert [item.model_level for item in for_the_step[1:]] == [3, 1]
    assert [_violation_code(for_every_step, order) for order in (2, 3)] == [
        MISMATCH,
        MISMATCH,
    ]
    assert [step.assistant_id for step in steps] == [
        world.strong.id,
        world.weak.id,
        world.weak.id,
    ]


@pytest.mark.asyncio
async def test_a_steps_copy_starts_from_the_shared_assistant_as_the_other_changes_leave_it(
    reading_world,
):
    world = reading_world
    steps = _shared_steps(world)
    shared_knowledge = CandidateAssistantChange(
        assistant_id=world.weak.id,
        update=AssistantUpdateCommand(groups=[world.knowledge.id]),
    )

    preview = await world.preview(
        steps=steps,
        assistant_changes=[_weak_model(world, steps[2].id), shared_knowledge],
    )

    assert [item.knowledge_level for item in preview[1:]] == [3, 3]
    assert [item.model_level for item in preview[1:]] == [3, 1]
    assert [_violation_code(preview, order) for order in (2, 3)] == [None, MISMATCH]


@pytest.mark.asyncio
async def test_a_change_for_the_only_step_of_an_assistant_changes_the_assistant(
    reading_world,
):
    world = reading_world

    for_the_step = await world.preview(
        assistant_changes=[_weak_model(world, world.second.id)]
    )
    for_every_step = await world.preview(assistant_changes=[_weak_model(world)])

    assert for_the_step == for_every_step
    assert _violation_code(for_the_step, 2) == MISMATCH


@pytest.mark.asyncio
async def test_preview_refuses_a_change_for_a_step_that_does_not_use_the_assistant(
    world,
):
    for step_id in (world.first.id, uuid4()):
        with pytest.raises(BadRequestException) as refused:
            await world.preview(assistant_changes=[_weak_model(world, step_id)])
        assert "does not use its assistant" in str(refused.value)


@pytest.mark.asyncio
async def test_a_step_that_shares_an_assistant_does_not_load_it_again(world):
    shared = world.candidate_steps(
        assistant_id=world.strong.id,
        input_source="previous_step",
        input_bindings={"question": "Fast text."},
    )

    await world.preview(steps=shared)
    assert world.assistant_service.get_assistant.await_count == 1

    world.assistant_service.get_assistant.reset_mock()
    world.service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    await world.service.update_flow(flow_id=world.flow.id, steps=shared)
    assert world.assistant_service.get_assistant.await_count == 1


@pytest.mark.asyncio
async def test_while_classifications_are_off_no_level_and_no_refusal(
    unclassified_world,
):
    world = unclassified_world
    candidate = world.candidate_steps(
        input_source="previous_step",
        input_bindings=None,
        output_classification_override=1,
    )

    preview = await world.preview(steps=candidate)
    for item in preview:
        assert item.effective_output_level is None
        assert item.required_model_level is None
        assert item.violation is None

    world.service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    await world.service.update_flow(flow_id=world.flow.id, steps=candidate)
    world.flow_repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_same_candidate_is_refused_while_classifications_are_on(world):
    candidate = world.candidate_steps(
        input_source="previous_step",
        input_bindings=None,
        output_classification_override=1,
    )
    world.service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(BadRequestException):
        await world.service.update_flow(flow_id=world.flow.id, steps=candidate)

    world.flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_preview_by_omission_refuses_a_saved_flow_over_the_limit(world):
    over = [
        _step(
            order,
            world.strong.id,
            input_source="flow_input" if order == 1 else "previous_step",
        )
        for order in range(1, MAX_FLOW_AUTHORING_STEPS + 2)
    ]
    world.flow.steps = over

    with pytest.raises(BadRequestException) as exc_info:
        await world.preview()

    assert exc_info.value.code == "flow_step_limit_exceeded"
    world.assistant_service.get_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_preview_by_omission_accepts_a_saved_flow_at_the_limit(world):
    at_limit = [
        _step(
            order,
            world.strong.id,
            input_source="flow_input" if order == 1 else "previous_step",
        )
        for order in range(1, MAX_FLOW_AUTHORING_STEPS + 1)
    ]
    world.flow.steps = at_limit

    preview = await world.preview()

    assert len(preview) == MAX_FLOW_AUTHORING_STEPS
    assert world.assistant_service.get_assistant.await_count == 1


@pytest.mark.asyncio
async def test_submitted_steps_over_the_limit_are_refused_by_the_service_too(world):
    over = [
        _step(
            order,
            world.strong.id,
            input_source="flow_input" if order == 1 else "previous_step",
        )
        for order in range(1, MAX_FLOW_AUTHORING_STEPS + 2)
    ]

    with pytest.raises(BadRequestException) as exc_info:
        await world.preview(steps=over)

    assert exc_info.value.code == "flow_step_limit_exceeded"


def _preview_client(world, monkeypatch) -> TestClient:
    """The preview route behind the app's real error handlers, on the real service."""
    container = MagicMock()
    container.flow_service.return_value = world.service
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(preview_router)
    for route in flatten_routes(list(app.routes)):
        if not isinstance(route.route, APIRoute):
            continue
        for dependency in route.dependant.dependencies:
            app.dependency_overrides[dependency.call] = lambda: container

    async def _allow(*_args, **_kwargs):
        return None

    monkeypatch.setattr(router_module, "require_flow_assistant_read_access", _allow)
    return TestClient(app)


def _step_payloads(count: int, assistant_id: UUID) -> list[dict[str, object]]:
    return [
        {
            "assistant_id": str(assistant_id),
            "step_order": order,
            "input_source": "flow_input" if order == 1 else "previous_step",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "text",
        }
        for order in range(1, count + 1)
    ]


def test_over_http_a_preview_of_too_many_steps_gets_the_flow_error_not_a_422(
    world, monkeypatch
):
    client = _preview_client(world, monkeypatch)

    response = client.post(
        f"/{world.flow.id}/security-classification/preview",
        json={"steps": _step_payloads(MAX_FLOW_AUTHORING_STEPS + 1, world.strong.id)},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "flow_step_limit_exceeded"
    assert body["context"] == {
        "issue_code": "flow_step_limit_exceeded",
        "step_count": MAX_FLOW_AUTHORING_STEPS + 1,
        "max_steps": MAX_FLOW_AUTHORING_STEPS,
    }
    world.assistant_service.get_assistant.assert_not_awaited()


def test_the_route_refuses_a_huge_step_list_before_converting_any_step(
    world, monkeypatch
):
    converted: list[object] = []
    original = FlowAssembler.to_domain_step_for_update

    def _spy(self, step):
        converted.append(step)
        return original(self, step)

    monkeypatch.setattr(FlowAssembler, "to_domain_step_for_update", _spy)
    client = _preview_client(world, monkeypatch)

    response = client.post(
        f"/{world.flow.id}/security-classification/preview",
        json={"steps": _step_payloads(10_000, world.strong.id)},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "flow_step_limit_exceeded"
    assert body["context"] == {
        "issue_code": "flow_step_limit_exceeded",
        "step_count": 10_000,
        "max_steps": MAX_FLOW_AUTHORING_STEPS,
    }
    assert converted == []
    world.assistant_service.get_assistant.assert_not_awaited()


def _candidates(count: int) -> list[FlowSecurityClassificationAssistantCandidate]:
    return [
        FlowSecurityClassificationAssistantCandidate(
            assistant_id=uuid4(),
            update=FlowAssistantUpdateRequest.model_validate({}),
        )
        for _ in range(count)
    ]


def test_the_assistant_list_is_bounded_by_the_most_steps_a_flow_can_have(
    world, monkeypatch
):
    FlowSecurityClassificationPreviewRequest(
        assistants=_candidates(MAX_FLOW_AUTHORING_STEPS)
    )
    with pytest.raises(ValidationError):
        FlowSecurityClassificationPreviewRequest(
            assistants=_candidates(MAX_FLOW_AUTHORING_STEPS + 1)
        )

    client = _preview_client(world, monkeypatch)
    response = client.post(
        f"/{world.flow.id}/security-classification/preview",
        json={
            "assistants": [
                {"assistant_id": str(uuid4()), "update": {}}
                for _ in range(MAX_FLOW_AUTHORING_STEPS + 1)
            ]
        },
    )
    assert response.status_code == 422


def test_an_over_cap_body_is_refused_before_it_is_parsed(world, monkeypatch):
    converted: list[object] = []
    original = FlowAssembler.to_domain_step_for_update

    def _spy(self, step):
        converted.append(step)
        return original(self, step)

    monkeypatch.setattr(FlowAssembler, "to_domain_step_for_update", _spy)
    client = _preview_client(world, monkeypatch)

    # Not JSON at all: a parser would answer 422, so a 413 means it never ran.
    response = client.post(
        f"/{world.flow.id}/security-classification/preview",
        content=b"x" * (MAX_FLOW_AUTHORING_REQUEST_BYTES + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    body = response.json()
    assert body["code"] == "flow_request_body_too_large"
    assert body["context"] == {"max_bytes": MAX_FLOW_AUTHORING_REQUEST_BYTES}
    assert converted == []
    world.assistant_service.get_assistant.assert_not_awaited()


def _request_with(chunks: list[bytes], *, content_length: int | None = None):
    consumed = {"chunks": 0}

    async def receive():
        if consumed["chunks"] < len(chunks):
            chunk = chunks[consumed["chunks"]]
            consumed["chunks"] += 1
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": consumed["chunks"] < len(chunks),
            }
        return {"type": "http.disconnect"}

    headers = (
        []
        if content_length is None
        else [(b"content-length", str(content_length).encode())]
    )
    request = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": headers}, receive
    )
    return request, consumed


@pytest.mark.asyncio
async def test_a_streamed_body_is_refused_at_the_chunk_that_crosses_the_cap():
    request, consumed = _request_with([b"a" * 10] * 10)

    with pytest.raises(FileTooLargeException) as exc_info:
        await read_body_within(request, 25)

    assert exc_info.value.code == "flow_request_body_too_large"
    assert consumed["chunks"] == 3


@pytest.mark.asyncio
async def test_a_declared_length_over_the_cap_is_refused_without_reading_a_byte():
    request, consumed = _request_with([b"a" * 10], content_length=1_000)

    with pytest.raises(FileTooLargeException):
        await read_body_within(request, 25)

    assert consumed["chunks"] == 0


@pytest.mark.asyncio
async def test_a_body_within_the_cap_is_read_whole():
    request, _ = _request_with([b"ab", b"cd", b"e"])

    assert await read_body_within(request, 5) == b"abcde"

    one_over, _ = _request_with([b"ab", b"cd", b"ef"])
    with pytest.raises(FileTooLargeException):
        await read_body_within(one_over, 5)


@pytest.mark.asyncio
async def test_a_client_that_disconnects_after_the_body_is_still_seen_as_gone():
    request, consumed = _request_with([b"ab", b"cd"])
    body = await read_body_within(request, 10)
    assert consumed["chunks"] == 2

    replayed = replay_body(request, body)

    # The body is delivered once, and read from the client only once.
    assert await replayed.body() == b"abcd"
    assert await replayed.body() == b"abcd"
    assert consumed["chunks"] == 2
    # What the client sends next is not masked by the buffered body.
    assert await replayed.is_disconnected() is True


def test_over_http_a_preview_of_the_largest_flow_is_explained(world, monkeypatch):
    client = _preview_client(world, monkeypatch)

    payload = {"steps": _step_payloads(MAX_FLOW_AUTHORING_STEPS, world.strong.id)}
    assert len(json.dumps(payload)) < MAX_FLOW_AUTHORING_REQUEST_BYTES

    response = client.post(
        f"/{world.flow.id}/security-classification/preview", json=payload
    )

    assert response.status_code == 200
    assert len(response.json()["steps"]) == MAX_FLOW_AUTHORING_STEPS


# --- the route ------------------------------------------------------------


def _route_container(world, *, can_edit: bool = True, permissions=None):
    container = MagicMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = world.flow

    async def _preview(*, flow_id, **kwargs):
        return await world.preview(**kwargs)

    flow_service.preview_step_security_classification.side_effect = _preview
    container.flow_service.return_value = flow_service
    audit_service = AsyncMock()
    container.audit_service.return_value = audit_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS] if permissions is None else permissions,
    )
    _enable_space_access(
        container,
        can_read=True,
        can_edit=can_edit,
        user_permissions=[Permission.FLOWS] if permissions is None else permissions,
    )
    return container, flow_service, audit_service


def _step_request(step: FlowStep, **updates) -> FlowStepUpdateRequest:
    values = {
        "id": str(step.id),
        "assistant_id": str(step.assistant_id),
        "step_order": step.step_order,
        "user_description": step.user_description,
        "input_source": step.input_source.value,
        "input_type": step.input_type.value,
        "output_mode": step.output_mode.value,
        "output_type": step.output_type.value,
        "input_bindings": step.input_bindings,
        "output_classification_override": step.output_classification_override,
    }
    return FlowStepUpdateRequest.model_validate(values | updates)


def _body(
    world, *, step_id: UUID | None = None
) -> FlowSecurityClassificationPreviewRequest:
    return FlowSecurityClassificationPreviewRequest(
        steps=[
            _step_request(world.first),
            _step_request(
                world.second, input_source="previous_step", input_bindings=None
            ),
        ],
        assistants=[
            FlowSecurityClassificationAssistantCandidate(
                assistant_id=world.weak.id,
                step_id=step_id,
                update=FlowAssistantUpdateRequest.model_validate(
                    {"completion_model": {"id": str(world.weak_model.id)}}
                ),
            )
        ],
    )


@pytest.mark.asyncio
async def test_the_route_lets_an_editor_preview_and_records_no_business_event(world):
    container, flow_service, audit_service = _route_container(world)

    response = await preview_flow_security_classification(
        id=world.flow.id,
        request=_request(),
        body=_body(world),
        container=container,
    )

    assert isinstance(response, FlowSecurityClassificationPreviewPublic)
    assert len(response.steps) == 2
    second = response.steps[1]
    assert second.violation is not None
    assert second.violation.code.value == MISMATCH
    assert second.violation.cause.value == "reads"
    assert second.qualifying_model_ids == [world.strong_model.id]
    (call,) = flow_service.preview_step_security_classification.await_args_list
    assert [step.step_order for step in call.kwargs["steps"]] == [1, 2]
    (change,) = call.kwargs["assistant_changes"]
    assert change.assistant_id == world.weak.id
    assert change.step_id is None
    assert isinstance(change.update, AssistantUpdateCommand)
    assert change.update.completion_model_id == world.weak_model.id
    audit_service.log_async.assert_not_awaited()
    flow_service.update_flow.assert_not_awaited()
    flow_service.update_flow_assistant.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_route_hands_the_service_the_step_a_change_is_for(world):
    container, flow_service, _ = _route_container(world)

    await preview_flow_security_classification(
        id=world.flow.id,
        request=_request(),
        body=_body(world, step_id=world.second.id),
        container=container,
    )

    (call,) = flow_service.preview_step_security_classification.await_args_list
    (change,) = call.kwargs["assistant_changes"]
    assert (change.assistant_id, change.step_id) == (world.weak.id, world.second.id)


@pytest.mark.asyncio
async def test_the_route_refuses_a_caller_without_tenant_flow_access_and_writes_nothing(
    world,
):
    container, flow_service, audit_service = _route_container(world, permissions=[])

    with pytest.raises(UnauthorizedException) as exc_info:
        await preview_flow_security_classification(
            id=world.flow.id,
            request=_request(),
            body=_body(world),
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"
    flow_service.preview_step_security_classification.assert_not_awaited()
    flow_service.update_flow.assert_not_awaited()
    audit_service.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_route_refuses_a_member_who_may_only_read_flows_and_writes_nothing(
    world,
):
    # The assistants the result is derived from are editor-only data.
    container, flow_service, audit_service = _route_container(world, can_edit=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await preview_flow_security_classification(
            id=world.flow.id,
            request=_request(),
            body=_body(world),
            container=container,
        )

    assert exc_info.value.code == "insufficient_space_permission"
    flow_service.preview_step_security_classification.assert_not_awaited()
    flow_service.update_flow.assert_not_awaited()
    audit_service.log_async.assert_not_awaited()


def test_two_candidates_for_one_assistant_and_step_are_refused_at_the_request_boundary(
    world,
):
    update = FlowAssistantUpdateRequest.model_validate({"completion_model": None})
    candidate = FlowSecurityClassificationAssistantCandidate(
        assistant_id=world.weak.id, update=update
    )
    for_a_step = FlowSecurityClassificationAssistantCandidate(
        assistant_id=world.weak.id, step_id=world.second.id, update=update
    )

    FlowSecurityClassificationPreviewRequest(assistants=[candidate, for_a_step])
    for twice in (candidate, for_a_step):
        with pytest.raises(ValueError):
            FlowSecurityClassificationPreviewRequest(assistants=[twice, twice])


def test_preview_refuses_a_candidate_step_the_save_refuses(reading_world, monkeypatch):
    # The candidate's tool argument composes text around a reference: the
    # save refuses it before its classification reads the configuration, and
    # the preview gives the same typed refusal instead of explaining it.
    world = reading_world
    _sends_step_1_to_a_tool(world, server_level=3)
    first, second = world.flow.steps
    assert second.input_config is not None
    tool = {
        **second.input_config["tool"],  # type: ignore[dict-item]
        "arguments": {"case": "Fall: {{step_1.output.text}}"},
    }
    candidate = [first, second.model_copy(update={"input_config": {"tool": tool}})]
    client = _preview_client(world, monkeypatch)

    response = client.post(
        f"/{world.flow.id}/security-classification/preview",
        json={
            "steps": [
                {
                    "id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": step.step_order,
                    "user_description": step.user_description,
                    "input_source": FlowInputSource(step.input_source).value,
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "text",
                    "input_config": step.input_config,
                    "output_classification_override": (
                        step.output_classification_override
                    ),
                }
                for step in candidate
            ]
        },
    )

    with pytest.raises(BadRequestException) as saved:
        asyncio.run(world.service.update_flow(flow_id=world.flow.id, steps=candidate))
    assert response.status_code == 400, response.text
    assert saved.value.code == "typed_io_tool_invalid_config"
    assert response.json()["code"] == saved.value.code
