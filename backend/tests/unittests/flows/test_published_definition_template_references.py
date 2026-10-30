from __future__ import annotations

from uuid import uuid4

from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    PublishedTemplateReferenceUndeterminedReason,
    scan_published_template_references,
)


def test_scan_published_template_references_collects_template_ids() -> None:
    template_asset_id = uuid4()
    template_file_id = uuid4()

    scan = scan_published_template_references(
        {
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "steps": [
                {
                    "output_config": {
                        "template_asset_id": str(template_asset_id),
                        "template_file_id": str(template_file_id),
                    }
                }
            ],
        }
    )

    assert scan.undetermined_reason is None
    assert scan.may_reference(
        template_asset_id=template_asset_id,
        template_file_id=template_file_id,
    )


def test_scan_published_template_references_ignores_unrelated_known_schema_drift() -> (
    None
):
    template_asset_id = uuid4()
    template_file_id = uuid4()

    scan = scan_published_template_references(
        {
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "steps": [
                {"output_config": {"unrelated": {"not": "runtime-validated"}}},
                {"output_config": None},
                "not-a-step",
            ],
        }
    )

    assert scan.undetermined_reason is None
    assert not scan.may_reference(
        template_asset_id=template_asset_id,
        template_file_id=template_file_id,
    )


def test_scan_published_template_references_fails_closed_on_unreadable_reference() -> (
    None
):
    scan = scan_published_template_references(
        {
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "steps": [{"output_config": {"template_file_id": "not-a-uuid"}}],
        }
    )

    assert (
        scan.undetermined_reason
        is PublishedTemplateReferenceUndeterminedReason.UNREADABLE_REFERENCE
    )
    assert scan.may_reference(
        template_asset_id=uuid4(),
        template_file_id=uuid4(),
    )


def test_scan_published_template_references_fails_closed_on_unknown_schema() -> None:
    scan = scan_published_template_references(
        {
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION + 1,
            "steps": [],
        }
    )

    assert (
        scan.undetermined_reason
        is PublishedTemplateReferenceUndeterminedReason.UNKNOWN_SCHEMA
    )
    assert scan.may_reference(
        template_asset_id=uuid4(),
        template_file_id=uuid4(),
    )
