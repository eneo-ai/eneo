from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, cast

from intric.flows.domain.flow import FlowRun, FlowStepAttempt, FlowStepResult, FlowVersion
from intric.flows.flow_run_evidence import build_debug_export
from intric.flows.flow_run_provenance import normalize_attempt_provenance
from intric.flows.flow_run_redaction import redact_payload


@dataclass(frozen=True)
class EvidenceBundle:
    run: FlowRun
    version: FlowVersion
    step_results: Sequence[FlowStepResult]
    step_attempts: Sequence[FlowStepAttempt]
    debug_export: dict[str, Any]


@dataclass(frozen=True)
class RedactedEvidenceBundle:
    run: dict[str, Any]
    definition_snapshot: dict[str, Any]
    step_results: tuple[dict[str, Any], ...]
    step_attempts: tuple[dict[str, Any], ...]
    debug_export: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": dict(self.run),
            "definition_snapshot": dict(self.definition_snapshot),
            "step_results": [dict(item) for item in self.step_results],
            "step_attempts": [dict(item) for item in self.step_attempts],
            "debug_export": dict(self.debug_export),
        }


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
    debug_export = cast(dict[str, Any], redact_payload(bundle.debug_export))
    security = debug_export.get("security")
    if isinstance(security, dict):
        security["redaction_applied"] = True
    return RedactedEvidenceBundle(
        run=cast(dict[str, Any], redact_payload(bundle.run.model_dump(mode="json"))),
        definition_snapshot=cast(
            dict[str, Any], redact_payload(bundle.version.definition_json)
        ),
        step_results=tuple(
            cast(dict[str, Any], redact_payload(_dump_json_record(item)))
            for item in bundle.step_results
        ),
        step_attempts=tuple(
            cast(dict[str, Any], redact_payload(_dump_json_record(item)))
            for item in bundle.step_attempts
        ),
        debug_export=debug_export,
    )


def _dump_json_record(item: FlowStepResult | FlowStepAttempt) -> dict[str, Any]:
    dumped = item.model_dump(mode="json")
    if isinstance(item, FlowStepAttempt):
        normalized_provenance = normalize_attempt_provenance(item.provenance_json)
        dumped["provenance_json"] = (
            normalized_provenance.to_payload()
            if normalized_provenance is not None
            else None
        )
    return {key: value for key, value in dumped.items()}
