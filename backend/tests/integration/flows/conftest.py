"""Shared fixtures for flow integration tests.

Provider calls are faked at the ``CompletionService.get_response`` boundary
and job dispatch at ``job_manager.enqueue``; everything else (services,
repository, schema, version pinning, step claiming) is real.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    CompletionModelResponse,
)
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
)
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.flows.definition import FlowDefinition, FormField, LlmStep
from eneo.jobs.job_manager import job_manager


class ProviderLog:
    """Records every faked completion call: (prompt, text_input, file names)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.answer = None  # callable(prompt, text_input) -> str, optional

    def completion_for(self, prompt: str, text_input: str) -> str:
        if self.answer is not None:
            return self.answer(prompt, text_input)
        return f"LLM[{prompt}|{text_input}]"


@pytest.fixture
def provider(monkeypatch) -> ProviderLog:
    log = ProviderLog()

    async def _fake_get_response(self, model, text_input, **kwargs):
        prompt = kwargs.get("prompt", "")
        log.calls.append(
            {
                "model_id": model.id,
                "prompt": prompt,
                "text_input": text_input,
                "file_names": [f.name for f in kwargs.get("files") or []],
            }
        )
        return CompletionModelResponse(
            completion=log.completion_for(prompt, text_input),
            model=model,
            total_token_count=7,
        )

    monkeypatch.setattr(CompletionService, "get_response", _fake_get_response)
    monkeypatch.setattr(job_manager, "enqueue", AsyncMock())
    return log


@pytest.fixture
def member_space(space_factory, admin_user):
    """A shared space the admin user administers, with the given models."""

    async def _create(session, name, model_ids):
        space = await space_factory(session, name, model_ids)
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        await session.flush()
        return space

    return _create


@pytest.fixture
def publish_flow():
    """Create and publish a flow from a definition; returns the FlowPublic."""

    async def _publish(container, space, definition: FlowDefinition, name="Flow"):
        flow_service = container.flow_service()
        flow = await flow_service.create_flow(
            space_id=space.id, name=name, description=None, definition=definition
        )
        return await flow_service.publish_flow(flow.id)

    return _publish


def topic_field() -> FormField:
    return FormField(key="topic", label="Topic", type="text", required=True)


async def patch_flow(client, url, *, json, headers):
    """An ordinary editor reads the revision before submitting its change."""
    current = await client.get(url, headers=headers)
    revision = current.json().get("revision", 1)
    return await client.patch(
        url, json={"expected_revision": revision, **json}, headers=headers
    )


FLOWS_FLAG = "flows_core"


@pytest.fixture
async def flows_enabled(db_container, admin_user):
    """The tenant has the flows feature on, so the HTTP routes answer."""
    async with db_container() as container:
        service = container.feature_flag_service()
        if await service.feature_flag_repo.one_or_none(name=FLOWS_FLAG) is None:
            await service.create_feature_flag(FLOWS_FLAG)
        flag = await service.feature_flag_repo.one(name=FLOWS_FLAG)
        assert flag.feature_id is not None
        await service.enable_tenant(flag.feature_id, admin_user.tenant_id)


@pytest.fixture
async def bearer(db_container, patch_auth_service_jwt, admin_user):
    """Authorization header of the admin user's session."""
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


def _definition(model_id) -> FlowDefinition:
    return FlowDefinition(
        form_fields=[topic_field()],
        steps=[
            LlmStep(
                key="draft",
                name="Draft",
                prompt="p",
                input="{{form.topic}}",
                model_id=model_id,
            )
        ],
    )


@pytest.fixture
async def published(
    db_container, member_space, completion_model_factory, publish_flow, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "authz-model")
        space = await member_space(session, "Authz Space", [model.id])
        other = await member_space(session, "Other Space", [model.id])
        flow = await publish_flow(container, space, _definition(model.id))
        draft = await container.flow_service().create_flow(
            space_id=space.id,
            name="Draft",
            description=None,
            definition=_definition(model.id),
        )
        # Read inside the session: the rows detach when it closes.
        ids = {"space_id": space.id, "other_space_id": other.id}
    return {"flow": flow, "draft": draft, **ids}


@pytest.fixture
async def second_editor(db_container, admin_user, published, patch_auth_service_jwt):
    """Another member of the flow's space who may edit flows, as a bearer.

    The tenant roles come from the admin user (flows need the tenant-level
    flows permission); the space role is editor."""
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.main.models import ModelId
    from eneo.users.user import UserAdd, UserState

    async with db_container() as container:
        user = await container.user_repo().add(
            UserAdd(
                email=f"editor-{uuid4().hex[:6]}@example.com",
                username=f"editor-{uuid4().hex[:6]}",
                tenant_id=admin_user.tenant_id,
                state=UserState.ACTIVE,
                roles=[ModelId(id=role.id) for role in admin_user.roles],
            )
        )
        container.session().add(
            SpacesUsers(space_id=published["space_id"], user_id=user.id, role="editor")
        )
        await container.session().flush()
        token = container.auth_service().create_access_token_for_user(user)
    return {"user": user, "bearer": {"Authorization": f"Bearer {token}"}}
