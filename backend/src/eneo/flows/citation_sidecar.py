from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, cast

from eneo.assistants.reference_tags import (
    INLINE_REFERENCE_PATTERN,
    extract_inline_reference_ids,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject

CITATION_MODE_OFF = "off"
CITATION_MODE_INLINE_INREF_SIDECAR = "inline_inref_sidecar"
TRACKING_MODE_PASSIVE_INLINE_SCAN = "passive_inline_scan"
TRACKING_MODE_INLINE_INREF_REQUIRED = "inline_inref_required"
COMPLIANCE_NOT_REQUESTED = "not_requested"
COMPLIANCE_OBSERVED = "observed"
COMPLIANCE_MISSING_REQUIRED = "missing_required_citations"
COMPLIANCE_UNKNOWN_IDS = "unknown_citation_ids_present"

_EXTRA_INLINE_REFERENCE_SPACE_PATTERN = re.compile(r"[ \t]{2,}")


def resolve_citation_mode(output_config: Any) -> str:
    if not isinstance(output_config, dict):
        return CITATION_MODE_OFF
    raw_mode = cast(FlowPersistedJsonObject, output_config).get("citation_mode")
    if not isinstance(raw_mode, str):
        return CITATION_MODE_OFF
    normalized = raw_mode.strip()
    return normalized or CITATION_MODE_OFF


def strip_inline_reference_tags(text: str) -> str:
    if not text:
        return text
    stripped = INLINE_REFERENCE_PATTERN.sub("", text)
    stripped = _EXTRA_INLINE_REFERENCE_SPACE_PATTERN.sub(" ", stripped)
    return stripped.strip()


def build_citation_sidecar(
    output_payload: Any,
    *,
    references: list[dict[str, Any]] | None = None,
    included_source_ids: list[str] | None = None,
    inherited_references: list[dict[str, Any]] | None = None,
    inherited_source_ids: list[str] | None = None,
    tracking_mode: str | None = None,
    citation_mode_requested: bool = False,
    citation_expected: bool = False,
    upstream_grounded_step_orders: list[int] | None = None,
    upstream_grounded_step_labels: list[str] | None = None,
    raw_completion_text: str | None = None,
) -> dict[str, Any]:
    cited_reference_ids = _extract_reference_ids_from_payload(
        raw_completion_text if raw_completion_text is not None else output_payload
    )
    direct_included_source_ids = _dedupe_nonempty_strings(included_source_ids)
    inherited_available_source_ids = _dedupe_nonempty_strings(inherited_source_ids)
    direct_known_sources = _build_known_sources_map(
        references or [], direct_included_source_ids
    )
    inherited_known_sources = _build_known_sources_map(
        inherited_references or [],
        inherited_available_source_ids,
    )

    cited_source_ids: list[str] = []
    direct_cited_source_ids: list[str] = []
    inherited_cited_source_ids: list[str] = []
    unknown_citation_ids: list[str] = []
    for cited_reference_id in cited_reference_ids:
        direct_resolved = direct_known_sources.get(cited_reference_id)
        if direct_resolved is not None:
            cited_source_ids.append(direct_resolved)
            direct_cited_source_ids.append(direct_resolved)
            continue
        inherited_resolved = inherited_known_sources.get(cited_reference_id)
        if inherited_resolved is not None:
            cited_source_ids.append(inherited_resolved)
            inherited_cited_source_ids.append(inherited_resolved)
            continue
        unknown_citation_ids.append(cited_reference_id)

    deduped_cited_source_ids = list(dict.fromkeys(cited_source_ids))
    direct_available_source_ids = direct_included_source_ids
    deduped_direct_cited_source_ids = list(dict.fromkeys(direct_cited_source_ids))
    deduped_inherited_cited_source_ids = list(dict.fromkeys(inherited_cited_source_ids))
    uncited_inserted_source_ids = [
        source_id
        for source_id in direct_available_source_ids
        if source_id not in deduped_direct_cited_source_ids
    ]
    uncited_inherited_source_ids = [
        source_id
        for source_id in inherited_available_source_ids
        if source_id not in deduped_inherited_cited_source_ids
    ]

    citation_applicable = bool(
        direct_available_source_ids or inherited_available_source_ids
    )
    if citation_mode_requested:
        citation_expected = citation_applicable
    citation_observed = bool(deduped_cited_source_ids or unknown_citation_ids)
    normalized_tracking_mode = tracking_mode or (
        TRACKING_MODE_INLINE_INREF_REQUIRED
        if citation_mode_requested
        else TRACKING_MODE_PASSIVE_INLINE_SCAN
    )
    citation_compliance = _resolve_citation_compliance(
        citation_expected=citation_expected,
        citation_observed=citation_observed,
        unknown_citation_ids=unknown_citation_ids,
    )
    citation_context_kind = _resolve_citation_context_kind(
        direct_available_source_ids=direct_available_source_ids,
        inherited_available_source_ids=inherited_available_source_ids,
    )

    sidecar = {
        "tracking_mode": normalized_tracking_mode,
        "citation_tracked": True,
        "citation_mode_requested": citation_mode_requested,
        "citation_applicable": citation_applicable,
        "citation_context_kind": citation_context_kind,
        "citation_expected": citation_expected,
        "citation_observed": citation_observed,
        "citation_compliance": citation_compliance,
        "cited_source_ids": deduped_cited_source_ids,
        "cited_source_count": len(deduped_cited_source_ids),
        "unknown_citation_ids": list(dict.fromkeys(unknown_citation_ids)),
        "uncited_inserted_source_ids": uncited_inserted_source_ids,
        "uncited_inherited_source_ids": uncited_inherited_source_ids,
        "direct_available_source_ids": direct_available_source_ids,
        "inherited_available_source_ids": inherited_available_source_ids,
        "direct_cited_source_ids": deduped_direct_cited_source_ids,
        "inherited_cited_source_ids": deduped_inherited_cited_source_ids,
        "upstream_grounded_step_orders": sorted(
            {int(step_order) for step_order in upstream_grounded_step_orders or []}
        ),
        "upstream_grounded_step_labels": _dedupe_nonempty_strings(
            upstream_grounded_step_labels
        ),
    }
    if raw_completion_text is not None:
        sidecar["raw_completion_text"] = raw_completion_text
    return sidecar


def summarize_step_citations(
    step_citations: Iterable[dict[str, Any]],
) -> dict[str, int]:
    requested = 0
    applicable = 0
    direct_context = 0
    inherited_context = 0
    expected = 0
    observed = 0
    missing_required = 0
    unknown_ids = 0
    for citation in step_citations:
        if bool(citation.get("citation_mode_requested")):
            requested += 1
        if bool(citation.get("citation_applicable")):
            applicable += 1
        context_kind = citation.get("citation_context_kind")
        if context_kind in {"direct", "mixed"}:
            direct_context += 1
        if context_kind in {"inherited", "mixed"}:
            inherited_context += 1
        if bool(citation.get("citation_expected")):
            expected += 1
        if bool(citation.get("citation_observed")):
            observed += 1
        if citation.get("citation_compliance") == COMPLIANCE_MISSING_REQUIRED:
            missing_required += 1
        if citation.get("citation_compliance") == COMPLIANCE_UNKNOWN_IDS:
            unknown_ids += 1
    return {
        "steps_with_citation_mode_requested": requested,
        "steps_with_citations_applicable": applicable,
        "steps_with_direct_citation_context": direct_context,
        "steps_with_inherited_citation_context": inherited_context,
        "steps_with_citations_expected": expected,
        "steps_with_citations_observed": observed,
        "steps_missing_required_citations": missing_required,
        "steps_with_unknown_citation_ids": unknown_ids,
    }


def normalize_citation_sidecar_payload(sidecar: dict[str, Any]) -> dict[str, Any]:
    cited_source_ids = [
        source_id.strip()
        for source_id in sidecar.get("cited_source_ids", [])
        if isinstance(source_id, str) and source_id.strip()
    ]
    unknown_citation_ids = [
        citation_id.strip()
        for citation_id in sidecar.get("unknown_citation_ids", [])
        if isinstance(citation_id, str) and citation_id.strip()
    ]
    uncited_inserted_source_ids = [
        source_id.strip()
        for source_id in sidecar.get("uncited_inserted_source_ids", [])
        if isinstance(source_id, str) and source_id.strip()
    ]
    uncited_inherited_source_ids = [
        source_id.strip()
        for source_id in sidecar.get("uncited_inherited_source_ids", [])
        if isinstance(source_id, str) and source_id.strip()
    ]
    direct_available_source_ids = _dedupe_nonempty_strings(
        sidecar.get("direct_available_source_ids")
    )
    inherited_available_source_ids = _dedupe_nonempty_strings(
        sidecar.get("inherited_available_source_ids")
    )
    direct_cited_source_ids = _dedupe_nonempty_strings(
        sidecar.get("direct_cited_source_ids")
    )
    inherited_cited_source_ids = _dedupe_nonempty_strings(
        sidecar.get("inherited_cited_source_ids")
    )
    citation_mode_requested = bool(
        sidecar.get(
            "citation_mode_requested",
            sidecar.get("tracking_mode") == TRACKING_MODE_INLINE_INREF_REQUIRED,
        )
    )
    citation_applicable = bool(
        sidecar.get(
            "citation_applicable",
            bool(direct_available_source_ids or inherited_available_source_ids),
        )
    )
    citation_expected = bool(sidecar.get("citation_expected"))
    citation_observed = bool(
        sidecar.get("citation_observed", bool(cited_source_ids or unknown_citation_ids))
    )
    citation_compliance = sidecar.get("citation_compliance")
    if not isinstance(citation_compliance, str) or not citation_compliance.strip():
        citation_compliance = _resolve_citation_compliance(
            citation_expected=citation_expected,
            citation_observed=citation_observed,
            unknown_citation_ids=unknown_citation_ids,
        )
    tracking_mode = sidecar.get("tracking_mode")
    if not isinstance(tracking_mode, str) or not tracking_mode.strip():
        tracking_mode = (
            TRACKING_MODE_INLINE_INREF_REQUIRED
            if citation_expected
            else TRACKING_MODE_PASSIVE_INLINE_SCAN
        )
    normalized = {
        "tracking_mode": tracking_mode,
        "citation_tracked": bool(sidecar.get("citation_tracked", True)),
        "citation_mode_requested": citation_mode_requested,
        "citation_applicable": citation_applicable,
        "citation_context_kind": sidecar.get("citation_context_kind")
        if isinstance(sidecar.get("citation_context_kind"), str)
        else _resolve_citation_context_kind(
            direct_available_source_ids=direct_available_source_ids,
            inherited_available_source_ids=inherited_available_source_ids,
        ),
        "citation_expected": citation_expected,
        "citation_observed": citation_observed,
        "citation_compliance": citation_compliance,
        "cited_source_ids": list(dict.fromkeys(cited_source_ids)),
        "cited_source_count": len(list(dict.fromkeys(cited_source_ids))),
        "unknown_citation_ids": list(dict.fromkeys(unknown_citation_ids)),
        "uncited_inserted_source_ids": list(dict.fromkeys(uncited_inserted_source_ids)),
        "uncited_inherited_source_ids": list(
            dict.fromkeys(uncited_inherited_source_ids)
        ),
        "direct_available_source_ids": direct_available_source_ids,
        "inherited_available_source_ids": inherited_available_source_ids,
        "direct_cited_source_ids": direct_cited_source_ids,
        "inherited_cited_source_ids": inherited_cited_source_ids,
        "upstream_grounded_step_orders": sorted(
            {
                int(step_order)
                for step_order in sidecar.get("upstream_grounded_step_orders", [])
                if isinstance(step_order, int)
            }
        ),
        "upstream_grounded_step_labels": _dedupe_nonempty_strings(
            sidecar.get("upstream_grounded_step_labels")
        ),
    }
    raw_completion_text = sidecar.get("raw_completion_text")
    if isinstance(raw_completion_text, str) and raw_completion_text:
        normalized["raw_completion_text"] = raw_completion_text
    return normalized


def _resolve_citation_compliance(
    *,
    citation_expected: bool,
    citation_observed: bool,
    unknown_citation_ids: list[str],
) -> str:
    if unknown_citation_ids:
        return COMPLIANCE_UNKNOWN_IDS
    if citation_expected and not citation_observed:
        return COMPLIANCE_MISSING_REQUIRED
    if citation_observed:
        return COMPLIANCE_OBSERVED
    return COMPLIANCE_NOT_REQUESTED


def _resolve_citation_context_kind(
    *,
    direct_available_source_ids: list[str],
    inherited_available_source_ids: list[str],
) -> str:
    if direct_available_source_ids and inherited_available_source_ids:
        return "mixed"
    if direct_available_source_ids:
        return "direct"
    if inherited_available_source_ids:
        return "inherited"
    return "none"


def _build_known_sources_map(
    references: list[dict[str, Any]],
    included_source_ids: list[str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for reference in references:
        raw_id = reference.get("id")
        if isinstance(raw_id, str) and raw_id.strip():
            mapping[raw_id.strip()] = raw_id.strip()
            mapping[raw_id.strip()[:8]] = raw_id.strip()
        raw_short = reference.get("id_short")
        if isinstance(raw_short, str) and raw_short.strip():
            raw_id = reference.get("id")
            if isinstance(raw_id, str) and raw_id.strip():
                mapping[raw_short.strip()] = raw_id.strip()
    for source_id in included_source_ids:
        mapping[source_id] = source_id
        mapping[source_id[:8]] = source_id
    return mapping


def _extract_reference_ids_from_payload(value: Any) -> list[str]:
    return list(
        dict.fromkeys(
            reference_id
            for text in _iter_strings(value)
            for reference_id in extract_inline_reference_ids(text)
        )
    )


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for nested in cast(FlowPersistedJsonObject, value).values():
            yield from _iter_strings(nested)
        return
    if isinstance(value, list):
        for nested in cast(list[Any], value):
            yield from _iter_strings(nested)


def _dedupe_nonempty_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(
            value.strip()
            for value in cast(list[object], values)
            if isinstance(value, str) and value.strip()
        )
    )
