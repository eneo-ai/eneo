from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from eneo.flows.api.flow_run_contract_models import (
    FlowCitationSourcePublic,
    FlowCitationSummaryPublic,
    FlowCitationSummaryStatus,
)
from eneo.flows.citation_sidecar import (
    CITATION_MODE_INLINE_INREF_SIDECAR,
    COMPLIANCE_MISSING_REQUIRED,
    COMPLIANCE_NOT_REQUESTED,
    COMPLIANCE_OBSERVED,
    COMPLIANCE_UNKNOWN_IDS,
    resolve_citation_mode,
)
from eneo.flows.domain.flow import FlowStepAttempt, FlowStepResult
from eneo.flows.domain.rag_evidence import CITATION_SOURCES_KEY
from eneo.flows.flow_run_provenance import parse_attempt_provenance
from eneo.flows.source_display import (
    format_source_container_label,
    format_source_display_name,
    resolve_reference_title,
)

_CITATION_SOURCE_LIMIT = 20
_CITATION_COMPLIANCE_VALUES = {
    COMPLIANCE_NOT_REQUESTED,
    COMPLIANCE_OBSERVED,
    COMPLIANCE_MISSING_REQUIRED,
    COMPLIANCE_UNKNOWN_IDS,
}


def citation_grounded_step_orders(
    current_attempt: FlowStepAttempt | None,
) -> tuple[int, ...]:
    sidecar = _citation_sidecar(current_attempt)
    if sidecar is None:
        return ()
    grounded_orders = _grounded_step_orders(sidecar)
    return grounded_orders if grounded_orders is not None else ()


def _grounded_step_orders(sidecar: Mapping[str, object]) -> tuple[int, ...] | None:
    raw_orders = sidecar.get("upstream_grounded_step_orders")
    if not isinstance(raw_orders, list):
        return None
    orders = cast(list[object], raw_orders)
    if any(
        not isinstance(order, int) or isinstance(order, bool) or order < 1
        for order in orders
    ):
        return None
    return tuple(sorted(set(cast(list[int], orders))))


def build_citation_summary(
    *,
    output_config: Mapping[str, object] | None,
    current_attempt: FlowStepAttempt | None,
    step_result: FlowStepResult | None,
    upstream_step_results: Sequence[FlowStepResult] = (),
    edited_at: datetime | None = None,
    config_known: bool = True,
) -> FlowCitationSummaryPublic | None:
    if config_known:
        if resolve_citation_mode(output_config) != CITATION_MODE_INLINE_INREF_SIDECAR:
            return None
        sidecar = _citation_sidecar(current_attempt)
        if sidecar is None:
            return _summary(status="unavailable", edited_at=edited_at)
    else:
        # The pinned configuration could not be established (unverified
        # definition integrity). The runtime sidecar is then the source of
        # truth: its presence proves citations were on for this attempt,
        # while its absence supports no claim either way — never infer
        # "citations off" from an unknown configuration.
        sidecar = _citation_sidecar(current_attempt)
        if sidecar is None:
            return None

    cited_source_ids = _string_list(sidecar.get("cited_source_ids"))
    unknown_citation_ids = _string_list(sidecar.get("unknown_citation_ids"))
    grounded_orders = _grounded_step_orders(sidecar)
    compliance = sidecar.get("citation_compliance")
    if (
        cited_source_ids is None
        or unknown_citation_ids is None
        or grounded_orders is None
        or compliance not in _CITATION_COMPLIANCE_VALUES
    ):
        return _summary(status="unavailable", edited_at=edited_at)

    direct_sources = _citation_sources(step_result)
    source_by_id = {
        source_id: source
        for source in direct_sources
        if (source_id := _source_id(source)) is not None
    }
    grounded_order_set = set(grounded_orders)
    for upstream_result in sorted(
        (
            result
            for result in upstream_step_results
            if result.step_order in grounded_order_set
        ),
        key=lambda result: result.step_order,
    ):
        for source in _citation_sources(upstream_result):
            source_id = _source_id(source)
            if source_id is not None:
                source_by_id.setdefault(source_id, source)

    cited_source_ids = list(dict.fromkeys(cited_source_ids))
    # Every id in cited_source_ids is runtime-validated (unknown ids live in
    # unknown_citation_ids), so the matched count is the deduplicated id
    # count — a source whose display identity cannot be recovered is still a
    # matched citation.
    matched_count = len(cited_source_ids)
    projected_sources: list[FlowCitationSourcePublic] = []
    for source_id in cited_source_ids:
        source = source_by_id.get(source_id)
        if source is None:
            projected_sources.append(
                FlowCitationSourcePublic(
                    identity_resolved=False,
                    display_name=None,
                    container_label=None,
                )
            )
            continue
        display_name = _display_name(source)
        container_label = _container_label(source)
        projected_sources.append(
            FlowCitationSourcePublic(
                identity_resolved=(
                    display_name is not None or container_label is not None
                ),
                display_name=display_name,
                container_label=container_label,
            )
        )

    applicable_sources_existed = bool(direct_sources or grounded_orders)
    if compliance == COMPLIANCE_UNKNOWN_IDS or unknown_citation_ids:
        status = "unknown_citation_ids_present"
    elif compliance == COMPLIANCE_MISSING_REQUIRED:
        status = "missing_required_citations"
    elif not applicable_sources_existed:
        status = "citations_on_without_sources"
    elif compliance == COMPLIANCE_OBSERVED:
        status = "observed"
    else:
        status = "unavailable"

    return FlowCitationSummaryPublic(
        status=status,
        sources=projected_sources[:_CITATION_SOURCE_LIMIT],
        matched_cited_source_count=matched_count,
        sources_truncated=len(projected_sources) > _CITATION_SOURCE_LIMIT,
        stale_after_edit=edited_at is not None,
    )


