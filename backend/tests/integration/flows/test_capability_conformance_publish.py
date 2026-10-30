"""Every proposable triple publishes through the public flow API.

Conformance flows come from the unit-level table; here each is created, given
the flow-level setup the platform requires (a transcription model for audio
steps, a stored template for template fill) and published over HTTP.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from eneo.database.tables.spaces_table import SpacesTranscriptionModels
from eneo.flows.enums import FlowAuthoringInputSource
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from tests.integration.flows.test_flow_live_transcription_session import (
    UNREACHABLE_ENDPOINT,
    _create_space,
    _create_transcription_model,
)
from tests.integration.flows.test_flow_template_attachment_persistence import (
    DOCX_MIME,
    _template_bytes,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

Triple = tuple[str, str, str]

# (input type, output type, output mode): the manifest's proposable cells,
# written out so that a new one has to be added here by hand.
PROPOSABLE_TRIPLES: tuple[Triple, ...] = (
    ("text", "text", "pass_through"),
    ("text", "text", "compose_text"),
    ("text", "json", "pass_through"),
    ("text", "pdf", "render_verbatim"),
    ("text", "docx", "render_verbatim"),
    ("text", "docx", "template_fill"),
    ("json", "text", "pass_through"),
    ("json", "json", "pass_through"),
    ("json", "pdf", "pass_through"),
    ("json", "docx", "pass_through"),
    ("json", "docx", "template_fill"),
    ("audio", "text", "pass_through"),
    ("audio", "text", "transcribe_only"),
    ("audio", "json", "pass_through"),
    ("audio", "pdf", "pass_through"),
    ("audio", "docx", "pass_through"),
    ("audio", "docx", "template_fill"),
    ("document", "text", "pass_through"),
    ("document", "json", "pass_through"),
    ("document", "pdf", "pass_through"),
    ("document", "docx", "pass_through"),
    ("document", "docx", "template_fill"),
    ("file", "text", "pass_through"),
    ("file", "json", "pass_through"),
    ("file", "pdf", "pass_through"),
    ("file", "docx", "pass_through"),
    ("file", "docx", "template_fill"),
    ("any", "text", "pass_through"),
    ("any", "json", "pass_through"),
    ("any", "pdf", "pass_through"),
    ("any", "docx", "pass_through"),
    ("any", "docx", "template_fill"),
)


def _conformance_step(
    ref: str,
    triple: Triple,
    *,
    source: FlowAuthoringInputSource = FlowAuthoringInputSource.FLOW_INPUT,
) -> StepSpec:
    input_type, output_type, output_mode = triple
    return StepSpec(
        plan_step_ref=ref,
        name=f"Steg {ref}",
        assistant_spec=AssistantSpec(
            instructions="Hantera underlaget och leverera resultatet."
        ),
        input_source=source,
        input_type=InputType(input_type),
        output_type=OutputType(output_type),
        output_mode=OutputMode(output_mode),
    )


def conformance_flow(triple: Triple) -> FlowDraftSpecCore:
    """A flow the platform accepts that contains the triple as a step.

    An audio step reads the flow input, and only one step may. The platform
    refuses a flow whose first step is audio and whose last step is a document
    unless that first step is a transcription, so an audio step that itself
    produces a document is only accepted ahead of a text-producing last step.
    """
    input_type, output_type, _mode = triple
    steps = [_conformance_step("step_a", triple)]
    if input_type == "audio" and output_type in {"pdf", "docx"}:
        steps.append(
            _conformance_step(
                "step_b",
                ("text", "text", "pass_through"),
                source=FlowAuthoringInputSource.PREVIOUS_STEP,
            )
        )
    return FlowDraftSpecCore(flow_name=f"Konformans {'-'.join(triple)}", steps=steps)


async def _publish_conformance_flow(
    client: AsyncClient,
    headers: Mapping[str, str],
    *,
    space_id: str,
    transcription_model_id: str,
    spec: FlowDraftSpecCore,
) -> str | None:
    """None when the flow publishes, else what the platform answered."""
    created = await client.post(
        "/api/v1/flows/",
        json={
            "space_id": space_id,
            "name": f"{spec.flow_name} {uuid4().hex[:6]}",
        },
        headers=headers,
    )
    if created.status_code != 201:
        return f"create: {created.text}"
    flow_id = created.json()["id"]

    steps: list[dict[str, object]] = []
    for order, step in enumerate(spec.steps, start=1):
        assistant = await client.post(
            f"/api/v1/flows/{flow_id}/assistants/",
            json={"name": f"conformance-{order}-{uuid4().hex[:6]}"},
            headers=headers,
        )
        if assistant.status_code != 201:
            return f"assistant: {assistant.text}"
        payload: dict[str, object] = {
            "assistant_id": assistant.json()["id"],
            "step_order": order,
            "user_description": step.name,
            "input_source": step.input_source.value,
            "input_type": step.input_type.value,
            "output_mode": step.output_mode.value,
            "output_type": step.output_type.value,
        }
        if step.output_mode.value == "template_fill":
            upload = await client.post(
                f"/api/v1/flows/{flow_id}/template-files/",
                files={
                    "upload_file": ("mall.docx", _template_bytes("case_id"), DOCX_MIME)
                },
                headers=headers,
            )
            if upload.status_code != 201:
                return f"template: {upload.text}"
            payload["output_config"] = {
                "template_asset_id": upload.json()["id"],
                "bindings": {"case_id": ""},
            }
        steps.append(payload)

    updated = await client.patch(
        f"/api/v1/flows/{flow_id}/",
        json={
            "name": spec.flow_name,
            "description": None,
            "steps": steps,
            "metadata_json": {
                "wizard": {
                    "transcription_enabled": True,
                    "transcription_model": {"id": transcription_model_id},
                    "transcription_language": "sv",
                }
            },
        },
        headers=headers,
    )
    if updated.status_code != 200:
        return f"update: {updated.text}"
    published = await client.post(f"/api/v1/flows/{flow_id}/publish/", headers=headers)
    return None if published.status_code == 200 else f"publish: {published.text}"


async def test_every_proposable_triple_publishes(
    client: AsyncClient, flow_process_auth_headers, db_container
) -> None:
    headers = dict(flow_process_auth_headers)
    space_id = await _create_space(client, headers)
    model = await _create_transcription_model(
        client, headers, endpoint=UNREACHABLE_ENDPOINT, supports_realtime=False
    )
    async with db_container() as container:
        container.session().add(
            SpacesTranscriptionModels(
                space_id=UUID(space_id), transcription_model_id=UUID(model["id"])
            )
        )

    refused: dict[Triple, str] = {}
    for triple in PROPOSABLE_TRIPLES:
        outcome = await _publish_conformance_flow(
            client,
            headers,
            space_id=space_id,
            transcription_model_id=model["id"],
            spec=conformance_flow(triple),
        )
        if outcome is not None:
            refused[triple] = outcome

    assert len(PROPOSABLE_TRIPLES) == 32
    assert refused == {}
