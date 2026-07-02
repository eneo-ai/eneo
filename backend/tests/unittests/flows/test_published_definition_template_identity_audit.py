from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from eneo.flows.published_definition import (
    FLOW_DEFINITION_SCHEMA_VERSION,
    PublishedTemplateIdentityAuditResult,
    PublishedTemplateIdentityAuditSnapshot,
    PublishedTemplateIdentityBlockerReason,
    PublishedTemplateIdentityLiveAsset,
    audit_published_template_identity_readiness,
)


def _snapshot(
    *,
    tenant_id: UUID,
    flow_id: UUID,
    version: int = 1,
    output_config: object | None,
    output_mode: object = "template_fill",
    schema_version: int = FLOW_DEFINITION_SCHEMA_VERSION,
) -> PublishedTemplateIdentityAuditSnapshot:
    return PublishedTemplateIdentityAuditSnapshot(
        tenant_id=tenant_id,
        flow_id=flow_id,
        version=version,
        definition_json={
            "schema_version": schema_version,
            "flow_id": str(flow_id),
            "steps": [
                {
                    "step_order": 3,
                    "output_mode": output_mode,
                    "output_config": output_config,
                }
            ],
        },
    )


def _asset(
    *,
    tenant_id: UUID,
    flow_id: UUID,
    asset_id: UUID,
    file_id: UUID,
    checksum: str = "template-checksum",
) -> PublishedTemplateIdentityLiveAsset:
    return PublishedTemplateIdentityLiveAsset(
        tenant_id=tenant_id,
        flow_id=flow_id,
        asset_id=asset_id,
        file_id=file_id,
        checksum=checksum,
    )


def _counts(
    result: PublishedTemplateIdentityAuditResult,
) -> dict[PublishedTemplateIdentityBlockerReason, int]:
    return {item.reason: item.count for item in result.blocker_counts}


def _reasons(
    result: PublishedTemplateIdentityAuditResult,
) -> set[PublishedTemplateIdentityBlockerReason]:
    return {item.reason for item in result.samples}


def test_template_identity_audit_passes_ready_asset_snapshot() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()
    asset_id = uuid4()
    file_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config={
                    "template_asset_id": str(asset_id),
                    "template_file_id": str(file_id),
                    "template_checksum": "template-checksum",
                },
            ),
        ),
        live_assets=(
            _asset(
                tenant_id=tenant_id,
                flow_id=flow_id,
                asset_id=asset_id,
                file_id=file_id,
            ),
        ),
    )

    assert result.is_ready_for_template_file_fallback_deletion
    assert result.total_versions == 1
    assert result.template_fill_steps == 1
    assert result.ready_template_fill_steps == 1
    assert result.blocked_template_fill_steps == 0
    assert result.blocker_counts == ()
    assert result.samples == ()


@pytest.mark.parametrize(
    ("output_config", "reason"),
    [
        (
            {
                "template_file_id": str(uuid4()),
                "template_checksum": "template-checksum",
            },
            PublishedTemplateIdentityBlockerReason.MISSING_TEMPLATE_ASSET_ID,
        ),
        (
            {
                "template_asset_id": "not-a-uuid",
                "template_checksum": "template-checksum",
            },
            PublishedTemplateIdentityBlockerReason.INVALID_TEMPLATE_ASSET_ID,
        ),
        (
            {
                "template_asset_id": str(uuid4()),
                "template_file_id": str(uuid4()),
            },
            PublishedTemplateIdentityBlockerReason.MISSING_TEMPLATE_CHECKSUM,
        ),
        (
            {
                "template_asset_id": str(uuid4()),
                "template_file_id": str(uuid4()),
                "template_checksum": "",
            },
            PublishedTemplateIdentityBlockerReason.MISSING_TEMPLATE_CHECKSUM,
        ),
    ],
)
def test_template_identity_audit_blocks_missing_or_unreadable_required_fields(
    output_config: object,
    reason: PublishedTemplateIdentityBlockerReason,
) -> None:
    tenant_id = uuid4()
    flow_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config=output_config,
            ),
        ),
        live_assets=(),
    )

    assert not result.is_ready_for_template_file_fallback_deletion
    assert _counts(result)[reason] == 1
    assert reason in _reasons(result)
    assert result.samples[0].tenant_id == tenant_id
    assert result.samples[0].flow_id == flow_id
    assert result.samples[0].version == 1
    assert result.samples[0].step_order == 3


