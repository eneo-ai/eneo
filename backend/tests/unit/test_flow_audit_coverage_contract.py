from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from eneo.audit.domain.action_types import ActionType
from tests.unit.api_key_test_utils import runtime_app_routes


class AuditAssurance(str, Enum):
    REQUIRED_TRANSACTION = "required_transaction"
    REQUIRED_BEFORE_RESPONSE = "required_before_response"
    CONFIGURABLE_ASYNC = "configurable_async"
    BEST_EFFORT_OPERATIONAL = "best_effort_operational"
    AUTHORIZED_READ_NO_AUDIT = "authorized_read_no_audit"
    NO_BUSINESS_EVENT = "no_business_event"


@dataclass(frozen=True, slots=True)
class FlowAuditContract:
    actions: tuple[ActionType, ...]
    owner: str
    assurance: AuditAssurance
    actor: str
    outcome: str
    metadata_keys: tuple[str, ...]
    idempotency: str
    failure: str


def _configurable(
    action: ActionType,
    *,
    owner: str,
    metadata_keys: tuple[str, ...],
) -> FlowAuditContract:
    return FlowAuditContract(
        actions=(action,),
        owner=owner,
        assurance=AuditAssurance.CONFIGURABLE_ASYNC,
        actor="authenticated user or API-key principal",
        outcome="successful request",
        metadata_keys=metadata_keys,
        idempotency="one event per accepted request; retries may be distinct actions",
        failure="configuration or queue failure does not roll back the request",
    )


def _required_transaction(
    actions: ActionType | tuple[ActionType, ...],
    *,
    owner: str,
    metadata_keys: tuple[str, ...],
    idempotency: str,
) -> FlowAuditContract:
    normalized_actions = actions if isinstance(actions, tuple) else (actions,)
    return FlowAuditContract(
        actions=normalized_actions,
        owner=owner,
        assurance=AuditAssurance.REQUIRED_TRANSACTION,
        actor="authenticated user or API-key principal; system for worker transitions",
        outcome="committed state transition and its final outcome",
        metadata_keys=metadata_keys,
        idempotency=idempotency,
        failure="the protected state transition must not commit without its audit record",
    )


def _required_read(
    action: ActionType,
    *,
    owner: str,
    metadata_keys: tuple[str, ...],
) -> FlowAuditContract:
    return FlowAuditContract(
        actions=(action,),
        owner=owner,
        assurance=AuditAssurance.REQUIRED_BEFORE_RESPONSE,
        actor="authenticated user or API-key principal",
        outcome="authorized sensitive data access",
        metadata_keys=metadata_keys,
        idempotency="each successful access is a separate business event",
        failure=(
            "return 503 and expose no protected run content, evidence, package bytes, "
            "or signed URL"
        ),
    )


def _no_business_event(*, owner: str) -> FlowAuditContract:
    return FlowAuditContract(
        actions=(),
        owner=owner,
        assurance=AuditAssurance.NO_BUSINESS_EVENT,
        actor="authenticated principal",
        outcome="side-effect-free validation or planning response",
        metadata_keys=(),
        idempotency="safe to repeat because no durable business state changes",
        failure="normal typed request error; package bytes are never copied to audit logs",
    )


def _authorized_read(*, owner: str, outcome: str) -> FlowAuditContract:
    return FlowAuditContract(
        actions=(),
        owner=owner,
        assurance=AuditAssurance.AUTHORIZED_READ_NO_AUDIT,
        actor="authenticated user or API-key principal",
        outcome=outcome,
        metadata_keys=(),
        idempotency="safe to repeat; no audit event is emitted",
        failure="normal typed authorization or request error",
    )


_SETTING_METADATA = ("setting", "changes")
_FLOW_METADATA = ("flow_id", "space_id")
_RUN_METADATA = ("flow_id", "run_id", "revision")
_FILE_METADATA = ("flow_id", "file_id", "mimetype", "size_bytes")


