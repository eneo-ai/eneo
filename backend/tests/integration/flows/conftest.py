"""Shared fixtures for flow integration tests.

Provider calls are faked at the ``CompletionService.get_response`` boundary
and job dispatch at ``job_manager.enqueue``; everything else (services,
repository, schema, version pinning, step claiming) is real.
"""

from unittest.mock import AsyncMock

import pytest

from eneo.ai_models.completion_models.completion_model import (
    CompletionModelResponse,
)
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
)
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.flows.definition import FlowDefinition, FormField
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
