from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence, cast
from uuid import UUID

from eneo.flows.api.flow_run_contract_models import FlowFinalOutputContractPublic
from eneo.flows.application.flow_run_evidence import build_debug_export
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunReviewCheckpoint,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from eneo.flows.domain.provider_call import ProviderCallEvidencePage
from eneo.flows.enums import FlowRunReviewCheckpointState
from eneo.flows.flow_run_contract_service import build_final_output_contract
from eneo.flows.flow_run_provenance import (
    FlowAttemptProvenance,
    FlowAttemptProvenanceParseResult,
    normalize_model_parameters_payload,
    parse_attempt_provenance,
)
from eneo.flows.flow_run_redaction import MaskedField, redact_payload_with_manifest
from eneo.flows.flow_run_step_input_file import FlowRunStepInputFileMetadata
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRead,
)
from eneo.flows.published_definition import (
    PublishedDefinitionIntegrity,
    PublishedDefinitionIntegrityStatus,
    inspect_published_definition_integrity,
    parse_verified_published_definition,
)
from eneo.json_types import JsonObject, JsonValue

_REVIEW_CHECKPOINT_FIELDS_EXCLUDED_FROM_EXPORT = {
    "next_step_ids_json",
    "output_contract_json",
    "resume_idempotency_key",
}


@dataclass(frozen=True)
class EvidenceBundlePayload:
    payload: dict[str, Any]
    provenance_parse_results: tuple[FlowAttemptProvenanceParseResult, ...]


@dataclass(frozen=True)
class RedactedEvidenceSection:
    records: tuple[dict[str, Any], ...]
    masked_paths: tuple[str, ...]
    masked_fields: tuple[MaskedField, ...]