def _citation_sidecar(
    current_attempt: FlowStepAttempt | None,
) -> dict[str, Any] | None:
    if current_attempt is None:
        return None
    parsed = parse_attempt_provenance(current_attempt.provenance_json)
    if parsed.status != "tracked" or parsed.provenance is None:
        return None
    citations = parsed.provenance.citations
    if citations is None:
        return None
    return citations.model_dump(mode="python")


def _citation_sources(step_result: FlowStepResult | None) -> list[dict[str, Any]]:
    if step_result is None or not isinstance(step_result.input_payload_json, dict):
        return []
    payload = cast(dict[str, object], step_result.input_payload_json)
    rag = payload.get("rag")
    if not isinstance(rag, dict):
        return []
    raw_sources = cast(dict[str, object], rag).get(CITATION_SOURCES_KEY)
    if not isinstance(raw_sources, list):
        return []
    return [
        cast(dict[str, Any], source)
        for source in cast(list[object], raw_sources)
        if isinstance(source, dict)
    ]


def _source_id(source: Mapping[str, Any]) -> str | None:
    source_id = source.get("id")
    if not isinstance(source_id, str) or not source_id.strip():
        return None
    return source_id.strip()


def _display_name(source: dict[str, Any]) -> str | None:
    display_name = source.get("source_display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name.strip()
    title = resolve_reference_title(source)
    if title is None:
        return None
    formatted = format_source_display_name(title)
    return formatted or None


def _container_label(source: dict[str, Any]) -> str | None:
    label = source.get("source_container_label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    return format_source_container_label(source)


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in cast(list[object], value)
    ):
        return None
    items = [item.strip() for item in cast(list[str], value)]
    if any(not item for item in items):
        # A blank identifier is corrupt provenance, not an empty entry to
        # skip — the whole sidecar is undecodable.
        return None
    return items


def _summary(
    *,
    status: FlowCitationSummaryStatus,
    edited_at: datetime | None,
) -> FlowCitationSummaryPublic:
    return FlowCitationSummaryPublic(
        status=status,
        sources=[],
        matched_cited_source_count=0,
        sources_truncated=False,
        stale_after_edit=edited_at is not None,
    )
