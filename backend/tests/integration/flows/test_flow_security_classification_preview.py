"""The classification preview of a change to one step of a shared assistant
explains that step with its own copy, as the editor's save makes it."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.spaces_table import Spaces, SpacesCompletionModels
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow import FlowStep
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

MISMATCH = "flow_step_security_classification_mismatch"


@dataclass(frozen=True)
class SharedAssistantFlow:
    """A draft whose step 1 gives an output at level 2, read by steps 2 and 3,
    which share an assistant on a level 2 model. A level 1 model is in the
    space too."""

    headers: dict[str, str]
    flow_id: UUID
    shared_assistant_id: UUID
    step_ids: list[UUID]
    weak_model_id: UUID
    draft_revision: int


@pytest.fixture
async def shared(
    client, db_container, admin_user, completion_model_factory, patch_auth_service_jwt
) -> SharedAssistantFlow:
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        tenant_id = admin_user.tenant_id
        low, high = (
            SecurityClassifications(
                tenant_id=tenant_id,
                name=f"niva-{level}-{uuid4().hex[:6]}",
                security_level=level,
            )
            for level in (1, 2)
        )
        session.add_all([low, high])
        await session.flush()
        strong = await completion_model_factory(
            session, f"stark-{uuid4().hex[:6]}", security_classification_id=high.id
        )
        weak = await completion_model_factory(
            session, f"svag-{uuid4().hex[:6]}", security_classification_id=low.id
        )
        session.add_all(
            SpacesCompletionModels(space_id=space_id, completion_model_id=model.id)
            for model in (strong, weak)
        )
        await session.execute(
            sa.update(Spaces)
            .where(Spaces.id == space_id)
            .values(security_classification_id=low.id)
        )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(security_enabled=True)
        )
        strong_id, weak_id = strong.id, weak.id

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name="Delad assistent",
            description=None,
        )
        first, _ = await service.create_flow_assistant(flow_id=flow.id, name="steg1")
        shared_assistant, _ = await service.create_flow_assistant(
            flow_id=flow.id, name="delad"
        )
        for assistant_id in (first.id, shared_assistant.id):
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant_id,
                update=AssistantUpdateCommand(completion_model_id=strong_id),
            )
        saved = await service.update_flow(
            flow_id=flow.id,
            steps=[
                FlowStep.model_validate(
                    {
                        "assistant_id": first.id,
                        "step_order": 1,
                        "user_description": "Sammanfatta",
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_mode": "pass_through",
                        "output_type": "text",
                        "output_classification_override": 2,
                    }
                ),
                *(
                    FlowStep.model_validate(
                        {
                            "assistant_id": shared_assistant.id,
                            "step_order": order,
                            "user_description": name,
                            "input_source": "previous_step",
                            "input_type": "text",
                            "output_mode": "pass_through",
                            "output_type": "text",
                        }
                    )
                    for order, name in ((2, "Bedöm"), (3, "Skriv svar"))
                ),
            ],
        )

    return SharedAssistantFlow(
        headers={"Authorization": f"Bearer {token}"},
        flow_id=flow.id,
        shared_assistant_id=shared_assistant.id,
        step_ids=[step.id for step in sorted(saved.steps, key=lambda s: s.step_order)],
        weak_model_id=weak_id,
        draft_revision=saved.draft_revision,
    )


def _weak_model_change(shared: SharedAssistantFlow, step_id: UUID | None) -> dict:
    change: dict = {"assistant_id": str(shared.shared_assistant_id)}
    if step_id is not None:
        change["step_id"] = str(step_id)
    return change


async def _preview(
    client: AsyncClient, shared: SharedAssistantFlow, step_id: UUID | None
) -> list[dict]:
    response = await client.post(
        f"/api/v1/flows/{shared.flow_id}/security-classification/preview",
        json={
            "assistants": [
                {
                    **_weak_model_change(shared, step_id),
                    "update": {"completion_model": {"id": str(shared.weak_model_id)}},
                }
            ]
        },
        headers=shared.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["steps"]


async def test_the_preview_of_one_steps_change_matches_what_the_save_refuses(
    client: AsyncClient, shared: SharedAssistantFlow
) -> None:
    third = shared.step_ids[2]

    for_the_step = await _preview(client, shared, third)
    for_every_step = await _preview(client, shared, None)
    response = await client.patch(
        f"/api/v1/flows/{shared.flow_id}/editor/",
        json={
            "expected_revision": shared.draft_revision,
            "definition": {},
            "assistants": [
                {
                    **_weak_model_change(shared, third),
                    "changes": {"completion_model": {"id": str(shared.weak_model_id)}},
                }
            ],
        },
        headers=shared.headers,
    )

    violations = [step["violation"] for step in for_the_step]
    assert violations[:2] == [None, None]
    assert violations[2] is not None
    assert [step["model_level"] for step in for_the_step] == [2, 2, 1]
    assert [
        step["violation"] and step["violation"]["code"] for step in for_every_step
    ] == [None, MISMATCH, MISMATCH]

    assert response.status_code == 400, response.text
    refusal = response.json()
    assert refusal["code"] == violations[2]["code"] == MISMATCH
    assert refusal["context"]["step_order"] == for_the_step[2]["step_order"] == 3
    assert refusal["context"]["step_id"] == str(third)
    assert (
        (
            refusal["context"]["required_level"],
            refusal["context"]["current_level"],
        )
        == (violations[2]["required_level"], violations[2]["current_level"])
        == (2, 1)
    )