@dataclass(frozen=True)
class EvidenceBundle:
    run: FlowRun
    version: FlowVersion
    definition_integrity: PublishedDefinitionIntegrity
    final_output: FlowFinalOutputContractPublic | None
    step_results: Sequence[FlowStepResult]
    step_attempts: Sequence[FlowStepAttempt]
    result_files: Sequence[FlowRunStepResultFile]
    rerun_operations: Sequence[FlowRunRerunOperation]
    rerun_invalidated_steps: Sequence[FlowRunRerunInvalidatedStep]
    review_checkpoints: Sequence[FlowRunReviewCheckpoint]
    webhook_deliveries: Sequence[FlowRunWebhookDeliveryRead]
    provider_calls: ProviderCallEvidencePage
    runtime_input_file_ids_by_step_result_id: Mapping[UUID, Sequence[UUID]]
    runtime_input_file_metadata_by_step_result_id: Mapping[
        UUID, Sequence[FlowRunStepInputFileMetadata]
    ]
    debug_export: dict[str, Any]

    def to_export_payload(self) -> EvidenceBundlePayload:
        step_attempts: list[dict[str, Any]] = []
        provenance_parse_results: list[FlowAttemptProvenanceParseResult] = []
        for item in self.step_attempts:
            dumped, parse_result = _dump_attempt_record(item)
            step_attempts.append(dumped)
            provenance_parse_results.append(parse_result)
        return EvidenceBundlePayload(
            payload={
                "run": self.run.model_dump(mode="json"),
                "definition_integrity": self.definition_integrity.to_dict(),
                "definition_snapshot": self.version.definition_json,
                "step_results": [
                    _dump_result_record(
                        item,
                        runtime_input_file_ids=_runtime_input_file_ids_for_result(
                            item,
                            self.runtime_input_file_ids_by_step_result_id,
                        ),
                        runtime_input_file_metadata=(
                            _runtime_input_file_metadata_for_result(
                                item,
                                self.runtime_input_file_metadata_by_step_result_id,
                            )
                        ),
                    )
                    for item in self.step_results
                ],
                "step_attempts": step_attempts,
                "result_files": [
                    item.model_dump(mode="json") for item in self.result_files
                ],
                "rerun_operations": [
                    item.model_dump(mode="json") for item in self.rerun_operations
                ],
                "rerun_invalidated_steps": [
                    item.model_dump(mode="json")
                    for item in self.rerun_invalidated_steps
                ],
                "review_checkpoints": [
                    _dump_review_checkpoint_record(item)
                    for item in self.review_checkpoints
                ],
                "webhook_deliveries": [
                    _dump_webhook_delivery(item) for item in self.webhook_deliveries
                ],
                "provider_calls": self.provider_calls.model_dump(mode="json"),
                "debug_export": dict(self.debug_export),
            },
            provenance_parse_results=tuple(provenance_parse_results),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.to_export_payload().payload


@dataclass(frozen=True)
class RedactedEvidenceBundle:
    run: dict[str, Any]
    definition_integrity: PublishedDefinitionIntegrity
    final_output: FlowFinalOutputContractPublic | None
    definition_snapshot: dict[str, Any]
    step_results: tuple[dict[str, Any], ...]
    step_attempts: tuple[dict[str, Any], ...]
    result_files: tuple[dict[str, Any], ...]
    rerun_operations: tuple[dict[str, Any], ...]
    rerun_invalidated_steps: tuple[dict[str, Any], ...]
    review_checkpoints: tuple[dict[str, Any], ...]
    webhook_deliveries: tuple[dict[str, Any], ...]
    provider_calls: ProviderCallEvidencePage
    debug_export: dict[str, Any]
    masked_paths: tuple[str, ...]
    masked_fields: tuple[MaskedField, ...]
    provenance_parse_results: tuple[FlowAttemptProvenanceParseResult, ...] = ()

    def to_export_payload(self) -> EvidenceBundlePayload:
        return EvidenceBundlePayload(
            payload={
                "run": dict(self.run),
                "definition_integrity": self.definition_integrity.to_dict(),
                "definition_snapshot": dict(self.definition_snapshot),
                "step_results": [dict(item) for item in self.step_results],
                "step_attempts": [dict(item) for item in self.step_attempts],
                "result_files": [dict(item) for item in self.result_files],
                "rerun_operations": [dict(item) for item in self.rerun_operations],
                "rerun_invalidated_steps": [
                    dict(item) for item in self.rerun_invalidated_steps
                ],
                "review_checkpoints": [dict(item) for item in self.review_checkpoints],
                "webhook_deliveries": [dict(item) for item in self.webhook_deliveries],
                "provider_calls": self.provider_calls.model_dump(mode="json"),
                "debug_export": dict(self.debug_export),
            },
            provenance_parse_results=self.provenance_parse_results,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.to_export_payload().payload


def build_evidence_bundle(
    *,
    run: FlowRun,
    version: FlowVersion,
    step_results: Sequence[FlowStepResult],
    step_attempts: Sequence[FlowStepAttempt],
    result_files: Sequence[FlowRunStepResultFile] = (),
    rerun_operations: Sequence[FlowRunRerunOperation] = (),
    rerun_invalidated_steps: Sequence[FlowRunRerunInvalidatedStep] = (),
    review_checkpoints: Sequence[FlowRunReviewCheckpoint] = (),
    webhook_deliveries: Sequence[FlowRunWebhookDeliveryRead] = (),
    provider_calls: ProviderCallEvidencePage | None = None,
    runtime_input_file_ids_by_step_result_id: Mapping[UUID, Sequence[UUID]]
    | None = None,
    runtime_input_file_metadata_by_step_result_id: Mapping[
        UUID, Sequence[FlowRunStepInputFileMetadata]
    ]
    | None = None,
) -> EvidenceBundle:
    resolved_runtime_input_file_metadata_by_step_result_id = (
        runtime_input_file_metadata_by_step_result_id or {}
    )
    resolved_runtime_input_file_ids_by_step_result_id = (
        runtime_input_file_ids_by_step_result_id
        or {
            step_result_id: tuple(file_metadata.file_id for file_metadata in files)
            for step_result_id, files in (
                resolved_runtime_input_file_metadata_by_step_result_id.items()
            )
        }
    )
    definition_integrity = inspect_published_definition_integrity(
        version.definition_json,
        expected_checksum=version.definition_checksum,
        flow_version=version.version,
    )
    final_output = None
    if definition_integrity.status is PublishedDefinitionIntegrityStatus.VERIFIED:
        definition = parse_verified_published_definition(
            version.definition_json,
            expected_checksum=version.definition_checksum,
            flow_version=version.version,
        )
        final_output = build_final_output_contract(definition.runtime_steps())
    return EvidenceBundle(
        run=run,
        version=version,
        definition_integrity=definition_integrity,
        final_output=final_output,
        step_results=tuple(step_results),
        step_attempts=tuple(step_attempts),
        result_files=tuple(result_files),
        rerun_operations=tuple(rerun_operations),
        rerun_invalidated_steps=tuple(rerun_invalidated_steps),
        review_checkpoints=tuple(review_checkpoints),
        webhook_deliveries=tuple(webhook_deliveries),
        provider_calls=provider_calls
        or ProviderCallEvidencePage(
            items=(),
            count=0,
            total_count=0,
            has_more=False,
            next_after_event_id=None,
        ),
        runtime_input_file_ids_by_step_result_id=(
            resolved_runtime_input_file_ids_by_step_result_id
        ),
        runtime_input_file_metadata_by_step_result_id=(
            resolved_runtime_input_file_metadata_by_step_result_id
        ),
        debug_export=build_debug_export(
            run=run,
            version=version,
            step_results=list(step_results),
            step_attempts=list(step_attempts),
            result_files=list(result_files),
            rerun_operations=list(rerun_operations),
            rerun_invalidated_steps=list(rerun_invalidated_steps),
        ),
    )


def redact_evidence_bundle(bundle: EvidenceBundle) -> RedactedEvidenceBundle:
    masked_paths: list[str] = []
    masked_fields: list[MaskedField] = []
    run_result = redact_payload_with_manifest(
        bundle.run.model_dump(mode="json"),
        path="bundle.run",
    )
    definition_result = redact_payload_with_manifest(
        bundle.version.definition_json,
        path="bundle.definition_snapshot",
    )
    step_result_section = _redact_record_payloads(
        section_path="bundle.step_results",
        payloads=[
            _dump_result_record(
                result,
                runtime_input_file_ids=_runtime_input_file_ids_for_result(
                    result,
                    bundle.runtime_input_file_ids_by_step_result_id,
                ),
                runtime_input_file_metadata=_runtime_input_file_metadata_for_result(
                    result,
                    bundle.runtime_input_file_metadata_by_step_result_id,
                ),
            )
            for result in bundle.step_results
        ],
    )
    masked_paths.extend(step_result_section.masked_paths)
    masked_fields.extend(step_result_section.masked_fields)

    dumped_attempt_payloads: list[dict[str, Any]] = []
    provenance_parse_results: list[FlowAttemptProvenanceParseResult] = []
    for step_attempt in bundle.step_attempts:
        dumped_attempt, parse_result = _dump_attempt_record(step_attempt)
        dumped_attempt_payloads.append(dumped_attempt)
        provenance_parse_results.append(parse_result)
    step_attempt_section = _redact_record_payloads(
        section_path="bundle.step_attempts",
        payloads=dumped_attempt_payloads,
    )
    masked_paths.extend(step_attempt_section.masked_paths)
    masked_fields.extend(step_attempt_section.masked_fields)

    result_file_section = _redact_record_payloads(
        section_path="bundle.result_files",
        payloads=[
            result_file.model_dump(mode="json") for result_file in bundle.result_files
        ],
    )
    masked_paths.extend(result_file_section.masked_paths)
    masked_fields.extend(result_file_section.masked_fields)

    rerun_operation_section = _redact_record_payloads(
        section_path="bundle.rerun_operations",
        payloads=[
            rerun_operation.model_dump(mode="json")
            for rerun_operation in bundle.rerun_operations
        ],
    )
    masked_paths.extend(rerun_operation_section.masked_paths)
    masked_fields.extend(rerun_operation_section.masked_fields)

    rerun_invalidated_step_section = _redact_record_payloads(
        section_path="bundle.rerun_invalidated_steps",
        payloads=[
            invalidated_step.model_dump(mode="json")
            for invalidated_step in bundle.rerun_invalidated_steps
        ],
    )
    masked_paths.extend(rerun_invalidated_step_section.masked_paths)
    masked_fields.extend(rerun_invalidated_step_section.masked_fields)

    review_checkpoint_section = _redact_record_payloads(
        section_path="bundle.review_checkpoints",
        payloads=[
            _dump_review_checkpoint_record(checkpoint)
            for checkpoint in bundle.review_checkpoints
        ],
    )
    masked_paths.extend(review_checkpoint_section.masked_paths)
    masked_fields.extend(review_checkpoint_section.masked_fields)

    debug_result = redact_payload_with_manifest(
        bundle.debug_export, path="bundle.debug_export"
    )
    debug_export = cast(dict[str, Any], debug_result.value)
    security = debug_export.get("security")
    if isinstance(security, dict):
        security["redaction_applied"] = True
        security["masked_fields_count"] = len(
            tuple(run_result.masked_paths)
            + tuple(definition_result.masked_paths)
            + tuple(masked_paths)
            + tuple(debug_result.masked_paths)
        )
    return RedactedEvidenceBundle(
        run=cast(dict[str, Any], run_result.value),
        definition_integrity=bundle.definition_integrity,
        final_output=bundle.final_output,
        definition_snapshot=cast(dict[str, Any], definition_result.value),
        step_results=step_result_section.records,
        step_attempts=step_attempt_section.records,
        result_files=result_file_section.records,
        rerun_operations=rerun_operation_section.records,
        rerun_invalidated_steps=rerun_invalidated_step_section.records,
        review_checkpoints=review_checkpoint_section.records,
        webhook_deliveries=tuple(
            _dump_webhook_delivery(item) for item in bundle.webhook_deliveries
        ),
        provider_calls=bundle.provider_calls,
        debug_export=debug_export,
        masked_paths=tuple(
            dict.fromkeys(
                tuple(run_result.masked_paths)
                + tuple(definition_result.masked_paths)
                + tuple(masked_paths)
                + tuple(debug_result.masked_paths)
            )
        ),
        masked_fields=tuple(
            dict.fromkeys(
                tuple(run_result.masked_fields)
                + tuple(definition_result.masked_fields)
                + tuple(masked_fields)
                + tuple(debug_result.masked_fields)
            )
        ),
        provenance_parse_results=tuple(provenance_parse_results),
    )


def _redact_record_payloads(
    *,
    section_path: str,
    payloads: Sequence[dict[str, Any]],
) -> RedactedEvidenceSection:
    redacted_records: list[dict[str, Any]] = []
    masked_paths: list[str] = []
    masked_fields: list[MaskedField] = []
    for index, record_payload in enumerate(payloads):
        result = redact_payload_with_manifest(
            record_payload,
            path=f"{section_path}[{index}]",
        )
        redacted_records.append(cast(dict[str, Any], result.value))
        masked_paths.extend(result.masked_paths)
        masked_fields.extend(result.masked_fields)
    return RedactedEvidenceSection(
        records=tuple(redacted_records),
        masked_paths=tuple(masked_paths),
        masked_fields=tuple(masked_fields),
    )


def _runtime_input_file_ids_for_result(
    item: FlowStepResult,
    file_ids_by_step_result_id: Mapping[UUID, Sequence[UUID]],
) -> Sequence[UUID]:
    result_id = item.id
    if result_id is None:
        return ()
    return file_ids_by_step_result_id.get(result_id, ())


def _runtime_input_file_metadata_for_result(
    item: FlowStepResult,
    metadata_by_step_result_id: Mapping[UUID, Sequence[FlowRunStepInputFileMetadata]],
) -> Sequence[FlowRunStepInputFileMetadata]:
    result_id = item.id
    if result_id is None:
        return ()
    return metadata_by_step_result_id.get(result_id, ())


def _dump_result_record(
    item: FlowStepResult,
    *,
    runtime_input_file_ids: Sequence[UUID] = (),
    runtime_input_file_metadata: Sequence[FlowRunStepInputFileMetadata] = (),
) -> dict[str, Any]:
    dumped = item.model_dump(mode="json")
    runtime_input_file_id_strings = [str(file_id) for file_id in runtime_input_file_ids]
    dumped["runtime_input_file_ids"] = runtime_input_file_id_strings
    _normalize_dumped_runtime_input_files(
        dumped,
        runtime_input_file_ids=runtime_input_file_id_strings,
        runtime_input_file_metadata=runtime_input_file_metadata,
    )
    return dumped


def _normalize_dumped_runtime_input_files(
    dumped: dict[str, Any],
    *,
    runtime_input_file_ids: Sequence[str],
    runtime_input_file_metadata: Sequence[FlowRunStepInputFileMetadata],
) -> None:
    raw_input_payload = dumped.get("input_payload_json")
    if not isinstance(raw_input_payload, dict):
        return
    input_payload = cast(JsonObject, raw_input_payload)
    raw_runtime_input = input_payload.get("runtime_input")
    if not isinstance(raw_runtime_input, dict):
        return

    runtime_files: list[JsonValue] = [
        file_metadata.to_runtime_input_file_payload()
        for file_metadata in runtime_input_file_metadata
    ]
    normalized_runtime_input: JsonObject = dict(raw_runtime_input)
    normalized_runtime_input["file_ids"] = list(runtime_input_file_ids)
    normalized_runtime_input["files"] = runtime_files
    normalized_runtime_input["files_count"] = len(runtime_input_file_ids)
    if "total_file_size" in normalized_runtime_input:
        normalized_runtime_input["total_file_size"] = sum(
            file_metadata.size for file_metadata in runtime_input_file_metadata
        )
    normalized_payload: JsonObject = dict(input_payload)
    normalized_payload["runtime_input"] = normalized_runtime_input
    dumped["input_payload_json"] = normalized_payload


def _dump_review_checkpoint_record(item: FlowRunReviewCheckpoint) -> dict[str, Any]:
    dumped = item.model_dump(
        mode="json", exclude=_REVIEW_CHECKPOINT_FIELDS_EXCLUDED_FROM_EXPORT
    )
    dumped["decision"] = _review_checkpoint_decision(item)
    dumped["output_contract"] = item.output_contract_json
    dumped["next_step_ids"] = (
        [str(step_id) for step_id in item.next_step_ids_json]
        if item.next_step_ids_json is not None
        else None
    )
    dumped["resume_key_present"] = item.resume_idempotency_key is not None
    return dumped


def _dump_webhook_delivery(item: FlowRunWebhookDeliveryRead) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "step_id": str(item.step_id),
        "step_order": item.step_order,
        "attempt_no": item.attempt_no,
        "delivery_status": item.delivery_status.value,
        "delivery_attempts": item.delivery_attempts,
        "next_delivery_at": (
            item.next_delivery_at.isoformat()
            if item.next_delivery_at is not None
            else None
        ),
        "delivered_at": (
            item.delivered_at.isoformat() if item.delivered_at is not None else None
        ),
        "dead_lettered_at": (
            item.dead_lettered_at.isoformat()
            if item.dead_lettered_at is not None
            else None
        ),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _review_checkpoint_decision(item: FlowRunReviewCheckpoint) -> str | None:
    """Resumed checkpoints keep the reviewer decision separate from run re-entry."""
    if item.state in (
        FlowRunReviewCheckpointState.APPROVED,
        FlowRunReviewCheckpointState.RESUMED,
    ):
        return "approved"
    if item.state == FlowRunReviewCheckpointState.REJECTED:
        return "rejected"
    if item.state == FlowRunReviewCheckpointState.CANCELLED:
        return "cancelled"
    return None


def _dump_attempt_record(
    item: FlowStepAttempt,
) -> tuple[dict[str, Any], FlowAttemptProvenanceParseResult]:
    dumped = item.model_dump(mode="json")
    parse_result = parse_attempt_provenance(item.provenance_json)
    export_provenance = _enrich_attempt_provenance_for_export(
        parse_result.provenance,
        item,
    )
    if export_provenance is not None and export_provenance.token_usage is not None:
        # Historical provider-call receipts remain in JSONB only as migration and
        # rollback material. The relational provider_calls projection is the sole
        # public lifecycle authority after the cutover.
        export_provenance = export_provenance.model_copy(update={"token_usage": None})
    dumped["provenance_json"] = (
        export_provenance.to_payload()
        if export_provenance is not None
        else parse_result.to_export_payload()
    )
    if dumped.get("provider") is None and export_provenance is not None:
        model_parameters = (
            export_provenance.llm.model_parameters
            if export_provenance.llm is not None
            else None
        )
        if isinstance(model_parameters, dict):
            raw_provider = model_parameters.get("provider")
            if isinstance(raw_provider, str) and raw_provider.strip():
                dumped["provider"] = raw_provider.strip()
    return dumped, parse_result


def _enrich_attempt_provenance_for_export(
    provenance: FlowAttemptProvenance | None,
    item: FlowStepAttempt,
) -> FlowAttemptProvenance | None:
    if provenance is None or provenance.llm is None:
        return provenance
    llm_payload = provenance.llm
    model_parameters = llm_payload.model_parameters
    if not isinstance(model_parameters, dict):
        model_parameters = {}
    model_parameters = {
        **model_parameters,
        "model_name": model_parameters.get("model_name")
        or item.response_model
        or item.requested_model,
        "provider": model_parameters.get("provider") or item.provider,
    }
    return provenance.model_copy(
        update={
            "llm": llm_payload.model_copy(
                update={
                    "model_parameters": normalize_model_parameters_payload(
                        model_parameters
                    )
                }
            )
        }
    )
