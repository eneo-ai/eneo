"""A connection's credential is entered in the editor after the step exists:
the draft saves with the auth mode declared, publish waits for the credential."""

from __future__ import annotations

from uuid import uuid4

from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_validators import draft_step_refusals, publish_step_refusals


def _http_source_step(auth: dict[str, object]) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=1,
        user_description="Hämta ärendet",
        input_source="http_get",
        input_type="text",
        input_config={"url": "https://api.example.se/cases", "auth": auth},
        output_mode="pass_through",
        output_type="text",
    )


def test_a_draft_saves_an_auth_mode_before_its_credential_exists():
    steps = [_http_source_step({"mode": "api_key", "header_name": "X-API-Key"})]

    assert draft_step_refusals(steps, metadata_json=None) == []

    refusals = publish_step_refusals(steps, metadata_json=None, prompt_templates={})
    assert [str(refusal) for refusal in refusals] == [
        "Step 1: input_config validation failed: HTTP_MISSING_AUTH"
    ]


def test_a_stored_credential_satisfies_publish():
    steps = [_http_source_step({"mode": "api_key", "key": {"$secret": "stored"}})]

    assert publish_step_refusals(steps, metadata_json=None, prompt_templates={}) == []
