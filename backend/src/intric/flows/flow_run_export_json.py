from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from intric.flows.citation_sidecar import build_citation_sidecar
from intric.flows.citation_sidecar import (
    TRACKING_MODE_INLINE_INREF_REQUIRED,
    TRACKING_MODE_PASSIVE_INLINE_SCAN,
    normalize_citation_sidecar_payload,
    resolve_citation_mode,
    summarize_step_citations,
)
from intric.flows.flow_run_evidence_bundle import RedactedEvidenceBundle
from intric.flows.flow_run_provenance import (
    default_rag_tracking,
    normalize_text_preview,
)
from intric.flows.source_display import (
    format_source_container_display_name,
    format_source_container_label,
    format_source_display_name,
)
from intric.flows.flow_run_redaction import REDACTION_POLICY_VERSION
from intric.flows.step_lineage import build_step_ref_mapping, resolve_upstream_step_orders
from intric.flows.template_reference_analyzer import analyze_template, consumes_runtime_input

EVIDENCE_EXPORT_SCHEMA_VERSION = "flow-evidence-export.v2"


def render_evidence_json_export(*, bundle: RedactedEvidenceBundle) -> dict[str, object]:
    bundle_payload = bundle.to_dict()
    serialized_bundle = json.dumps(
        bundle_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    content_hash = hashlib.sha256(serialized_bundle).hexdigest()
    manifest = _build_manifest(
        bundle_payload,
        content_hash,
        masked_fields_count=len(bundle.masked_paths),
    )
    return {
        "schema_version": EVIDENCE_EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "manifest": manifest,
        "summary": _build_summary(bundle_payload),
        "redaction": {
            "applied": bool(
                ((bundle_payload.get("debug_export") or {}).get("security") or {}).get(
                    "redaction_applied"
                )
            ),
            "policy_version": REDACTION_POLICY_VERSION,
            "masked_fields_count": len(bundle.masked_paths),
            "masked_paths": list(bundle.masked_paths),
            "masked_fields": [
                {
                    "path": field.path,
                    "key": field.key,
                    "reason": field.reason,
                }
                for field in bundle.masked_fields
            ],
        },
        "bundle": bundle_payload,
    }


def _build_manifest(
    bundle_payload: dict[str, Any],
    content_hash: str,
    *,
    masked_fields_count: int,
) -> dict[str, Any]:
    run = bundle_payload.get("run", {})
    debug_export = bundle_payload.get("debug_export", {})
    security = debug_export.get("security", {}) if isinstance(debug_export, dict) else {}
    return {
        "run_id": run.get("id"),
        "flow_id": run.get("flow_id"),
        "trace_id": run.get("trace_id"),
        "flow_version": run.get("flow_version"),
        "content_hash": content_hash,
        "redaction_applied": bool(security.get("redaction_applied")),
        "masked_fields_count": masked_fields_count,
        "redaction_policy_version": REDACTION_POLICY_VERSION,
    }


def _build_summary(bundle_payload: dict[str, Any]) -> dict[str, Any]:
    run = bundle_payload.get("run", {})
    step_results = bundle_payload.get("step_results", [])
    step_attempts = bundle_payload.get("step_attempts", [])
    debug_export = bundle_payload.get("debug_export", {})
    debug_run = debug_export.get("run", {}) if isinstance(debug_export, dict) else {}
    debug_summary = debug_run.get("summary", {}) if isinstance(debug_run, dict) else {}
    artifacts_count = _count_artifacts(step_results, run.get("output_payload_json"))
    rag_sources = _collect_rag_sources(bundle_payload)
    rag_source_names = [source["name"] for source in rag_sources if isinstance(source.get("name"), str)]
    artifact_names = _collect_artifact_names(step_results, run.get("output_payload_json"))
    artifact_details = _collect_artifact_details(step_results, run.get("output_payload_json"))
    step_overview = _build_step_overview(bundle_payload)
    citations = _build_summary_citations(bundle_payload, step_overview=step_overview)
    return {
        "status": run.get("status"),
        "trace_id": run.get("trace_id"),
        "steps_count": debug_summary.get("steps_count", len(step_results)),
        "completed_steps": debug_summary.get(
            "completed_steps",
            sum(
                1
                for result in step_results
                if isinstance(result, dict) and result.get("status") == "completed"
            ),
        ),
        "failed_steps": debug_summary.get(
            "failed_steps",
            sum(
                1
                for result in step_results
                if isinstance(result, dict) and result.get("status") == "failed"
            ),
        ),
        "attempts_count": debug_summary.get("attempts_count", len(step_attempts)),
        "artifacts_count": artifacts_count,
        "artifact_names": artifact_names,
        "artifact_details": artifact_details,
        "duration_ms": debug_summary.get("duration_ms"),
        "models_used": debug_summary.get("models_used", _collect_models_used(step_attempts)),
        "rag_sources_count": len(rag_source_names),
        "rag_source_names": rag_source_names,
        "rag_source_display_names": [format_source_display_name(name) for name in rag_source_names],
        "rag_sources": rag_sources,
        "rag_usage_tracking": _collect_rag_tracking(bundle_payload),
        "citations": citations,
        "final_output": _build_final_output_summary(
            run.get("output_payload_json"),
            step_results=step_results,
        ),
        "step_overview": step_overview,
    }


def _collect_models_used(step_attempts: Any) -> list[str]:
    models: list[str] = []
    if not isinstance(step_attempts, list):
        return models
    for attempt in step_attempts:
        if not isinstance(attempt, dict):
            continue
        for key in ("response_model", "requested_model"):
            raw_value = attempt.get(key)
            if isinstance(raw_value, str) and raw_value.strip():
                models.append(raw_value.strip())
                break
    return list(dict.fromkeys(models))


def _collect_rag_sources(bundle_payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources_by_key: dict[str, dict[str, Any]] = {}
    step_attempts = bundle_payload.get("step_attempts", [])
    if isinstance(step_attempts, list):
        for attempt in step_attempts:
            if not isinstance(attempt, dict):
                continue
            provenance = attempt.get("provenance_json")
            if not isinstance(provenance, dict):
                continue
            rag = provenance.get("rag")
            if not isinstance(rag, dict):
                continue
            references = rag.get("references")
            if not isinstance(references, list):
                continue
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                name = _resolve_rag_source_name(reference)
                key = _resolve_rag_source_key(reference, name)
                if key is None:
                    continue
                sources_by_key.setdefault(
                    key,
                    {
                        "id": reference.get("id"),
                        "name": name,
                        "display_name": (
                            format_source_display_name(name)
                            if isinstance(name, str) and name.strip()
                            else None
                        ),
                        "source_title_raw": reference.get("source_title_raw"),
                        "source_display_name": reference.get("source_display_name"),
                        "source_url": reference.get("source_url"),
                        "source_kind": reference.get("source_kind"),
                        "source_container_kind": reference.get("source_container_kind"),
                        "source_container_name": reference.get("source_container_name"),
                        "source_container_name_raw": reference.get("source_container_name_raw"),
                        "source_container_display_name": (
                            reference.get("source_container_display_name")
                            or format_source_container_display_name(reference)
                        ),
                        "source_container_label": (
                            reference.get("source_container_label")
                            or format_source_container_label(reference)
                        ),
                        "source_container_id": reference.get("source_container_id"),
                        "usage_state": reference.get("usage_state") or "retrieved_candidate",
                    },
                )
    return list(sources_by_key.values())


def _collect_rag_tracking(bundle_payload: dict[str, Any]) -> dict[str, Any]:
    step_attempts = bundle_payload.get("step_attempts", [])
    if isinstance(step_attempts, list):
        for attempt in step_attempts:
            if not isinstance(attempt, dict):
                continue
            provenance = attempt.get("provenance_json")
            if not isinstance(provenance, dict):
                continue
            rag = provenance.get("rag")
            if not isinstance(rag, dict):
                continue
            tracking = rag.get("tracking")
            if isinstance(tracking, dict):
                merged = dict(default_rag_tracking())
                for key, value in tracking.items():
                    merged[key] = value
                return merged
    return default_rag_tracking()


def _build_final_output_summary(
    run_output_payload: Any,
    *,
    step_results: Any = None,
) -> dict[str, Any]:
    payload = run_output_payload if isinstance(run_output_payload, dict) else {}
    text_value = payload.get("text")
    structured_value = payload.get("structured")
    artifact_names = _collect_artifact_names_from_single_payload(payload)
    artifact_details = _collect_artifact_details_from_single_payload(payload)
    if step_results is not None:
        summary_artifact_details = _collect_artifact_details(step_results, payload)
        if summary_artifact_details:
            artifact_details = summary_artifact_details
            artifact_names = list(
                dict.fromkeys(
                    detail["name"]
                    for detail in summary_artifact_details
                    if isinstance(detail.get("name"), str)
                )
            )
    text_present = isinstance(text_value, str) and text_value.strip() != ""
    structured_present = structured_value is not None or _has_structured_payload(payload)
    artifact_count = len(artifact_details)
    kind_flags = [text_present, structured_present, artifact_count > 0]
    if sum(kind_flags) > 1:
        kind = "mixed"
    elif text_present:
        kind = "text"
    elif structured_present:
        kind = "structured"
    elif artifact_count > 0:
        kind = "artifact"
    else:
        kind = "empty"
    return {
        "kind": kind,
        "text_present": text_present,
        "text_preview": (
            normalize_text_preview(text_value).model_dump(mode="json")
            if text_present and isinstance(text_value, str)
            else None
        ),
        "structured_present": structured_present,
        "artifact_count": artifact_count,
        "artifact_names": artifact_names,
        "artifact_details": artifact_details,
    }


def _build_step_overview(bundle_payload: dict[str, Any]) -> list[dict[str, Any]]:
    definition_snapshot = bundle_payload.get("definition_snapshot")
    raw_steps = (
        definition_snapshot.get("steps")
        if isinstance(definition_snapshot, dict)
        else None
    )
    if not isinstance(raw_steps, list):
        return []
    step_ref_mapping = build_step_ref_mapping(raw_steps)
    step_labels_by_order: dict[int, str] = {}
    for step in raw_steps:
        if not isinstance(step, dict):
            continue
        step_order_value = step.get("step_order")
        user_description = step.get("user_description")
        if isinstance(step_order_value, int) and isinstance(user_description, str):
            step_labels_by_order[step_order_value] = user_description

    results_by_order: dict[int, dict[str, Any]] = {}
    for result in bundle_payload.get("step_results", []):
        if not isinstance(result, dict):
            continue
        step_order = result.get("step_order")
        if isinstance(step_order, int):
            results_by_order[step_order] = result

    attempts_by_order: dict[int, list[dict[str, Any]]] = {}
    for attempt in bundle_payload.get("step_attempts", []):
        if not isinstance(attempt, dict):
            continue
        step_order = attempt.get("step_order")
        if isinstance(step_order, int):
            attempts_by_order.setdefault(step_order, []).append(attempt)

    overview: list[dict[str, Any]] = []
    for step in raw_steps:
        if not isinstance(step, dict):
            continue
        step_order = step.get("step_order")
        if not isinstance(step_order, int):
            continue
        result = results_by_order.get(step_order, {})
        attempts = attempts_by_order.get(step_order, [])
        rag_sources = _collect_rag_sources({"step_attempts": attempts})
        artifact_details = _collect_artifact_details_from_single_payload(result.get("output_payload_json"))
        artifact_names = [detail["name"] for detail in artifact_details if isinstance(detail.get("name"), str)]
        overview.append(
            {
                "step_order": step_order,
                "step_id": step.get("step_id"),
                "user_description": step.get("user_description"),
                "status": result.get("status"),
                "attempts_count": len(attempts),
                "retries": max(len(attempts) - 1, 0),
                "duration_ms": _sum_attempt_durations(attempts),
                "models_used": _collect_models_used(attempts),
                "knowledge_sources_count": len(rag_sources),
                "knowledge_usage_state": _resolve_step_knowledge_usage_state(rag_sources),
                "knowledge_retrieval": _build_step_knowledge_retrieval_summary(attempts, result),
                "citations": _build_output_citations(
                    result.get("output_payload_json"),
                    attempts=attempts,
                    step=step,
                ),
                "artifact_names": artifact_names,
                "artifact_details": artifact_details,
                "result_output_kind": _build_final_output_summary(result.get("output_payload_json")).get("kind"),
                "output_summary": _build_step_output_summary(result.get("output_payload_json")),
                "input_lineage": _build_input_lineage(
                    step=step,
                    step_order=step_order,
                    step_ref_mapping=step_ref_mapping,
                    step_labels_by_order=step_labels_by_order,
                    result=result,
                    max_prior_step_order=max(step_labels_by_order, default=0),
                ),
                "configured_input_type": step.get("input_type"),
                "configured_output_type": step.get("output_type"),
            }
        )
    return overview


def _count_artifacts(step_results: Any, run_output_payload: Any) -> int:
    artifact_ids: set[str] = set()
    if isinstance(step_results, list):
        for result in step_results:
            if isinstance(result, dict):
                _collect_artifact_ids(result.get("output_payload_json"), artifact_ids)
    _collect_artifact_ids(run_output_payload, artifact_ids)
    return len(artifact_ids)


def _collect_artifact_names(step_results: Any, run_output_payload: Any) -> list[str]:
    names: list[str] = []
    if isinstance(step_results, list):
        for result in step_results:
            if isinstance(result, dict):
                _collect_artifact_names_from_payload(result.get("output_payload_json"), names)
    _collect_artifact_names_from_payload(run_output_payload, names)
    return list(dict.fromkeys(name for name in names if name))


def _collect_artifact_names_from_single_payload(payload: Any) -> list[str]:
    names: list[str] = []
    _collect_artifact_names_from_payload(payload, names)
    return list(dict.fromkeys(name for name in names if name))


def _collect_artifact_details(step_results: Any, run_output_payload: Any) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    if isinstance(step_results, list):
        for result in step_results:
            if isinstance(result, dict):
                _collect_artifact_details_from_payload(result.get("output_payload_json"), details)
    _collect_artifact_details_from_payload(run_output_payload, details)
    return _dedupe_artifact_details(details)


def _collect_artifact_details_from_single_payload(payload: Any) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    _collect_artifact_details_from_payload(payload, details)
    return _dedupe_artifact_details(details)


def _collect_artifact_ids(payload: Any, artifact_ids: set[str]) -> None:
    if not isinstance(payload, dict):
        return
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict):
                file_id = artifact.get("file_id")
                if file_id is not None:
                    artifact_ids.add(str(file_id))
    for key in ("generated_file_ids", "file_ids"):
        values = payload.get(key)
        if isinstance(values, list):
            for file_id in values:
                artifact_ids.add(str(file_id))


def _collect_artifact_names_from_payload(payload: Any, artifact_names: list[str]) -> None:
    if not isinstance(payload, dict):
        return
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, dict):
                raw_name = artifact.get("file_name") or artifact.get("name") or artifact.get("title")
                if isinstance(raw_name, str) and raw_name.strip():
                    artifact_names.append(raw_name.strip())


