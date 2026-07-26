from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.api.flow_runtime_paths import (
    FlowReviewCheckpointRuntimePathsPublic,
    FlowRuntimePathsPublic,
    FlowRuntimePublic,
    build_flow_runtime_paths,
)


def _runtime_review_paths_payload() -> dict[str, str]:
    return {
        "active_template": "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/",
        "edit_template": (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/"
        ),
        "approve_template": (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/"
            "{checkpoint_id}/approve/"
        ),
        "reject_template": (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/"
            "{checkpoint_id}/reject/"
        ),
        "resume_template": (
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/"
            "{checkpoint_id}/resume/"
        ),
    }


def _runtime_paths_payload() -> dict[str, object]:
    return {
        "run_contract": "/api/v1/flows/{id}/run-contract/",
        "graph": "/api/v1/flows/{id}/graph/",
        "upload_step_runtime_file_template": (
            "/api/v1/flows/{id}/steps/{step_id}/runtime-files/"
        ),
        "delete_runtime_file_template": ("/api/v1/flows/{id}/runtime-files/{file_id}/"),
        "create_run": "/api/v1/flows/{id}/runs/",
        "list_runs": "/api/v1/flows/{id}/runs/",
        "cancel_run_template": "/api/v1/flows/{id}/runs/{run_id}/cancel/",
        "rerun_step_template": (
            "/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/"
        ),
        "redispatch_run_template": ("/api/v1/flows/{id}/runs/{run_id}/redispatch/"),
        "review_checkpoints": _runtime_review_paths_payload(),
        "get_graph_for_run_template": "/api/v1/flows/{id}/graph/?run_id={run_id}",
        "get_run_template": "/api/v1/flows/{id}/runs/{run_id}/",
        "list_steps_template": "/api/v1/flows/{id}/runs/{run_id}/steps/",
        "evidence_template": "/api/v1/flows/{id}/runs/{run_id}/evidence/",
        "provider_calls_template": ("/api/v1/flows/{id}/runs/{run_id}/provider-calls/"),
        "export_evidence_template": (
            "/api/v1/flows/{id}/runs/{run_id}/evidence/export"
        ),
        "artifact_signed_url_template": (
            "/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/"
        ),
    }


def _runtime_public_payload() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "space_id": str(uuid4()),
        "name": "Published flow",
        "description": "Runtime-safe projection",
        "published_version": 3,
        "runtime_paths": _runtime_paths_payload(),
    }


def test_build_flow_runtime_paths_uses_explicit_api_prefix() -> None:
    flow_id = uuid4()

    runtime_paths = build_flow_runtime_paths(flow_id, api_prefix="/custom-api/")

    assert runtime_paths.run_contract == f"/custom-api/flows/{flow_id}/run-contract/"
    assert runtime_paths.graph == f"/custom-api/flows/{flow_id}/graph/"
    assert (
        runtime_paths.upload_step_runtime_file_template
        == f"/custom-api/flows/{flow_id}/steps/{{step_id}}/runtime-files/"
    )
    assert (
        runtime_paths.delete_runtime_file_template
        == f"/custom-api/flows/{flow_id}/runtime-files/{{file_id}}/"
    )
    assert runtime_paths.create_run == f"/custom-api/flows/{flow_id}/runs/"
    assert runtime_paths.list_runs == f"/custom-api/flows/{flow_id}/runs/"
    assert (
        runtime_paths.cancel_run_template
        == f"/custom-api/flows/{flow_id}/runs/{{run_id}}/cancel/"
    )
    assert (
        runtime_paths.rerun_step_template
        == f"/custom-api/flows/{flow_id}/runs/{{run_id}}/steps/"
        "{step_id}/rerun/"
    )
    assert (
        runtime_paths.redispatch_run_template
        == f"/custom-api/flows/{flow_id}/runs/{{run_id}}/redispatch/"
    )
    assert (
        runtime_paths.review_checkpoints.active_template
        == f"/custom-api/flows/{flow_id}/runs/{{run_id}}/"
        "review-checkpoints/active/"
    )
    assert (
        runtime_paths.review_checkpoints.resume_template
        == f"/custom-api/flows/{flow_id}/runs/{{run_id}}/"
        "review-checkpoints/{checkpoint_id}/resume/"
    )
    assert (
        runtime_paths.get_graph_for_run_template
        == f"/custom-api/flows/{flow_id}/graph/?run_id={{run_id}}"
    )
    assert (
        runtime_paths.export_evidence_template
        == f"/custom-api/flows/{flow_id}/runs/{{run_id}}/evidence/export"
    )
    assert runtime_paths.provider_calls_template == (
        f"/custom-api/flows/{flow_id}/runs/{{run_id}}/provider-calls/"
    )
    assert (
        runtime_paths.artifact_signed_url_template
        == f"/custom-api/flows/{flow_id}/runs/{{run_id}}/artifacts/"
        "{file_id}/signed-url/"
    )


def test_build_flow_runtime_paths_normalizes_missing_leading_slash() -> None:
    flow_id = uuid4()

    runtime_paths = build_flow_runtime_paths(flow_id, api_prefix="api")

    assert runtime_paths.create_run == f"/api/flows/{flow_id}/runs/"


def test_flow_runtime_discovery_models_reject_unknown_response_fields() -> None:
    cases = (
        (
            FlowReviewCheckpointRuntimePathsPublic,
            _runtime_review_paths_payload(),
        ),
        (FlowRuntimePathsPublic, _runtime_paths_payload()),
        (FlowRuntimePublic, _runtime_public_payload()),
    )

    for model, payload in cases:
        with pytest.raises(ValidationError):
            model.model_validate({**payload, "unexpected": True})


def test_flow_runtime_discovery_models_construct_from_attributes() -> None:
    review_paths = SimpleNamespace(
        **_runtime_review_paths_payload(), legacy_extra="ignored"
    )
    runtime_paths = SimpleNamespace(
        **{
            **_runtime_paths_payload(),
            "review_checkpoints": review_paths,
            "legacy_extra": "ignored",
        }
    )
    runtime = SimpleNamespace(
        id=uuid4(),
        space_id=uuid4(),
        name="Published flow",
        description=None,
        published_version=3,
        created_at=None,
        updated_at=None,
        runtime_paths=runtime_paths,
        legacy_extra="ignored",
    )

    review_paths_public = FlowReviewCheckpointRuntimePathsPublic.model_validate(
        review_paths
    )
    runtime_paths_public = FlowRuntimePathsPublic.model_validate(runtime_paths)
    runtime_public = FlowRuntimePublic.model_validate(runtime)

    assert review_paths_public.resume_template.endswith("{checkpoint_id}/resume/")
    assert runtime_paths_public.review_checkpoints is not None
    assert runtime_public.runtime_paths.get_run_template.endswith("{run_id}/")
