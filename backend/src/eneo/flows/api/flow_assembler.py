from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError

from eneo.authentication.auth_models import FlowServicePrincipalActorPublic
from eneo.flows.api.flow_models import (
    FlowPublic,
    FlowRunDetailPublic,
    FlowRunPublic,
    FlowRunReviewCheckpointPublic,
    FlowRunStepPublic,
    FlowRunStepRerunResponse,
    FlowRunTokenUsagePublic,
    FlowRunWebhookDeliveryPublic,
    FlowSparsePublic,
    FlowStepCreateRequest,
    FlowStepDiagnosticPublic,
    FlowStepUpdateRequest,
)
from eneo.flows.api.flow_run_contract_models import (
    FlowFinalOutputContractPublic,
    FlowOutputDelivery,
    FlowRunArtifactResultPublic,
    FlowRunFileBackedTextResultPublic,
    FlowRunInlineTextResultPublic,
    FlowRunOutboundHttpResultPublic,
    FlowRunResultPublic,
    FlowRunStructuredResultPublic,
)
from eneo.flows.api.flow_runtime_paths import (
    FlowRuntimePublic,
    build_flow_runtime_paths,
)
from eneo.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunReviewCheckpoint,
    FlowRunTokenUsage,
    FlowSparse,
    FlowStep,
    FlowStepResult,
)
from eneo.flows.domain.step_output import (
    FileBackedStepText,
    StepOutputMetadataError,
    interpret_step_text,
)
from eneo.flows.enums import FlowOutputType, FlowRunStatus
from eneo.flows.flow_run_input_envelope import read_semantic_flow_input_payload
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.http_transport import (
    HttpAuthoredConfig,
    is_authored_config,
    redact_authored_config,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRead,
)

logger = logging.getLogger(__name__)
# Keep drift logs searchable without dumping arbitrary persisted payload keys.
_MAX_LOGGED_DIAGNOSTIC_ERROR_TYPES = 3
_MAX_LOGGED_DIAGNOSTIC_EXTRA_KEYS = 3
_PUBLIC_STEP_DIAGNOSTIC_FIELDS = frozenset(FlowStepDiagnosticPublic.model_fields)


