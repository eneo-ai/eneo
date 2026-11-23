"""The readiness report counts a published step's model only when the step
calls it, by the rule publishing and the step's execution share: a step that
sends the run's result calls none, so its assistant needs no model."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.enums import FlowOutputMode
from eneo.flows.http_transport.authored_config import HttpBodyMode

# Every output mode, and every body mode of an http_post step.
_ROWS = [
    *(
        (mode.value, None)
        for mode in FlowOutputMode
        if mode is not FlowOutputMode.HTTP_POST
    ),
    *(("http_post", body.value) for body in HttpBodyMode),
]
_CALLS_MODEL = {
    ("pass_through", None),
    ("speaker_mapping", None),
    *(
        ("http_post", body.value)
        for body in HttpBodyMode
        if body is not HttpBodyMode.RUN_RESULT
    ),
}


def _output_config(body: str | None) -> dict[str, object] | None:
    if body is None:
        return None
    return {
        "url": "https://receiver.example.org/results",
        "auth": {"mode": "none"},
        "body": {"mode": body},
    }


@pytest.mark.parametrize(("mode", "body"), _ROWS)
@pytest.mark.asyncio
async def test_the_readiness_report_asks_for_a_model_only_for_a_step_that_calls_one(
    monkeypatch, mode, body
):
    from eneo.cli.model_capacity_readiness import report_tenant
    from eneo.flows import published_definition
    from eneo.flows.domain.flow import FlowSparse
    from eneo.flows.domain.runtime import RuntimeStep
    from tests.unittests.cli.test_model_capacity_readiness import (
        FlowRepository,
        model,
        tenant,
    )

    owner = tenant()
    repository = FlowRepository([owner])
    flow_id = uuid4()
    repository.flows.append(
        FlowSparse(
            id=flow_id,
            tenant_id=owner.id,
            space_id=uuid4(),
            name="flow",
            published_version=1,
        )
    )
    repository.versions[owner.id, flow_id, 1] = SimpleNamespace(
        tenant_id=owner.id,
        definition_json={},
        definition_checksum="",
        version=1,
    )
    # The published step as the report reads it, whatever its mode needs.
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode=mode,
        output_config=_output_config(body),
    )
    monkeypatch.setattr(
        published_definition,
        "parse_verified_published_definition",
        lambda *_args, **_kwargs: SimpleNamespace(runtime_steps=lambda: [step]),
    )
    asked: list[object] = []
    completion = model(owner)

    async def assistant_model(_owner, assistant_id):
        asked.append(assistant_id)
        return completion

    repository.assistant_model = assistant_model

    await report_tenant(repository, owner)

    assert bool(asked) == ((mode, body) in _CALLS_MODEL)