def test_template_identity_audit_blocks_non_live_asset() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config={
                    "template_asset_id": str(uuid4()),
                    "template_checksum": "template-checksum",
                },
            ),
        ),
        live_assets=(),
    )

    assert _counts(result)[PublishedTemplateIdentityBlockerReason.ASSET_NOT_LIVE] == 1


def test_template_identity_audit_blocks_asset_file_mismatch() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()
    asset_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config={
                    "template_asset_id": str(asset_id),
                    "template_file_id": str(uuid4()),
                    "template_checksum": "template-checksum",
                },
            ),
        ),
        live_assets=(
            _asset(
                tenant_id=tenant_id,
                flow_id=flow_id,
                asset_id=asset_id,
                file_id=uuid4(),
            ),
        ),
    )

    assert (
        _counts(result)[PublishedTemplateIdentityBlockerReason.ASSET_FILE_MISMATCH] == 1
    )


def test_template_identity_audit_blocks_checksum_mismatch() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()
    asset_id = uuid4()
    file_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config={
                    "template_asset_id": str(asset_id),
                    "template_file_id": str(file_id),
                    "template_checksum": "published-checksum",
                },
            ),
        ),
        live_assets=(
            _asset(
                tenant_id=tenant_id,
                flow_id=flow_id,
                asset_id=asset_id,
                file_id=file_id,
                checksum="current-file-checksum",
            ),
        ),
    )

    assert (
        _counts(result)[
            PublishedTemplateIdentityBlockerReason.TEMPLATE_CHECKSUM_MISMATCH
        ]
        == 1
    )


def test_template_identity_audit_preserves_runtime_checksum_whitespace() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()
    asset_id = uuid4()
    file_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config={
                    "template_asset_id": str(asset_id),
                    "template_file_id": str(file_id),
                    "template_checksum": " template-checksum ",
                },
            ),
        ),
        live_assets=(
            _asset(
                tenant_id=tenant_id,
                flow_id=flow_id,
                asset_id=asset_id,
                file_id=file_id,
                checksum="template-checksum",
            ),
        ),
    )

    assert (
        _counts(result)[
            PublishedTemplateIdentityBlockerReason.TEMPLATE_CHECKSUM_MISMATCH
        ]
        == 1
    )


def test_template_identity_audit_blocks_file_only_ambiguous_asset_mapping() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()
    file_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config={
                    "template_file_id": str(file_id),
                    "template_checksum": "template-checksum",
                },
            ),
        ),
        live_assets=(
            _asset(
                tenant_id=tenant_id,
                flow_id=flow_id,
                asset_id=uuid4(),
                file_id=file_id,
            ),
            _asset(
                tenant_id=tenant_id,
                flow_id=flow_id,
                asset_id=uuid4(),
                file_id=file_id,
            ),
        ),
    )

    counts = _counts(result)
    assert counts[PublishedTemplateIdentityBlockerReason.MISSING_TEMPLATE_ASSET_ID] == 1
    assert (
        counts[PublishedTemplateIdentityBlockerReason.AMBIGUOUS_FILE_TO_ASSET_MAPPING]
        == 1
    )


def test_template_identity_audit_fails_closed_for_unknown_schema() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config=None,
                schema_version=FLOW_DEFINITION_SCHEMA_VERSION + 1,
            ),
        ),
        live_assets=(),
    )

    assert _counts(result)[PublishedTemplateIdentityBlockerReason.UNKNOWN_SCHEMA] == 1
    assert result.samples[0].step_order is None


def test_template_identity_audit_fails_closed_for_unreadable_output_config() -> None:
    tenant_id = uuid4()
    flow_id = uuid4()

    result = audit_published_template_identity_readiness(
        snapshots=(
            _snapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                output_config="not-an-object",
            ),
        ),
        live_assets=(),
    )

    assert (
        _counts(result)[PublishedTemplateIdentityBlockerReason.UNREADABLE_OUTPUT_CONFIG]
        == 1
    )