def _collect_artifact_details_from_payload(payload: Any, artifact_details: list[dict[str, Any]]) -> None:
    if not isinstance(payload, dict):
        return
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_details.append(
                {
                    "file_id": artifact.get("file_id"),
                    "name": artifact.get("file_name") or artifact.get("name") or artifact.get("title"),
                    "mimetype": artifact.get("mimetype"),
                    "size": artifact.get("size"),
                    "checksum": artifact.get("checksum"),
                    "file_type": artifact.get("file_type"),
                }
            )


def _dedupe_artifact_details(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for detail in details:
        key = (
            str(detail.get("file_id"))
            if detail.get("file_id") is not None
            else str(detail.get("name") or detail.get("checksum") or len(by_key))
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = dict(detail)
            continue
        for field, value in detail.items():
            if existing.get(field) in (None, "", []) and value not in (None, "", []):
                existing[field] = value
    return list(by_key.values())


def _build_step_output_summary(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    text_value = payload.get("text")
    if isinstance(text_value, str) and text_value.strip():
        return normalize_text_preview(text_value, max_bytes=512).model_dump(mode="json")
    structured_value = payload.get("structured")
    if structured_value is not None:
        try:
            serialized = json.dumps(structured_value, ensure_ascii=False)
        except TypeError:
            serialized = str(structured_value)
        return normalize_text_preview(serialized, max_bytes=512).model_dump(mode="json")
    meaningful_payload = _strip_artifact_wrapper_keys(payload)
    if not meaningful_payload:
        return None
    preferred_summary = _resolve_preferred_summary_value(meaningful_payload)
    if preferred_summary is not None:
        return normalize_text_preview(preferred_summary, max_bytes=512).model_dump(mode="json")
    if len(meaningful_payload) == 1:
        only_value = next(iter(meaningful_payload.values()))
        scalar_preview = _stringify_scalar_preview(only_value)
        if scalar_preview is not None:
            return normalize_text_preview(scalar_preview, max_bytes=512).model_dump(mode="json")
    try:
        serialized = json.dumps(meaningful_payload, ensure_ascii=False)
    except TypeError:
        serialized = str(meaningful_payload)
    return normalize_text_preview(serialized, max_bytes=512).model_dump(mode="json")


def _strip_artifact_wrapper_keys(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"text", "structured", "artifacts", "generated_file_ids", "file_ids", "webhook_delivered"}
    }


def _stringify_scalar_preview(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _resolve_preferred_summary_value(payload: dict[str, Any]) -> str | None:
    for key in ("summary", "message", "result", "output", "content"):
        if key not in payload:
            continue
        scalar_preview = _stringify_scalar_preview(payload.get(key))
        if scalar_preview is not None:
            return scalar_preview
    return None


def _build_input_lineage(
    *,
    step: dict[str, Any],
    step_order: int,
    step_ref_mapping: dict[str, int],
    step_labels_by_order: dict[int, Any],
    result: dict[str, Any],
    max_prior_step_order: int,
) -> dict[str, Any]:
    input_payload = result.get("input_payload_json") if isinstance(result, dict) else {}
    input_payload = input_payload if isinstance(input_payload, dict) else {}
    runtime_input = input_payload.get("runtime_input")
    runtime_input = runtime_input if isinstance(runtime_input, dict) else {}
    runtime_files = runtime_input.get("files")
    runtime_files = runtime_files if isinstance(runtime_files, list) else []
    question_template = None
    bindings = step.get("input_bindings")
    if isinstance(bindings, dict):
        raw_question = bindings.get("question")
        if isinstance(raw_question, str) and raw_question.strip():
            question_template = raw_question
    references = (
        analyze_template(question_template, step_refs=step_ref_mapping, form_field_names=set())
        if question_template is not None
        else []
    )
    upstream_orders = resolve_upstream_step_orders(
        input_source=step.get("input_source"),
        step_order=step_order,
        references=references,
        max_prior_step_order=max_prior_step_order,
    )
    return {
        "input_source": step.get("input_source"),
        "used_question_binding": input_payload.get("used_question_binding"),
        "legacy_prompt_binding_used": input_payload.get("legacy_prompt_binding_used"),
        "uses_runtime_input": bool(runtime_input),
        "runtime_input_format": runtime_input.get("input_format"),
        "runtime_file_count": runtime_input.get("files_count", len(runtime_files)),
        "runtime_file_ids": runtime_input.get("file_ids", []),
        "runtime_file_names": [
            file_item.get("name")
            for file_item in runtime_files
            if isinstance(file_item, dict) and isinstance(file_item.get("name"), str)
        ],
        "runtime_file_checksums": [
            file_item.get("checksum")
            for file_item in runtime_files
            if isinstance(file_item, dict) and isinstance(file_item.get("checksum"), str)
        ],
        "runtime_files": runtime_files,
        "question_binding_references_runtime_input": consumes_runtime_input(references),
        "question_binding_expressions": [reference.expression for reference in references],
        "upstream_step_orders": upstream_orders,
        "upstream_step_labels": [
            str(step_labels_by_order[order])
            for order in upstream_orders
            if isinstance(step_labels_by_order.get(order), str)
        ],
    }


def _build_step_knowledge_retrieval_summary(
    attempts: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any] | None:
    rag_payload: dict[str, Any] | None = None
    for attempt in reversed(attempts):
        provenance = attempt.get("provenance_json")
        if not isinstance(provenance, dict):
            continue
        rag = provenance.get("rag")
        if isinstance(rag, dict):
            rag_payload = rag
            break
    if rag_payload is None:
        input_payload = result.get("input_payload_json") if isinstance(result, dict) else None
        if isinstance(input_payload, dict):
            raw_rag = input_payload.get("rag")
            if isinstance(raw_rag, dict):
                rag_payload = raw_rag
    if rag_payload is None:
        return None
    prompt_context = rag_payload.get("prompt_context")
    prompt_context = prompt_context if isinstance(prompt_context, dict) else None
    return {
        "status": rag_payload.get("status"),
        "attempted": rag_payload.get("attempted"),
        "retrieval_duration_ms": rag_payload.get("retrieval_duration_ms"),
        "unique_sources": rag_payload.get("unique_sources"),
        "references_truncated": rag_payload.get("references_truncated"),
        "reference_metadata_status": rag_payload.get("reference_metadata_status"),
        "retrieval_error_type": rag_payload.get("retrieval_error_type"),
        "error_code": rag_payload.get("error_code"),
        "source_names": rag_payload.get("source_names"),
        "source_display_names": rag_payload.get("source_display_names"),
        "prompt_context": (
            {
                "tracked": prompt_context.get("tracked"),
                "included_source_count": prompt_context.get("included_source_count"),
                "not_included_source_count": prompt_context.get("not_included_source_count"),
                "included_chunk_count": prompt_context.get("included_chunk_count"),
                "knowledge_tokens": prompt_context.get("knowledge_tokens"),
                "truncated_by_token_budget": prompt_context.get("truncated_by_token_budget"),
                "included_source_ids": prompt_context.get("included_source_ids"),
                "included_source_titles": prompt_context.get("included_source_titles"),
                "included_source_display_names": [
                    format_source_display_name(title)
                    for title in prompt_context.get("included_source_titles", [])
                    if isinstance(title, str) and title.strip()
                ],
                "summary": _build_inserted_sources_summary(
                    prompt_context=prompt_context,
                    references=rag_payload.get("references"),
                ),
            }
            if prompt_context is not None
            else None
        ),
    }


def _resolve_rag_source_name(reference: dict[str, Any]) -> str | None:
    for key in ("source_title", "title", "source_url"):
        raw_value = reference.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
    return None


def _resolve_rag_source_key(reference: dict[str, Any], name: str | None) -> str | None:
    raw_id = reference.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _has_structured_payload(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    for key in ("structured",):
        if payload.get(key) is not None:
            return True
    return bool(_strip_artifact_wrapper_keys(payload))


def _sum_attempt_durations(attempts: list[dict[str, Any]]) -> int | None:
    duration_ms = 0
    found = False
    for attempt in attempts:
        started_at = _parse_iso_datetime(attempt.get("started_at"))
        finished_at = _parse_iso_datetime(attempt.get("finished_at"))
        if started_at is None or finished_at is None:
            continue
        duration_ms += max(0, int((finished_at - started_at).total_seconds() * 1000))
        found = True
    return duration_ms if found else None


def _resolve_step_knowledge_usage_state(rag_sources: list[dict[str, Any]]) -> str | None:
    if not rag_sources:
        return None
    usage_states = list(
        dict.fromkeys(
            source.get("usage_state")
            for source in rag_sources
            if isinstance(source.get("usage_state"), str)
        )
    )
    if not usage_states:
        return None
    if len(usage_states) == 1:
        return usage_states[0]
    return "mixed"


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_summary_citations(
    bundle_payload: dict[str, Any],
    *,
    step_overview: list[dict[str, Any]],
) -> dict[str, Any]:
    run = bundle_payload.get("run", {})
    summary = _build_output_citations(
        run.get("output_payload_json"),
        attempts=bundle_payload.get("step_attempts", []),
        step=_resolve_last_definition_step(bundle_payload),
    )
    step_citations = [
        citations
        for item in step_overview
        if isinstance(item, dict)
        and isinstance((citations := item.get("citations")), dict)
    ]
    summary.update(
        summarize_step_citations(step_citations)
    )
    return summary


def _build_output_citations(
    output_payload: Any,
    *,
    attempts: Any,
    step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rag_payload = _resolve_latest_rag_payload(attempts)
    prompt_context = rag_payload.get("prompt_context") if isinstance(rag_payload, dict) else None
    included_source_ids = (
        prompt_context.get("included_source_ids")
        if isinstance(prompt_context, dict)
        else []
    )
    references = rag_payload.get("references") if isinstance(rag_payload, dict) else None
    stored_sidecar = _resolve_latest_citation_payload(attempts)
    if isinstance(stored_sidecar, dict):
        return normalize_citation_sidecar_payload(stored_sidecar)
    citation_mode = resolve_citation_mode(step.get("output_config")) if isinstance(step, dict) else "off"
    return build_citation_sidecar(
        output_payload,
        references=references if isinstance(references, list) else None,
        included_source_ids=included_source_ids if isinstance(included_source_ids, list) else None,
        tracking_mode=(
            TRACKING_MODE_INLINE_INREF_REQUIRED
            if citation_mode == "inline_inref_sidecar"
            else TRACKING_MODE_PASSIVE_INLINE_SCAN
        ),
        citation_mode_requested=citation_mode == "inline_inref_sidecar",
    )


def _resolve_latest_rag_payload(attempts: Any) -> dict[str, Any] | None:
    if not isinstance(attempts, list):
        return None
    sorted_attempts = sorted(
        [attempt for attempt in attempts if isinstance(attempt, dict)],
        key=lambda attempt: (
            int(attempt.get("step_order", 0) or 0),
            int(attempt.get("attempt_no", 0) or 0),
        ),
        reverse=True,
    )
    for attempt in sorted_attempts:
        if not isinstance(attempt, dict):
            continue
        provenance = attempt.get("provenance_json")
        if not isinstance(provenance, dict):
            continue
        rag_payload = provenance.get("rag")
        if isinstance(rag_payload, dict):
            return rag_payload
    return None


def _resolve_latest_citation_payload(attempts: Any) -> dict[str, Any] | None:
    if not isinstance(attempts, list):
        return None
    sorted_attempts = sorted(
        [attempt for attempt in attempts if isinstance(attempt, dict)],
        key=lambda attempt: (
            int(attempt.get("step_order", 0) or 0),
            int(attempt.get("attempt_no", 0) or 0),
        ),
        reverse=True,
    )
    for attempt in sorted_attempts:
        provenance = attempt.get("provenance_json")
        if not isinstance(provenance, dict):
            continue
        citations = provenance.get("citations")
        if isinstance(citations, dict):
            return citations
    return None


def _resolve_last_definition_step(bundle_payload: dict[str, Any]) -> dict[str, Any] | None:
    definition_snapshot = bundle_payload.get("definition_snapshot")
    raw_steps = definition_snapshot.get("steps") if isinstance(definition_snapshot, dict) else None
    if not isinstance(raw_steps, list):
        return None
    typed_steps = [step for step in raw_steps if isinstance(step, dict)]
    if not typed_steps:
        return None
    return max(
        typed_steps,
        key=lambda step: int(step.get("step_order", 0) or 0),
    )


def _build_inserted_sources_summary(
    *,
    prompt_context: dict[str, Any],
    references: Any,
    max_ranked_sources: int = 5,
) -> dict[str, Any]:
    groups = [
        group
        for group in prompt_context.get("included_groups", [])
        if isinstance(group, dict)
    ]
    included_source_ids = [
        source_id
        for source_id in prompt_context.get("included_source_ids", [])
        if isinstance(source_id, str) and source_id.strip()
    ]
    grouped_chunks: dict[str, int] = {}
    grouped_titles: dict[str, str] = {}
    grouped_scores: dict[str, float] = {}
    grouped_counts: dict[str, int] = {}
    for group in groups:
        source_id = group.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        grouped_chunks[source_id] = grouped_chunks.get(source_id, 0) + int(
            group.get("chunk_count", 0) or 0
        )
        grouped_counts[source_id] = grouped_counts.get(source_id, 0) + 1
        if isinstance(group.get("source_title"), str) and group["source_title"].strip():
            grouped_titles[source_id] = group["source_title"].strip()
        grouped_scores[source_id] = max(
            grouped_scores.get(source_id, 0.0),
            float(group.get("relevance_score", 0.0) or 0.0),
        )

    references_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue
            source_id = reference.get("id")
            if isinstance(source_id, str) and source_id.strip():
                references_by_id[source_id] = reference

    ranked_sources: list[dict[str, Any]] = []
    for source_id in included_source_ids:
        reference = references_by_id.get(source_id, {})
        display_name = (
            reference.get("source_display_name")
            or reference.get("display_title")
            or grouped_titles.get(source_id)
        )
        ranked_sources.append(
            {
                "source_id": source_id,
                "display_name": display_name,
                "source_kind": reference.get("source_kind"),
                "included_group_count": grouped_counts.get(source_id, 0),
                "included_chunk_count": grouped_chunks.get(source_id, 0),
                "best_score": max(
                    grouped_scores.get(source_id, 0.0),
                    float(reference.get("best_score", 0.0) or 0.0),
                ),
            }
        )
    ranked_sources.sort(
        key=lambda item: (
            -int(item.get("included_group_count", 0) or 0),
            -int(item.get("included_chunk_count", 0) or 0),
            -float(item.get("best_score", 0.0) or 0.0),
            str(item.get("source_id") or ""),
        )
    )
    for index, item in enumerate(ranked_sources, start=1):
        item["rank"] = index
    return {
        "total_sources": prompt_context.get("included_source_count") or len(included_source_ids),
        "total_chunks": prompt_context.get("included_chunk_count")
        or sum(grouped_chunks.values()),
        "truncated_by_token_budget": bool(prompt_context.get("truncated_by_token_budget")),
        "top_ranked_sources": ranked_sources[:max_ranked_sources],
    }
