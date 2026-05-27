from pathlib import Path

from intric.authentication.auth_models import (
    ApiKeyUpdateRequest,
    ApiKeyV2,
    ApiKeyV2InDB,
)

REPO_ROOT = Path(__file__).parents[2]


def test_service_principal_identity_stays_internal_to_api_key_persistence():
    assert "service_principal_id" in ApiKeyV2InDB.model_fields
    assert "service_principal_id" not in ApiKeyV2.model_fields


def test_service_key_scope_cannot_drift_through_update_contract():
    assert "scope_type" not in ApiKeyUpdateRequest.model_fields
    assert "scope_id" not in ApiKeyUpdateRequest.model_fields


def test_flow_and_file_runtime_ownership_waits_for_dedicated_migration_task():
    scanned_roots = (
        REPO_ROOT / "src" / "intric" / "flows",
        REPO_ROOT / "src" / "intric" / "files",
    )
    hits: list[str] = []
    for root in scanned_roots:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "service_principal_id" in text or "owner_service_id" in text:
                hits.append(str(path.relative_to(REPO_ROOT)))

    assert hits == []
