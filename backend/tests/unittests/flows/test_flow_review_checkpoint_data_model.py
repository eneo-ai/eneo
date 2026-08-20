from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.category_mappings import CATEGORY_MAPPINGS
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_models import FlowServicePrincipalActorPublic
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.api.flow_models import (
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointEvidencePublic,
    FlowRunReviewCheckpointPublic,
)
from eneo.flows.enums import (
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode


def _service_principal_actor() -> FlowServicePrincipalActorPublic:
    return FlowServicePrincipalActorPublic(
        id=uuid4(),
        display_name="Runtime service principal",
    )


def _review_checkpoint_public_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "flow_id": uuid4(),
        "flow_run_id": uuid4(),
        "step_id": uuid4(),
        "step_order": 1,
        "attempt_no": 1,
        "state": FlowRunReviewCheckpointState.AWAITING_REVIEW,
        "revision": 1,
        "schema_version": 1,
        "review_mode": FlowStepReviewMode.VIEW,
        "output_type": FlowOutputType.JSON,
        "requester_principal_type": PrincipalType.SERVICE_KEY,
        "requester_service_principal": _service_principal_actor(),
        "decided_by_principal_type": None,
        "created_at": now,
        "updated_at": now,
    }


def _review_checkpoint_evidence_payload() -> dict[str, object]:
    payload = _review_checkpoint_public_payload()
    payload["decision"] = None
    payload["resume_key_present"] = False
    return payload


def test_review_checkpoint_edit_schema_documents_payload_integrity_contract() -> None:
    edit_schema = FlowRunReviewCheckpointEditRequest.model_json_schema()
    checkpoint_schema = FlowRunReviewCheckpointPublic.model_json_schema()

    edit_description = edit_schema["properties"]["edited_value"]["description"]
    assert "not a payload envelope" in edit_description
    assert "the persisted `text` rendering is derived from it" in edit_description
    assert (
        "Runtime-owned payload metadata is preserved from the stored checkpoint"
        in edit_description
    )
    assert "`review_mode` is `edit`" in edit_description
    assert (
        "unsupported versions as non-editable"
        in checkpoint_schema["properties"]["schema_version"]["description"]
    )


def test_review_checkpoint_public_accepts_service_principal_actor_shape() -> None:
    checkpoint = FlowRunReviewCheckpointPublic.model_validate(
        _review_checkpoint_public_payload()
    )

    assert checkpoint.requester_principal_type == PrincipalType.SERVICE_KEY
    assert checkpoint.requester_service_principal is not None
    assert checkpoint.requester_user_id is None


def test_review_checkpoint_public_rejects_service_principal_without_summary() -> None:
    payload = _review_checkpoint_public_payload()
    payload["requester_service_principal"] = None

    with pytest.raises(ValidationError, match="requester service principal"):
        FlowRunReviewCheckpointPublic.model_validate(payload)


def test_review_checkpoint_public_rejects_mixed_requester_actor_shape() -> None:
    payload = _review_checkpoint_public_payload()
    payload["requester_principal_type"] = PrincipalType.USER
    payload["requester_user_id"] = uuid4()

    with pytest.raises(ValidationError, match="requester user principal"):
        FlowRunReviewCheckpointPublic.model_validate(payload)


def test_review_checkpoint_evidence_rejects_mismatched_decider_actor_shape() -> None:
    payload = _review_checkpoint_evidence_payload()
    payload["decided_by_principal_type"] = PrincipalType.SERVICE_KEY
    payload["decided_by_user_id"] = uuid4()

    with pytest.raises(ValidationError, match="decider service principal"):
        FlowRunReviewCheckpointEvidencePublic.model_validate(payload)


def test_review_lifecycle_audit_vocabulary_is_explicit() -> None:
    review_actions = {
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EDITED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_APPROVED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_REJECTED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_RESUMED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED,
    }

    assert EntityType.FLOW_RUN_REVIEW_CHECKPOINT.value == "flow_run_review_checkpoint"
    assert {
        FlowRunLifecycleSource.REVIEW_REJECTED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_EDITED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_APPROVED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_REJECTED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_RESUMED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_CANCELLED.value,
    }.issubset({item.value for item in FlowRunLifecycleSource})
    assert {CATEGORY_MAPPINGS[action.value] for action in review_actions} == {
        "user_actions"
    }