FLOW_ROUTE_AUDIT_CONTRACTS: dict[str, FlowAuditContract] = {
    **{
        operation_id: _authorized_read(
            owner=owner,
            outcome="authorized Flow definition or runtime-policy read",
        )
        for operation_id, owner in {
            "list_flows": "flow_authoring_router.list_flows",
            "get_flow": "flow_authoring_router.get_flow",
            "get_flow_assistant": "flow_assistant_router.get_flow_assistant",
            "get_published_flow_runtime": (
                "flow_authoring_router.get_published_flow_runtime"
            ),
            "get_flow_run_contract": "flow_upload_router.get_flow_run_contract",
            "list_flow_template_files": (
                "flow_template_router.list_flow_template_files"
            ),
            "inspect_flow_template": "flow_template_router.inspect_flow_template",
        }.items()
    },
    **{
        operation_id: _authorized_read(
            owner=owner,
            outcome=(
                "authorized operational run read; routine polling is not a distinct "
                "business event"
            ),
        )
        for operation_id, owner in {
            "get_flow_run_capacity": (
                "flow_run_lifecycle_router.get_flow_run_capacity"
            ),
            "get_flow_run_status_capabilities": (
                "flow_run_lifecycle_router.get_flow_run_status_capabilities"
            ),
            "list_flow_runs": "flow_run_lifecycle_router.list_flow_runs",
            "get_flow_run_status": "flow_run_lifecycle_router.get_flow_run_status",
            "get_flow_graph": "flow_run_steps_router.get_flow_graph",
        }.items()
    },
    **{
        operation_id: _authorized_read(
            owner=owner,
            outcome="authorized settings or retention-planning read",
        )
        for operation_id, owner in {
            "get_flow_input_limits": "flow_settings_router.get_flow_input_limits",
            "get_flow_document_render_limits": (
                "flow_settings_router.get_flow_document_render_limits"
            ),
            "get_flow_runtime_policy": ("flow_settings_router.get_flow_runtime_policy"),
            "get_mapped_execution_policy": (
                "flow_settings_router.get_mapped_execution_policy"
            ),
            "get_rag_evidence_policy": ("flow_settings_router.get_rag_evidence_policy"),
            "get_flow_evidence_policy": (
                "flow_settings_router.get_flow_evidence_policy"
            ),
            "get_flow_retention_policy": (
                "flow_settings_router.get_flow_retention_policy"
            ),
            "get_organization_flow_run_retention_policy": (
                "flow_run_retention_policy_router.get_organization_policy"
            ),
            "get_space_flow_run_retention_policy": (
                "flow_run_retention_policy_router.get_space_policy"
            ),
            "get_flow_run_retention_policy": (
                "flow_run_retention_policy_router.get_flow_policy"
            ),
            "list_organization_flow_run_retention_review_queue": (
                "flow_run_retention_policy_router.list_organization_review_queue"
            ),
            "list_space_flow_run_retention_review_queue": (
                "flow_run_retention_policy_router.list_space_review_queue"
            ),
            "list_flow_run_retention_review_queue": (
                "flow_run_retention_policy_router.list_flow_review_queue"
            ),
            "list_flow_run_retention_space_targets": (
                "flow_run_retention_policy_router.list_space_targets"
            ),
            "list_flow_run_retention_flow_targets": (
                "flow_run_retention_policy_router.list_flow_targets"
            ),
        }.items()
    },
    **{
        operation_id: _configurable(
            ActionType.TENANT_SETTINGS_UPDATED,
            owner="SettingService",
            metadata_keys=_SETTING_METADATA,
        )
        for operation_id in (
            "update_flow_input_limits",
            "update_flow_document_render_limits",
            "update_flow_runtime_policy",
            "update_mapped_execution_policy",
            "update_rag_evidence_policy",
            "update_flow_evidence_policy",
            "update_flow_retention_policy",
        )
    },
    **{
        operation_id: _required_transaction(
            ActionType.FLOW_RUN_RETENTION_POLICY_CHANGED,
            owner="FlowRunRetentionPolicyService",
            metadata_keys=(
                "scope",
                "scope_id",
                "previous_local_policy",
                "new_local_policy",
                "effective_policy",
                "effective_source",
            ),
            idempotency="an unchanged replacement emits no event",
        )
        for operation_id in (
            "replace_organization_flow_run_retention_policy",
            "replace_space_flow_run_retention_policy",
            "replace_flow_run_retention_policy",
        )
    },
    "create_flow": _configurable(
        ActionType.FLOW_CREATED,
        owner="flow_authoring_router.create_flow",
        metadata_keys=_FLOW_METADATA,
    ),
    "update_flow": _configurable(
        ActionType.FLOW_UPDATED,
        owner="flow_authoring_router.update_flow",
        metadata_keys=(*_FLOW_METADATA, "changed_fields"),
    ),
    "delete_flow": _configurable(
        ActionType.FLOW_DELETED,
        owner="flow_authoring_router.delete_flow",
        metadata_keys=_FLOW_METADATA,
    ),
    "publish_flow": _configurable(
        ActionType.FLOW_PUBLISHED,
        owner="flow_authoring_router.publish_flow",
        metadata_keys=(*_FLOW_METADATA, "published_version"),
    ),
    "unpublish_flow": _configurable(
        ActionType.FLOW_UNPUBLISHED,
        owner="flow_authoring_router.unpublish_flow",
        metadata_keys=_FLOW_METADATA,
    ),
    "create_flow_assistant": _configurable(
        ActionType.ASSISTANT_CREATED,
        owner="flow_assistant_router.create_flow_assistant",
        metadata_keys=("flow_id", "assistant_id", "origin"),
    ),
    "update_flow_assistant": _configurable(
        ActionType.ASSISTANT_UPDATED,
        owner="flow_assistant_router.update_flow_assistant",
        metadata_keys=("flow_id", "assistant_id", "origin"),
    ),
    "delete_flow_assistant": _configurable(
        ActionType.ASSISTANT_DELETED,
        owner="flow_assistant_router.delete_flow_assistant",
        metadata_keys=("flow_id", "assistant_id", "origin"),
    ),
    "upload_flow_template_file": _configurable(
        ActionType.FILE_UPLOADED,
        owner="flow_template_router.upload_flow_template_file",
        metadata_keys=(*_FILE_METADATA, "template_asset_id", "upload_purpose"),
    ),
    "delete_flow_template_file": _configurable(
        ActionType.FILE_DELETED,
        owner="flow_template_router.delete_flow_template_file",
        metadata_keys=(*_FILE_METADATA, "template_asset_id", "upload_purpose"),
    ),
    "generate_flow_template_signed_url": _required_read(
        ActionType.FILE_SIGNED_URL_MINTED,
        owner="flow_template_router.generate_flow_template_signed_url",
        metadata_keys=(
            "flow_id",
            "file_id",
            "template_asset_id",
            "download_purpose",
        ),
    ),
    "test_flow_http": FlowAuditContract(
        actions=(ActionType.FLOW_HTTP_OUTBOUND_CALL,),
        owner="flow_http_test_router.test_flow_http",
        assurance=AuditAssurance.BEST_EFFORT_OPERATIONAL,
        actor="authenticated Flow editor",
        outcome="HTTP test success or classified failure",
        metadata_keys=(
            "flow_id",
            "test_direction",
            "test_success",
            "status_code",
            "failure_code",
        ),
        idempotency="each test request is a separate external call",
        failure="audit failure cannot undo the completed external test call",
    ),
    "upload_flow_runtime_file": _required_transaction(
        ActionType.FILE_UPLOADED,
        owner="FlowRuntimeFileService._upload_with_policy",
        metadata_keys=(*_FILE_METADATA, "step_id", "upload_purpose"),
        idempotency="each accepted upload has a unique file identity",
    ),
    "delete_flow_runtime_file": _required_transaction(
        ActionType.FILE_DELETED,
        owner="flow_upload_router.delete_flow_runtime_file",
        metadata_keys=(*_FILE_METADATA, "file_type", "runtime_role"),
        idempotency="a repeated delete returns not found and emits no success event",
    ),
    "create_flow_run": _required_transaction(
        ActionType.FLOW_RUN_CREATED,
        owner="flow_run_lifecycle_router.create_flow_run",
        metadata_keys=_RUN_METADATA,
        idempotency="an Idempotency-Key replay returns the existing run without a duplicate event",
    ),
    "cancel_flow_run": _required_transaction(
        ActionType.FLOW_RUN_CANCELLED,
        owner="FlowRunTerminalizer and FlowRunAuditOutboxRepository",
        metadata_keys=(*_RUN_METADATA, "source", "target_status"),
        idempotency="terminal compare-and-set and unique run revision bound duplicates",
    ),
    "redispatch_flow_run": _required_transaction(
        ActionType.FLOW_RUN_REDISPATCHED,
        owner="flow_dispatch.redrive_flow_run_recoverably_after_commit",
        metadata_keys=(*_RUN_METADATA, "accepted_exhaustion_rearmed"),
        idempotency="the exhausted-dispatch generation prevents a stale duplicate redrive",
    ),
    **{
        operation_id: _required_transaction(
            action,
            owner="FlowRunReviewCheckpointRepository and FlowRunAuditOutboxRepository",
            metadata_keys=(*_RUN_METADATA, "checkpoint_id", "step_id", "source"),
            idempotency="checkpoint state compare-and-set and revision uniqueness bound duplicates",
        )
        for operation_id, action in {
            "edit_flow_run_review_checkpoint": (
                ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EDITED
            ),
            "approve_flow_run_review_checkpoint": (
                ActionType.FLOW_RUN_REVIEW_CHECKPOINT_APPROVED
            ),
            "reject_flow_run_review_checkpoint": (
                ActionType.FLOW_RUN_REVIEW_CHECKPOINT_REJECTED
            ),
            "resume_flow_run_review_checkpoint": (
                ActionType.FLOW_RUN_REVIEW_CHECKPOINT_RESUMED
            ),
        }.items()
    },
    "generate_flow_run_artifact_signed_url": _required_read(
        ActionType.FILE_SIGNED_URL_MINTED,
        owner="flow_run_steps_router.generate_flow_run_artifact_signed_url",
        metadata_keys=(
            *_FILE_METADATA,
            "run_id",
            "download_purpose",
            "artifact_name",
        ),
    ),
    "generate_flow_run_input_file_signed_url": _required_read(
        ActionType.FILE_SIGNED_URL_MINTED,
        owner="flow_run_steps_router.generate_flow_run_input_file_signed_url",
        metadata_keys=(
            *_FILE_METADATA,
            "run_id",
            "download_purpose",
            "content_disposition",
            "expires_in_seconds",
        ),
    ),
    "list_flow_run_steps": _required_read(
        ActionType.FLOW_EVIDENCE_VIEWED,
        owner="flow_run_steps_router.list_flow_run_steps",
        metadata_keys=("flow_id", "run_id", "evidence_detail"),
    ),
    "get_flow_run": _required_read(
        ActionType.FLOW_EVIDENCE_VIEWED,
        owner="flow_trace_audit.log_flow_trace_audit_or_raise",
        metadata_keys=("flow_id", "run_id", "evidence_detail"),
    ),
    "get_active_flow_run_review_checkpoint": _required_read(
        ActionType.FLOW_EVIDENCE_VIEWED,
        owner="flow_trace_audit.log_flow_trace_audit_or_raise",
        metadata_keys=(
            "flow_id",
            "run_id",
            "evidence_detail",
            "checkpoint_present",
        ),
    ),
    "get_flow_run_evidence": _required_read(
        ActionType.FLOW_EVIDENCE_VIEWED,
        owner="flow_trace_audit.log_flow_trace_audit_or_raise",
        metadata_keys=("flow_id", "run_id", "evidence_detail"),
    ),
    "list_flow_run_provider_calls": _required_read(
        ActionType.FLOW_EVIDENCE_VIEWED,
        owner="flow_trace_audit.log_flow_trace_audit_or_raise",
        metadata_keys=("flow_id", "run_id", "evidence_detail"),
    ),
    "export_flow_run_evidence": _required_read(
        ActionType.FLOW_EVIDENCE_EXPORTED_JSON,
        owner="flow_trace_audit.log_flow_trace_audit_or_raise",
        metadata_keys=("flow_id", "run_id", "detail", "reason"),
    ),
    "export_flow_package": _required_read(
        ActionType.FLOW_PACKAGE_EXPORTED,
        owner="flow_package_router.export_flow_package",
        metadata_keys=(
            "flow_id",
            "package_id",
            "package_version",
            "content_checksum",
            "requirements_count",
            "payload_size_bytes",
            "omissions",
        ),
    ),
    "import_flow_package_as_draft": _required_transaction(
        (
            ActionType.FLOW_PACKAGE_DRAFT_INSTALLED,
            ActionType.FLOW_PACKAGE_IMPORT_FAILED,
        ),
        owner="flow_package_router.import_flow_package_as_draft",
        metadata_keys=(
            "import_id",
            "space_id",
            "flow_id",
            "package_id",
            "package_version",
            "content_checksum",
            "failure_code",
        ),
        idempotency="the reviewed checksum, target state, and mapping decision identify replays",
    ),
    "validate_flow_package": _no_business_event(
        owner="flow_package_router.validate_flow_package"
    ),
    "create_flow_package_import_plan": _no_business_event(
        owner="flow_package_router.create_flow_package_import_plan"
    ),
}