class FlowAssembler:
    def to_domain_step(self, step: FlowStepCreateRequest) -> FlowStep:
        return self._to_domain_step_from_authoring_request(step, step_id=None)

    def to_domain_step_for_update(self, step: FlowStepUpdateRequest) -> FlowStep:
        return self._to_domain_step_from_authoring_request(step, step_id=step.id)

    def _to_domain_step_from_authoring_request(
        self, step: FlowStepCreateRequest, *, step_id: UUID | None
    ) -> FlowStep:
        return FlowStep(
            id=step_id,
            assistant_id=step.assistant_id,
            step_order=step.step_order,
            timeout_seconds=step.timeout_seconds,
            user_description=step.user_description,
            input_source=step.input_source,
            input_type=step.input_type,
            input_contract=step.input_contract,
            output_mode=step.output_mode,
            output_type=step.output_type,
            output_contract=step.output_contract,
            input_bindings=step.input_bindings,
            output_classification_override=step.output_classification_override,
            input_config=step.input_config,
            output_config=step.output_config,
            review_policy=step.review_policy,
        )

    def to_public(self, flow: Flow) -> FlowPublic:
        redacted = self._redact_step_configs(flow)
        return FlowPublic.model_validate(redacted)

    def to_sparse_public(self, flow: FlowSparse) -> FlowSparsePublic:
        return FlowSparsePublic.model_validate(flow)

    def to_runtime_public(
        self, flow: Flow, *, published_version: int, api_prefix: str
    ) -> FlowRuntimePublic:
        flow_id = flow.require_persisted_id()

        runtime_paths = build_flow_runtime_paths(flow_id, api_prefix=api_prefix)
        return FlowRuntimePublic(
            id=flow_id,
            space_id=flow.space_id,
            name=flow.name,
            description=flow.description,
            published_version=published_version,
            created_at=flow.created_at,
            updated_at=flow.updated_at,
            runtime_paths=runtime_paths,
        )

    @staticmethod
    def to_run_result_public(
        *,
        run: FlowRun,
        final_output: FlowFinalOutputContractPublic | None,
        result_files: Sequence[FlowRunStepResultFile] = (),
    ) -> FlowRunResultPublic | None:
        return _project_run_result(
            run=run,
            final_output=final_output,
            result_files=result_files,
        )

    def to_run_public(
        self,
        run: FlowRun,
        *,
        result_files: Sequence[FlowRunStepResultFile] = (),
        token_usage: FlowRunTokenUsage | None = None,
        final_output: FlowFinalOutputContractPublic | None = None,
    ) -> FlowRunPublic:
        public_token_usage = (
            FlowRunTokenUsagePublic.model_validate(token_usage)
            if token_usage is not None
            else None
        )
        return FlowRunPublic.model_validate(run).model_copy(
            update={
                "input_payload_json": read_semantic_flow_input_payload(
                    run.input_payload_json
                ),
                "result": self.to_run_result_public(
                    run=run,
                    final_output=final_output,
                    result_files=result_files,
                ),
                "result_files": list(result_files),
                "token_usage": public_token_usage,
            }
        )

    def to_run_detail_public(
        self,
        run: FlowRun,
        *,
        result_files: Sequence[FlowRunStepResultFile] = (),
        token_usage: FlowRunTokenUsage | None = None,
        final_output: FlowFinalOutputContractPublic | None = None,
        webhook_deliveries: Sequence[FlowRunWebhookDeliveryRead] = (),
    ) -> FlowRunDetailPublic:
        run_payload = self.to_run_public(
            run,
            result_files=result_files,
            token_usage=token_usage,
            final_output=final_output,
        ).model_dump()
        return FlowRunDetailPublic.model_validate(
            {
                **run_payload,
                "webhook_deliveries": [
                    FlowRunWebhookDeliveryPublic.model_validate(delivery)
                    for delivery in webhook_deliveries
                ],
            }
        )

    def to_step_public(
        self,
        result: FlowStepResult,
        *,
        runtime_input_file_ids: Sequence[UUID] = (),
        result_files: Sequence[FlowRunStepResultFile] = (),
    ) -> FlowRunStepPublic:
        return FlowRunStepPublic.model_validate(result).model_copy(
            update={
                "diagnostics": _project_step_diagnostics(result),
                "runtime_input_file_ids": list(runtime_input_file_ids),
                "result_files": list(result_files),
            }
        )

    def to_rerun_response(
        self,
        *,
        operation: FlowRunRerunOperation,
        run: FlowRun,
        invalidated_steps: Sequence[FlowRunRerunInvalidatedStep],
        result_files: Sequence[FlowRunStepResultFile] = (),
        token_usage: FlowRunTokenUsage | None = None,
        final_output: FlowFinalOutputContractPublic | None = None,
    ) -> FlowRunStepRerunResponse:
        return FlowRunStepRerunResponse(
            operation_id=operation.id,
            run=self.to_run_public(
                run,
                result_files=result_files,
                token_usage=token_usage,
                final_output=final_output,
            ),
            rerun_step_id=operation.rerun_step_id,
            new_attempt_no=operation.root_attempt_no,
            invalidated_step_ids=[step.step_id for step in invalidated_steps],
            status=operation.status,
        )

    def to_review_checkpoint_public(
        self,
        checkpoint: FlowRunReviewCheckpoint,
        *,
        requester_service_principal: FlowServicePrincipalActorPublic | None = None,
        decided_by_service_principal: FlowServicePrincipalActorPublic | None = None,
    ) -> FlowRunReviewCheckpointPublic:
        # Public API names omit persistence-only `_json` suffixes because every
        # response is already JSON-serialized; keep the suffix on domain fields
        # where it records the backing column convention.
        return FlowRunReviewCheckpointPublic.model_validate(
            {
                **checkpoint.model_dump(),
                "next_step_ids": checkpoint.next_step_ids_json,
                "output_contract": checkpoint.output_contract_json,
                "requester_service_principal": requester_service_principal,
                "decided_by_service_principal": decided_by_service_principal,
            }
        )

    @staticmethod
    def _redact_step_configs(flow: Flow) -> Flow:
        """Replace encrypted secrets with sentinel values in authored HTTP configs."""
        redacted_steps = [
            step.model_copy(
                update={
                    "input_config": _redact_config(step.input_config),
                    "output_config": _redact_config(step.output_config),
                },
                deep=True,
            )
            for step in flow.steps
        ]
        return flow.model_copy(update={"steps": redacted_steps}, deep=True)


class FlowRunResultProjectionError(RuntimeError):
    """Persisted completed-run data does not satisfy its published result contract."""


