import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from eneo.authentication.auth_models import (
    ApiKeyUpdateRequest,
    ApiKeyV2,
    ApiKeyV2InDB,
)
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import FlowRuns

REPO_ROOT = Path(__file__).parents[2]


def _check_constraint_sql(table: object, constraint_name: str) -> str:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def test_service_principal_identity_stays_internal_to_api_key_persistence():
    assert "service_principal_id" in ApiKeyV2InDB.model_fields
    assert "service_principal_id" not in ApiKeyV2.model_fields


def test_service_key_scope_cannot_drift_through_update_contract():
    assert "scope_type" not in ApiKeyUpdateRequest.model_fields
    assert "scope_id" not in ApiKeyUpdateRequest.model_fields


def test_flow_and_file_runtime_ownership_does_not_use_exact_key_owner_columns():
    scanned_roots = (
        REPO_ROOT / "src" / "eneo" / "flows",
        REPO_ROOT / "src" / "eneo" / "files",
    )
    hits: list[str] = []
    for root in scanned_roots:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for forbidden in (
                "principal_api_key_id",
                "owner_api_key_id",
                "build_service_key_user",
            ):
                if forbidden in text:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{forbidden}")

    assert hits == []


def test_flow_and_file_runtime_does_not_synthesize_user_identities():
    # Why: Flow/File runtime identity is service-principal based; runtime must
    # not rebuild a UserInDB shape after actor resolution.
    pattern = re.compile(r"\bUserInDB\(")
    scanned_roots = (
        REPO_ROOT / "src" / "eneo" / "flows",
        REPO_ROOT / "src" / "eneo" / "files",
    )
    hits: list[str] = []

    for root in scanned_roots:
        for path in sorted(root.rglob("*.py")):
            relative_path = path.relative_to(REPO_ROOT).as_posix()
            if pattern.search(path.read_text(encoding="utf-8")):
                hits.append(relative_path)

    assert hits == []


def test_flow_runtime_does_not_use_user_container_overrides():
    runtime_root = REPO_ROOT / "src" / "eneo" / "flows" / "runtime"
    pattern = re.compile(r"\boverride_user\b|\bcontainer_overrides\b")
    hits: list[str] = []

    for path in sorted(runtime_root.rglob("*.py")):
        if pattern.search(path.read_text(encoding="utf-8")):
            hits.append(path.relative_to(REPO_ROOT).as_posix())

    assert hits == []


def test_flow_run_actor_stays_free_of_container_user_bridge_imports():
    actor_source = (
        REPO_ROOT / "src" / "eneo" / "flows" / "runtime" / "flow_run_actor.py"
    ).read_text(encoding="utf-8")

    assert "TenantInDB" not in actor_source
    assert "UserState" not in actor_source


def test_flow_runtime_does_not_use_user_wired_template_asset_service():
    runtime_root = REPO_ROOT / "src" / "eneo" / "flows" / "runtime"
    offenders: list[str] = []

    for path in sorted(runtime_root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if (
            "FlowTemplateAssetService" in source
            or "flow_template_asset_service" in source
        ):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_flow_and_file_runtime_ownership_uses_stable_service_principal_columns():
    flow_run_columns = FlowRuns.__table__.columns
    file_columns = Files.__table__.columns

    assert "principal_api_key_id" not in flow_run_columns
    assert "owner_api_key_id" not in file_columns
    assert {
        "principal_service_id",
        "created_by_api_key_id",
        "runtime_service_permission",
    }.issubset(flow_run_columns.keys())
    assert "owner_service_id" in file_columns
    assert "principal_service_id IS NOT NULL" in _check_constraint_sql(
        FlowRuns,
        "ck_flow_runs_principal_identity",
    )
    assert "owner_service_id IS NOT NULL" in _check_constraint_sql(
        Files,
        "ck_files_owner_identity",
    )
    assert "principal_service_id" in (
        REPO_ROOT / "src" / "eneo" / "flows" / "domain" / "flow.py"
    ).read_text(encoding="utf-8")
    assert "owner_service_id" in (
        REPO_ROOT / "src" / "eneo" / "files" / "file_models.py"
    ).read_text(encoding="utf-8")
