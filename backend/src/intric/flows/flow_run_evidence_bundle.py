from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, cast

from intric.flows.domain.flow import (
    FlowRun,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from intric.flows.flow_run_evidence import build_debug_export
from intric.flows.flow_run_provenance import (
    FlowAttemptProvenance,
    FlowAttemptProvenanceParseResult,
    normalize_model_parameters_payload,
    parse_attempt_provenance,
)
from intric.flows.flow_run_redaction import MaskedField, redact_payload_with_manifest


@dataclass(frozen=True)
class EvidenceBundlePayload:
    payload: dict[str, Any]
    provenance_parse_results: tuple[FlowAttemptProvenanceParseResult, ...]


@dataclass(frozen=True)
class EvidenceBundle:
    run: FlowRun
    version: FlowVersion
    step_results: Sequence[FlowStepResult]
    step_attempts: Sequence[FlowStepAttempt]
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
                "definition_snapshot": self.version.definition_json,
                "step_results": [
                    _dump_result_record(item) for item in self.step_results
                ],
                "step_attempts": step_attempts,
                "debug_export": dict(self.debug_export),
            },
            provenance_parse_results=tuple(provenance_parse_results),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.to_export_payload().payload


@dataclass(frozen=True)
class RedactedEvidenceBundle:
    run: dict[str, Any]
    definition_snapshot: dict[str, Any]
    step_results: tuple[dict[str, Any], ...]
    step_attempts: tuple[dict[str, Any], ...]
    debug_export: dict[str, Any]
    masked_paths: tuple[str, ...]
    masked_fields: tuple[MaskedField, ...]
    provenance_parse_results: tuple[FlowAttemptProvenanceParseResult, ...] = ()

    def to_export_payload(self) -> EvidenceBundlePayload:
        return EvidenceBundlePayload(
            payload={
                "run": dict(self.run),
                "definition_snapshot": dict(self.definition_snapshot),
                "step_results": [dict(item) for item in self.step_results],
                "step_attempts": [dict(item) for item in self.step_attempts],
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
) -> EvidenceBundle:
    return EvidenceBundle(
        run=run,
        version=version,
        step_results=tuple(step_results),
        step_attempts=tuple(step_attempts),
        debug_export=build_debug_export(
            run=run,
            version=version,
            step_results=list(step_results),
            step_attempts=list(step_attempts),
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
    step_result_payloads: list[dict[str, Any]] = []
    for index, item in enumerate(bundle.step_results):
        result = redact_payload_with_manifest(
            _dump_result_record(item),
            path=f"bundle.step_results[{index}]",
        )
        step_result_payloads.append(cast(dict[str, Any], result.value))
        masked_paths.extend(result.masked_paths)
        masked_fields.extend(result.masked_fields)
    step_attempt_payloads: list[dict[str, Any]] = []
    provenance_parse_results: list[FlowAttemptProvenanceParseResult] = []
    for index, item in enumerate(bundle.step_attempts):
        dumped_attempt, parse_result = _dump_attempt_record(item)
        result = redact_payload_with_manifest(
            dumped_attempt,
            path=f"bundle.step_attempts[{index}]",
        )
        step_attempt_payloads.append(cast(dict[str, Any], result.value))
        provenance_parse_results.append(parse_result)
        masked_paths.extend(result.masked_paths)
        masked_fields.extend(result.masked_fields)
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
        definition_snapshot=cast(dict[str, Any], definition_result.value),
        step_results=tuple(step_result_payloads),
        step_attempts=tuple(step_attempt_payloads),
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


def _dump_result_record(item: FlowStepResult) -> dict[str, Any]:
    return item.model_dump(mode="json", exclude={"tool_calls_metadata"})


def _dump_attempt_record(
    item: FlowStepAttempt,
) -> tuple[dict[str, Any], FlowAttemptProvenanceParseResult]:
    dumped = item.model_dump(mode="json")
    parse_result = parse_attempt_provenance(item.provenance_json)
    export_provenance = _enrich_attempt_provenance_for_export(
        parse_result.provenance,
        item,
    )
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