FLOW_INTERNAL_AUDIT_CONTRACTS: dict[str, FlowAuditContract] = {
    "run_terminalization": _required_transaction(
        (
            ActionType.FLOW_RUN_COMPLETED,
            ActionType.FLOW_RUN_FAILED,
            ActionType.FLOW_RUN_CANCELLED,
        ),
        owner="FlowRunTerminalizer and FlowRunAuditOutboxRepository",
        metadata_keys=(*_RUN_METADATA, "source", "target_status"),
        idempotency="one outbox event per terminal run revision",
    ),
    "review_checkpoint_worker_transitions": _required_transaction(
        (
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED,
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED,
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EXPIRED,
        ),
        owner="FlowRunReviewCheckpointRepository and FlowRunAuditOutboxRepository",
        metadata_keys=(*_RUN_METADATA, "checkpoint_id", "step_id", "source"),
        idempotency="one outbox event per checkpoint and run revision",
    ),
    "outbound_http": FlowAuditContract(
        actions=(ActionType.FLOW_HTTP_OUTBOUND_CALL,),
        owner="runtime.http_audit plus persisted step/attempt or webhook-delivery state",
        assurance=AuditAssurance.BEST_EFFORT_OPERATIONAL,
        actor="persisted run principal",
        outcome="HTTP status, duration, and classified failure",
        metadata_keys=(
            "flow_id",
            "run_id",
            "step_id",
            "call_type",
            "http_method",
            "url_host",
            "url_path",
            "status_code",
            "duration_ms",
        ),
        idempotency="runtime retry attempts are distinct; webhook delivery identity is durable",
        failure="admin audit is best effort; run step/attempt and webhook delivery state remain durable",
    ),
    "transcription": FlowAuditContract(
        actions=(ActionType.FLOW_RUN_AUDIO_TRANSCRIBED,),
        owner="transcription_runtime plus FlowProviderCallRecorder",
        assurance=AuditAssurance.BEST_EFFORT_OPERATIONAL,
        actor="persisted run principal",
        outcome="transcription success or classified provider outcome",
        metadata_keys=(
            "flow_id",
            "run_id",
            "step_id",
            "provider",
            "model",
            "audio_duration_seconds",
        ),
        idempotency="provider job identity prevents remote resubmission after an accepted call",
        failure="admin audit is best effort; FlowProviderCalls evidence is required and fail-closed",
    ),
    "future_run_history_purge": _required_transaction(
        ActionType.FLOW_RUN_HISTORY_PURGED,
        owner="future Flow purge service and FlowRunAuditOutboxRepository",
        metadata_keys=(
            "requester_id",
            "reason",
            "eligibility_snapshot_id",
            "eligible_run_count",
            "purged_run_count",
            "purged_bytes",
            "receipt_id",
            "correlation_id",
            "outcome",
        ),
        idempotency="receipt identity and purge command key prevent duplicate deletion events",
    ),
}


