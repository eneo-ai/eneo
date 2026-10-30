"""Saved flows with known step rows and assistants, read back by plain SQL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.fernet import Fernet

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge as AssistantIntegrationKnowledgeTable,
)
from eneo.database.tables.assistant_table import (
    Assistants,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.flow_tables import FlowSteps
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import (
    SpacesCompletionModels,
    SpacesEmbeddingModels,
)
from eneo.database.tables.websites_table import Websites
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import FlowStep
from eneo.main.models import ModelId
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.settings.encryption_service import EncryptionService
from eneo.users.user import UserUpdate

# Saved state an authoring spec cannot express, one distinct value per step.
_TIMEOUTS = {1: 30, 2: 90, 3: None}
_CLASSIFICATIONS = {1: 1, 2: 2, 3: None}
# Steps 2 and 3 ask a question that names no other step, so they read no
# classified output.
_OWN_QUESTION = {"question": "Gör uppgiften."}
ROW_COLUMNS = [column.name for column in FlowSteps.__table__.columns]
ENCRYPTION_KEY = Fernet.generate_key().decode()

Row = dict[str, Any]


@dataclass
class Saved:
    space_id: UUID
    flow_id: UUID
    revision: int


async def flow_space(client, db_container, admin_user) -> UUID:
    """A shared space created over HTTP by a person who may manage flows."""

    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"edit-step-rows-{uuid4().hex[:8]}",
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
        json={"name": f"edit-step-rows-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def saved_three_step_flow(db_container, space_id: UUID) -> Saved:
    """Three steps, each with a timeout, an override and a question of its own."""

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name="Tre steg",
            description="Läser, bedömer, skriver.",
        )
        steps: list[FlowStep] = []
        for order in (1, 2, 3):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg{order}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(
                    prompt=PromptCreate(text=f"Gör uppgift {order}.")
                ),
            )
            steps.append(
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    input_source="flow_input" if order == 1 else "previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                    timeout_seconds=_TIMEOUTS[order],
                    output_classification_override=_CLASSIFICATIONS[order],
                    input_bindings=None if order == 1 else _OWN_QUESTION,
                )
            )
        flow = await service.update_flow(flow_id=flow.id, steps=steps)
    return Saved(space_id, flow.id, flow.draft_revision)


async def step_rows(db_container, flow_id: UUID) -> list[Row]:
    """Every column of every step row of the flow, in step order, by plain SQL."""

    async with db_container() as container:
        result = await container.session().execute(
            sa.select(FlowSteps.__table__)
            .where(FlowSteps.flow_id == flow_id)
            .order_by(FlowSteps.step_order)
        )
        return [dict(row._mapping) for row in result]  # pyright: ignore[reportPrivateUsage]


async def set_step_columns(db_container, step_id: UUID, **columns: Any) -> None:
    """Write step columns as an older writer did, past the flow service."""

    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowSteps).where(FlowSteps.id == step_id).values(**columns)
        )


@contextmanager
def flow_service_encryption(active: bool) -> Iterator[EncryptionService | None]:
    """The flow service writes with this encryption for the duration."""

    encryption = EncryptionService(ENCRYPTION_KEY) if active else None
    original = FlowService.update_flow

    async def with_encryption(self: FlowService, **kwargs: Any) -> Any:
        self.encryption_service = encryption
        return await original(self, **kwargs)

    with patch.object(FlowService, "update_flow", with_encryption):
        yield encryption


_PROMPTS = {
    1: "Gör uppgift 1.",
    2: "Gör uppgift 2.",
    3: "Sammanfatta {{ step_2.output.text }} kort.",
}
# Assistant settings no flow edit writes.
_OWN_SETTINGS = {
    "description": "Läser underlaget noga.",
    "logging_enabled": True,
    "insight_enabled": True,
    "inline_file_text": False,
    "knowledge_mode": "tool",
    "data_retention_days": 30,
    "metadata_json": {"anteckning": "behåll"},
}


@dataclass
class Seeded:
    space_id: UUID
    flow_id: UUID
    revision: int
    assistant_ids: list[UUID]
    model_ids: list[UUID]
    group_ids: list[UUID]
    website_id: UUID
    knowledge_id: UUID


async def seed_flow_with_assistants(
    db_container, client, admin_user, completion_model_factory, user_integration_factory
) -> Seeded:
    """Three steps whose assistants hold models, knowledge and settings of their
    own; step 3 reads step 2 in its question and its prompt."""

    space_id = await flow_space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        tenant_id, user_id = container.user().tenant_id, container.user().id
        models = [
            await completion_model_factory(
                session, name, litellm_model_name=f"openai/{name}"
            )
            for name in ("gpt-4o", "gpt-4o-mini")
        ]
        for model in models:
            existing = await session.scalar(
                sa.select(SpacesCompletionModels.completion_model_id).where(
                    SpacesCompletionModels.space_id == space_id,
                    SpacesCompletionModels.completion_model_id == model.id,
                )
            )
            if existing is None:
                session.add(
                    SpacesCompletionModels(
                        space_id=space_id, completion_model_id=model.id
                    )
                )
        embedding_model_id = await session.scalar(
            sa.select(SpacesEmbeddingModels.embedding_model_id).where(
                SpacesEmbeddingModels.space_id == space_id
            )
        )
        assert embedding_model_id is not None
        groups = [
            CollectionsTable(
                name=label,
                size=0,
                user_id=user_id,
                tenant_id=tenant_id,
                embedding_model_id=embedding_model_id,
                space_id=space_id,
            )
            for label in ("Riktlinjer", "Lagar")
        ]
        website = Websites(
            name="Kommunen",
            url=f"https://example.invalid/{uuid4().hex[:8]}",
            download_files=False,
            crawl_type="crawl",
            update_interval="never",
            size=0,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
            space_id=space_id,
        )
        integration = await user_integration_factory(session, tenant_id=tenant_id)
        knowledge = IntegrationKnowledge(
            name="Intranät",
            url="https://example.invalid/intranet",
            space_id=space_id,
            tenant_id=tenant_id,
            embedding_model_id=embedding_model_id,
            user_integration_id=integration.id,
        )
        session.add_all([*groups, website, knowledge])
        await session.flush()
        model_ids = [model.id for model in models]
        group_ids = [group.id for group in groups]
        website_id, knowledge_id = website.id, knowledge.id

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name="Tre steg",
            description="Läser, analyserar och sammanfattar.",
        )
        steps: list[FlowStep] = []
        assistant_ids: list[UUID] = []
        for order in (1, 2, 3):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg{order}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(
                    prompt=PromptCreate(text=_PROMPTS[order])
                ),
            )
            assistant_ids.append(assistant.id)
            steps.append(
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    input_source="flow_input" if order == 1 else "previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                    input_bindings=(
                        {"question": "{{ step_2.output.text }}"} if order == 3 else None
                    ),
                )
            )
        flow = await service.update_flow(flow_id=flow.id, steps=steps)
        session = container.session()
        for index, assistant_id in enumerate(assistant_ids):
            await session.execute(
                sa.update(Assistants)
                .where(Assistants.id == assistant_id)
                .values(completion_model_id=model_ids[index % 2], **_OWN_SETTINGS)
            )
            await session.execute(
                sa.insert(AssistantsGroups).values(
                    assistant_id=assistant_id, group_id=group_ids[index % 2]
                )
            )
            await session.execute(
                sa.insert(AssistantsWebsites).values(
                    assistant_id=assistant_id, website_id=website_id
                )
            )
            await session.execute(
                sa.insert(AssistantIntegrationKnowledgeTable).values(
                    assistant_id=assistant_id, integration_knowledge_id=knowledge_id
                )
            )
    return Seeded(
        space_id,
        flow.id,
        flow.draft_revision,
        assistant_ids,
        model_ids,
        group_ids,
        website_id,
        knowledge_id,
    )


async def assistant_prompt_text(db_container, assistant_id: UUID) -> str | None:
    """The text of the assistant's selected prompt."""

    async with db_container() as container:
        return await container.session().scalar(
            sa.text(
                "select p.text from prompts p join prompts_assistants pa "
                "on pa.prompt_id = p.id where pa.assistant_id = :a and pa.is_selected"
            ),
            {"a": assistant_id},
        )