def _project_run_result(
    *,
    run: FlowRun,
    final_output: FlowFinalOutputContractPublic | None,
    result_files: Sequence[FlowRunStepResultFile],
) -> FlowRunResultPublic | None:
    if run.status is not FlowRunStatus.COMPLETED:
        return None
    if final_output is None:
        raise FlowRunResultProjectionError(
            "Completed run has no pinned final-output contract."
        )

    if final_output.delivery is FlowOutputDelivery.OUTBOUND_HTTP:
        return FlowRunOutboundHttpResultPublic(
            kind="outbound_http",
            delivery_status="delivered",
        )

    if final_output.delivery is FlowOutputDelivery.ARTIFACT:
        final_files = [
            result_file
            for result_file in result_files
            if result_file.step_id == final_output.step_id
        ]
        if not final_files:
            raise FlowRunResultProjectionError(
                "Completed artifact run has no current final-step artifact metadata."
            )
        return FlowRunArtifactResultPublic(kind="artifact", files=final_files)

    payload = run.output_payload_json
    if payload is None:
        raise FlowRunResultProjectionError(
            "Completed payload run has no terminal output payload."
        )
    if final_output.output_type is FlowOutputType.JSON:
        if "structured" not in payload:
            raise FlowRunResultProjectionError(
                "Completed structured run has no structured terminal value."
            )
        return FlowRunStructuredResultPublic(
            kind="structured",
            value=payload["structured"],
            output_contract=final_output.output_contract,
        )
    if final_output.output_type is FlowOutputType.TEXT:
        try:
            text = interpret_step_text(payload)
        except StepOutputMetadataError as exc:
            raise FlowRunResultProjectionError(
                "Completed text run has malformed persisted text metadata."
            ) from exc
        if isinstance(text, FileBackedStepText):
            matching_files = [
                result_file
                for result_file in result_files
                if result_file.flow_run_id == run.id
                and result_file.flow_id == run.flow_id
                and result_file.tenant_id == run.tenant_id
                and result_file.step_id == final_output.step_id
                and result_file.file_id == text.file_id
                and result_file.source == "generated_output"
            ]
            if len(matching_files) != 1:
                raise FlowRunResultProjectionError(
                    "Completed file-backed text run must have exactly one current "
                    "final-step generated output file."
                )
            return FlowRunFileBackedTextResultPublic(
                kind="file_backed_text",
                preview=text.preview,
                file=matching_files[0],
            )
        return FlowRunInlineTextResultPublic(kind="inline_text", text=text.text)
    raise FlowRunResultProjectionError(
        "Completed payload run has an unsupported published output type."
    )


def _redact_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if config is None or not is_authored_config(config):
        return config
    authored = HttpAuthoredConfig.model_validate(config)
    redacted = redact_authored_config(authored)
    return redacted.model_dump(mode="json")


def _project_step_diagnostics(
    result: FlowStepResult,
) -> list[FlowStepDiagnosticPublic]:
    input_payload = result.input_payload_json
    if not isinstance(input_payload, Mapping):
        return []

    raw_diagnostics_value = input_payload.get("diagnostics")
    if not isinstance(raw_diagnostics_value, list):
        return []
    raw_diagnostics = cast(list[object], raw_diagnostics_value)

    diagnostics: list[FlowStepDiagnosticPublic] = []
    dropped_count = 0
    trimmed_count = 0
    error_types: list[str] = []
    trimmed_keys: list[str] = []

    for raw_item in raw_diagnostics:
        if not isinstance(raw_item, Mapping):
            dropped_count += 1
            if len(error_types) < _MAX_LOGGED_DIAGNOSTIC_ERROR_TYPES:
                error_types.append("not_mapping")
            continue
        raw_mapping = cast(Mapping[Any, Any], raw_item)
        public_payload, extra_keys = _split_public_step_diagnostic_payload(raw_mapping)
        if extra_keys:
            trimmed_count += 1
            for key in extra_keys:
                if len(trimmed_keys) >= _MAX_LOGGED_DIAGNOSTIC_EXTRA_KEYS:
                    break
                trimmed_keys.append(key)
        try:
            diagnostics.append(FlowStepDiagnosticPublic.model_validate(public_payload))
        except ValidationError as exc:
            dropped_count += 1
            if len(error_types) < _MAX_LOGGED_DIAGNOSTIC_ERROR_TYPES:
                error_type = "validation_error"
                errors = exc.errors()
                if errors:
                    error_type = errors[0].get("type", "validation_error")
                error_types.append(error_type)

    if trimmed_count:
        logger.warning(
            "flow_step_diagnostics_projection_trimmed",
            extra={
                "run_id": str(result.flow_run_id),
                "step_id": str(result.step_id),
                "trimmed_count": trimmed_count,
                "trimmed_keys": trimmed_keys,
            },
        )

    if dropped_count:
        logger.warning(
            "flow_step_diagnostics_projection_dropped",
            extra={
                "run_id": str(result.flow_run_id),
                "step_id": str(result.step_id),
                "dropped_count": dropped_count,
                "error_types": error_types,
            },
        )

    return diagnostics


def _split_public_step_diagnostic_payload(
    raw_item: Mapping[Any, Any],
) -> tuple[dict[str, Any], list[str]]:
    public_payload: dict[str, Any] = {}
    extra_keys: list[str] = []
    for key, value in raw_item.items():
        if isinstance(key, str) and key in _PUBLIC_STEP_DIAGNOSTIC_FIELDS:
            public_payload[key] = value
        else:
            extra_keys.append(str(key))
    return public_payload, extra_keys