_FORBIDDEN_METADATA_KEYS = {
    "authorization",
    "credentials",
    "document_content",
    "prompt",
    "raw_provider_payload",
    "request_body",
    "response_body",
    "secret",
    "signed_url",
}


def _is_flow_contract_path(path: str) -> bool:
    if path.startswith("/api/v1/flows/ai-builder"):
        return False
    return (
        path.startswith("/api/v1/flows")
        or path.startswith("/api/v1/settings/flow-")
        or path.startswith("/api/v1/flow-packages/")
        or "/flow-packages/" in path
    )


def _flow_route_operation_ids() -> set[str]:
    operation_ids: set[str] = set()
    for route in runtime_app_routes():
        operation_id = getattr(route.route, "operation_id", None)
        if not operation_id or not _is_flow_contract_path(route.path):
            continue
        operation_ids.add(operation_id)
    return operation_ids


def test_every_significant_flow_route_has_an_audit_decision() -> None:
    assert set(FLOW_ROUTE_AUDIT_CONTRACTS) == _flow_route_operation_ids()


def test_flow_audit_contracts_name_owners_failure_modes_and_safe_metadata() -> None:
    for contract in (
        *FLOW_ROUTE_AUDIT_CONTRACTS.values(),
        *FLOW_INTERNAL_AUDIT_CONTRACTS.values(),
    ):
        assert contract.owner
        assert contract.actor
        assert contract.outcome
        assert contract.idempotency
        assert contract.failure
        assert not (_FORBIDDEN_METADATA_KEYS & set(contract.metadata_keys))
        if contract.assurance in {
            AuditAssurance.AUTHORIZED_READ_NO_AUDIT,
            AuditAssurance.NO_BUSINESS_EVENT,
        }:
            assert contract.actions == ()
        else:
            assert contract.actions


def test_outbound_and_transcription_keep_durable_evidence_below_admin_audit() -> None:
    outbound = FLOW_INTERNAL_AUDIT_CONTRACTS["outbound_http"]
    transcription = FLOW_INTERNAL_AUDIT_CONTRACTS["transcription"]

    assert outbound.assurance is AuditAssurance.BEST_EFFORT_OPERATIONAL
    assert "step/attempt" in outbound.failure
    assert transcription.assurance is AuditAssurance.BEST_EFFORT_OPERATIONAL
    assert "FlowProviderCalls" in transcription.failure


def test_future_purge_receipt_contract_is_ready_for_the_purge_workflow() -> None:
    purge = FLOW_INTERNAL_AUDIT_CONTRACTS["future_run_history_purge"]

    assert purge.actions == (ActionType.FLOW_RUN_HISTORY_PURGED,)
    assert purge.assurance is AuditAssurance.REQUIRED_TRANSACTION
    assert {
        "requester_id",
        "reason",
        "eligibility_snapshot_id",
        "eligible_run_count",
        "purged_run_count",
        "purged_bytes",
        "receipt_id",
        "outcome",
    }.issubset(purge.metadata_keys)
