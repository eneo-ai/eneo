from uuid import uuid4

import pytest

from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.step_config import clean_inactive_step_config


@pytest.mark.parametrize("input_source", ["http_get", "flow_input"])
@pytest.mark.parametrize("output_mode", ["http_post", "template_fill", "pass_through"])
def test_cleanup_preserves_active_config_and_unrelated_values(
    input_source, output_mode
):
    http = {
        "url": "https://example.test/private",
        "auth": {"unexpected": ["obsolete"]},
        "timeout_seconds": 12,
        "body": {"mode": "none"},
        "custom_headers": [{"value": {"$secret": "stored"}}],
        "response_format": "json",
    }
    template = {
        "template_asset_id": str(uuid4()),
        "template_file_id": str(uuid4()),
        "template_name": "template.docx",
        "template_checksum": "checksum",
        "placeholders": ["name"],
        "bindings": {"name": "{{flow_input.text}}"},
    }
    retained = {
        "runtime_input": {"files": []},
        "item_map": {"extension": True},
        "retrieval_policy": {"version": 1, "mode": "best_effort"},
        "citation_mode": "off",
        "speaker_mapping": {"extension": []},
        "future_extension": {"url": "nested-url"},
    }
    step = FlowStep(
        assistant_id=uuid4(),
        step_order=1,
        input_source=input_source,
        input_type="text",
        output_mode=output_mode,
        output_type="text",
        input_config={**http, **template, **retained},
        output_config={**http, **template, **retained},
        timeout_seconds=90,
    )
    before = step.model_dump()
    cleaned = clean_inactive_step_config(step)
    assert cleaned.input_config == {
        **(http if input_source == "http_get" else {}),
        **template,
        **retained,
    }
    assert cleaned.output_config == {
        **(http if output_mode == "http_post" else {}),
        **(template if output_mode == "template_fill" else {}),
        **retained,
    }
    assert cleaned.timeout_seconds == 90
    assert step.model_dump() == before
    assert clean_inactive_step_config(cleaned) == cleaned


@pytest.mark.parametrize(
    "config, expected", [(None, None), ({}, {}), ({"url": "obsolete"}, None)]
)
def test_cleanup_collapses_only_configs_it_empties(config, expected):
    step = FlowStep(
        assistant_id=uuid4(),
        step_order=1,
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
        input_config=config,
        output_config=config,
    )
    cleaned = clean_inactive_step_config(step)
    assert cleaned.input_config == expected
    assert cleaned.output_config == expected


@pytest.mark.parametrize("config_kind", ["unknown", "http", "template"])
def test_cleaned_active_or_unknown_config_keeps_export_refusal(config_kind):
    from datetime import datetime, timezone

    from eneo.flow_packages.application.flow_package_export_service import (
        build_flow_package_export_envelope,
    )
    from eneo.flow_packages.domain.flow_package_errors import (
        FlowPackageExportError,
        FlowPackageExportErrorCode,
    )
    from eneo.flow_packages.domain.flow_package_manifest import (
        EneoPackageKind,
        FlowPackageManifestMetadata,
    )
    from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
    from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
    from eneo.flows.domain.flow import Flow

    step = FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=1,
        input_source="flow_input",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
        output_config={"extension": "unportable"},
    )
    expected = FlowPackageExportErrorCode.STEP_CONFIG_NOT_PORTABLE
    if config_kind == "http":
        step.output_mode = "http_post"
        step.output_config = {
            "url": "https://example.test/output",
            "auth": {"mode": "none"},
        }
    elif config_kind == "template":
        step.output_mode = "template_fill"
        step.output_type = "docx"
        step.output_config = {"template_asset_id": str(uuid4())}
        expected = FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED
    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        steps=[clean_inactive_step_config(step)],
    )
    with pytest.raises(FlowPackageExportError) as exc:
        build_flow_package_export_envelope(
            flow=flow,
            assistant_snapshots={
                step.assistant_id: AssistantAuthoringSnapshot(
                    instructions="Return input", model=None, knowledge_refs=()
                )
            },
            resource_bindings=(),
            manifest_metadata=FlowPackageManifestMetadata(
                schema_version=1,
                kind=EneoPackageKind.FLOW,
                package_id="se.test.cleanup",
                package_version="1.0.0",
                name="Cleanup",
                description="Portable flow",
            ),
            provenance=FlowPackageProvenance.for_portable_export(
                exported_at=datetime.now(timezone.utc), omissions=[]
            ),
        )
    assert exc.value.code == expected
