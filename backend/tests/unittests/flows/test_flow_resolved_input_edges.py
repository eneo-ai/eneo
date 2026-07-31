from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.domain.canonical_json_hash import (
    canonical_json_bytes,
    canonical_json_hash,
)
from eneo.flows.flow_retention_tombstone import (
    FlowAttemptRetentionMarker,
    FlowRetentionTombstone,
    RunDebugAttemptRetentionCounts,
)
from eneo.flows.flow_run_provenance import (
    FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES,
    FLOW_RESOLVED_INPUT_MAX_EDGES,
    FlowAttemptProvenanceParseResult,
    FlowAttemptScopedProvenance,
    FlowResolvedInputEdges,
    group_resolved_input_edges,
    parse_attempt_provenance_for_attempt,
    parse_resolved_input_edges,
    project_resolved_input_lineage,
)


def _edge_payload(*, binding_ref: str = "question") -> dict[str, object]:
    return {
        "binding_ref": binding_ref,
        "source": {
            "kind": "step_result",
            "source_step_id": str(uuid4()),
            "source_attempt_no": 3,
            "selector": {"kind": "json_path", "path": ["summary"]},
        },
        "selection": {
            "encoding": "canonical_json",
            "sha256": "a" * 64,
            "byte_size": 12,
        },
    }


def _payload_with_canonical_size(byte_size: int) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "edges": [
            _edge_payload(binding_ref="x") for _ in range(FLOW_RESOLVED_INPUT_MAX_EDGES)
        ],
    }
    remaining = byte_size - len(canonical_json_bytes(payload))
    assert remaining >= 0

    edges = payload["edges"]
    assert isinstance(edges, list)
    first_edge = edges[0]
    assert isinstance(first_edge, dict)
    first_edge["binding_ref"] = "x" * (1 + remaining)

    assert len(canonical_json_bytes(payload)) == byte_size
    return payload


def test_resolved_input_edges_accepts_exact_count_limit() -> None:
    aggregate = FlowResolvedInputEdges.model_validate(
        {
            "schema_version": 1,
            "edges": [_edge_payload() for _ in range(FLOW_RESOLVED_INPUT_MAX_EDGES)],
        }
    )

    assert len(aggregate.edges) == FLOW_RESOLVED_INPUT_MAX_EDGES


def test_resolved_input_edges_rejects_count_limit_plus_one() -> None:
    with pytest.raises(ValidationError, match="at most 2048"):
        FlowResolvedInputEdges.model_validate(
            {
                "schema_version": 1,
                "edges": [
                    _edge_payload() for _ in range(FLOW_RESOLVED_INPUT_MAX_EDGES + 1)
                ],
            }
        )


@pytest.mark.parametrize("schema_version", [True, 1.0, "1"])
def test_resolved_input_edges_requires_exact_integer_schema_version(
    schema_version: object,
) -> None:
    with pytest.raises(ValidationError, match="schema_version must be the integer 1"):
        FlowResolvedInputEdges.model_validate(
            {"schema_version": schema_version, "edges": []}
        )


def test_resolved_input_edges_accepts_exact_canonical_byte_limit() -> None:
    aggregate = FlowResolvedInputEdges.model_validate(
        _payload_with_canonical_size(FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES)
    )

    assert (
        len(canonical_json_bytes(aggregate.model_dump(mode="json")))
        == FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES
    )


def test_tracked_projection_preserves_exact_canonical_byte_limit() -> None:
    aggregate = FlowResolvedInputEdges.model_validate(
        _payload_with_canonical_size(FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES)
    )

    lineage = project_resolved_input_lineage(
        resolved_inputs=parse_resolved_input_edges(aggregate.model_dump(mode="json")),
        scoped_attempt_provenance=FlowAttemptScopedProvenance(
            parse_result=FlowAttemptProvenanceParseResult.not_tracked()
        ),
    )

    assert lineage.status == "tracked"
    assert lineage.edges == aggregate.edges


def test_resolved_input_edges_rejects_canonical_byte_limit_plus_one() -> None:
    with pytest.raises(ValidationError, match="canonical JSON exceeds 1048576 bytes"):
        FlowResolvedInputEdges.model_validate(
            _payload_with_canonical_size(FLOW_RESOLVED_INPUT_MAX_CANONICAL_BYTES + 1)
        )


def test_parse_resolved_input_edges_marks_unsupported_version_unavailable() -> None:
    result = parse_resolved_input_edges({"schema_version": 2, "edges": []})

    assert result.status == "corrupt"
    assert result.aggregate is None
    assert result.marker is not None
    assert (
        result.marker.error_code
        == "flow_resolved_input_edges_schema_version_unsupported"
    )
    assert result.marker.persisted_schema_version == 2


def test_parse_resolved_input_edges_never_returns_partial_corrupt_evidence() -> None:
    payload = {"schema_version": 1, "edges": [_edge_payload(), _edge_payload()]}
    corrupt_payload = deepcopy(payload)
    edges = corrupt_payload["edges"]
    assert isinstance(edges, list)
    corrupt_edge = edges[1]
    assert isinstance(corrupt_edge, dict)
    corrupt_edge["unexpected"] = "not accepted"

    result = parse_resolved_input_edges(corrupt_payload)

    assert result.status == "corrupt"
    assert result.aggregate is None
    assert result.marker is not None
    assert result.marker.error_code == "flow_resolved_input_edges_invalid_payload"


@pytest.mark.parametrize("malformed_field", ["binding_ref", "path_segment"])
def test_resolved_input_edges_rejects_empty_identifiers(
    malformed_field: str,
) -> None:
    payload = {"schema_version": 1, "edges": [_edge_payload()]}
    edge = payload["edges"][0]
    assert isinstance(edge, dict)
    if malformed_field == "binding_ref":
        edge["binding_ref"] = ""
    else:
        source = edge["source"]
        assert isinstance(source, dict)
        selector = source["selector"]
        assert isinstance(selector, dict)
        selector["path"] = [""]

    with pytest.raises(ValidationError):
        FlowResolvedInputEdges.model_validate(payload)

    parsed = parse_resolved_input_edges(payload)
    assert parsed.status == "corrupt"
    assert parsed.aggregate is None


def test_resolved_input_edges_allows_empty_path_for_whole_value_selection() -> None:
    payload = {"schema_version": 1, "edges": [_edge_payload()]}
    edge = payload["edges"][0]
    assert isinstance(edge, dict)
    source = edge["source"]
    assert isinstance(source, dict)
    selector = source["selector"]
    assert isinstance(selector, dict)
    selector["path"] = []

    aggregate = FlowResolvedInputEdges.model_validate(payload)

    assert aggregate.edges[0].source.selector.path == ()


def test_resolved_input_edges_preserves_numeric_json_path_segments() -> None:
    payload = {"schema_version": 1, "edges": [_edge_payload()]}
    edge = payload["edges"][0]
    assert isinstance(edge, dict)
    source = edge["source"]
    assert isinstance(source, dict)
    selector = source["selector"]
    assert isinstance(selector, dict)
    selector["path"] = ["rows", 1, "title"]

    aggregate = FlowResolvedInputEdges.model_validate(payload)

    assert aggregate.edges[0].source.selector.path == ("rows", 1, "title")


def test_resolved_input_edge_grouping_returns_stable_call_indexes() -> None:
    shared_edge = FlowResolvedInputEdges.model_validate(
        {"schema_version": 1, "edges": [_edge_payload(binding_ref="shared")]}
    ).edges[0]
    first_only_edge = FlowResolvedInputEdges.model_validate(
        {"schema_version": 1, "edges": [_edge_payload(binding_ref="first")]}
    ).edges[0]
    second_only_edge = FlowResolvedInputEdges.model_validate(
        {"schema_version": 1, "edges": [_edge_payload(binding_ref="second")]}
    ).edges[0]

    grouping = group_resolved_input_edges(
        (shared_edge, first_only_edge),
        (second_only_edge, shared_edge),
    )

    assert grouping.aggregate.edges == (
        shared_edge,
        first_only_edge,
        second_only_edge,
    )
    assert grouping.indexes_by_group == ((0, 1), (0, 2))


def test_parse_resolved_input_edges_preserves_null_as_not_tracked() -> None:
    result = parse_resolved_input_edges(None)

    assert result.status == "not_tracked"
    assert result.aggregate is None
    assert result.marker is None


def test_missing_resolved_input_lineage_uses_attempt_retention_marker() -> None:
    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    run_id = uuid4()
    attempt_id = uuid4()
    marker = FlowAttemptRetentionMarker(
        tombstone=FlowRetentionTombstone(
            tenant_id=str(tenant_id),
            run_id=str(run_id),
            trace_id=str(uuid4()),
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=str(attempt_id),
            policy_source="tenant_policy",
            cutoff=now,
            counts=RunDebugAttemptRetentionCounts(
                cleared_field_count=3,
                provider_call_count=2,
                resolved_input_aggregate_count=1,
                resolved_input_edge_count=7,
            ),
            timestamp=now,
            retention_state="retention_purged",
        )
    )

    scoped_provenance = parse_attempt_provenance_for_attempt(
        marker.to_payload(),
        tenant_id=tenant_id,
        run_id=run_id,
        attempt_id=attempt_id,
    )
    assert scoped_provenance.retention_counts == marker.tombstone.counts

    lineage = project_resolved_input_lineage(
        resolved_inputs=parse_resolved_input_edges(None),
        scoped_attempt_provenance=scoped_provenance,
    )

    assert lineage.model_dump(mode="json") == {
        "status": "retention_purged",
        "resolved_input_aggregate_count": 1,
        "resolved_input_edge_count": 7,
    }


@pytest.mark.parametrize("mismatched_identity", ["tenant_id", "run_id", "attempt_id"])
def test_missing_lineage_does_not_trust_another_attempts_retention_marker(
    mismatched_identity: str,
) -> None:
    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    run_id = uuid4()
    attempt_id = uuid4()
    marker_identity = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "attempt_id": attempt_id,
    }
    marker_identity[mismatched_identity] = uuid4()
    marker = FlowAttemptRetentionMarker(
        tombstone=FlowRetentionTombstone(
            tenant_id=str(marker_identity["tenant_id"]),
            run_id=str(marker_identity["run_id"]),
            trace_id=str(uuid4()),
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=str(marker_identity["attempt_id"]),
            policy_source="tenant_policy",
            cutoff=now,
            counts=RunDebugAttemptRetentionCounts(
                cleared_field_count=3,
                provider_call_count=2,
                resolved_input_aggregate_count=1,
                resolved_input_edge_count=7,
            ),
            timestamp=now,
            retention_state="retention_purged",
        )
    )

    scoped_provenance = parse_attempt_provenance_for_attempt(
        marker.to_payload(),
        tenant_id=tenant_id,
        run_id=run_id,
        attempt_id=attempt_id,
    )
    lineage = project_resolved_input_lineage(
        resolved_inputs=parse_resolved_input_edges(None),
        scoped_attempt_provenance=scoped_provenance,
    )

    parse_result = scoped_provenance.parse_result
    assert parse_result.status == "corrupt"
    assert parse_result.marker is not None
    assert (
        parse_result.marker.error_code
        == "flow_attempt_provenance_invalid_retention_marker"
    )
    assert lineage.model_dump(mode="json") == {"status": "not_tracked"}


@pytest.mark.parametrize(
    "count_field",
    [
        "cleared_field_count",
        "provider_call_count",
        "resolved_input_aggregate_count",
        "resolved_input_edge_count",
    ],
)
def test_negative_attempt_retention_counts_are_corrupt(
    count_field: str,
) -> None:
    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    run_id = uuid4()
    attempt_id = uuid4()
    raw_marker = FlowAttemptRetentionMarker(
        tombstone=FlowRetentionTombstone(
            tenant_id=str(tenant_id),
            run_id=str(run_id),
            trace_id=str(uuid4()),
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=str(attempt_id),
            policy_source="tenant_policy",
            cutoff=now,
            counts=RunDebugAttemptRetentionCounts(
                cleared_field_count=3,
                provider_call_count=2,
                resolved_input_aggregate_count=1,
                resolved_input_edge_count=7,
            ),
            timestamp=now,
            retention_state="retention_purged",
        )
    ).to_payload()
    tombstone = raw_marker["tombstone"]
    assert isinstance(tombstone, dict)
    counts = tombstone["counts"]
    assert isinstance(counts, dict)
    counts[count_field] = -1

    scoped_provenance = parse_attempt_provenance_for_attempt(
        raw_marker,
        tenant_id=tenant_id,
        run_id=run_id,
        attempt_id=attempt_id,
    )
    lineage = project_resolved_input_lineage(
        resolved_inputs=parse_resolved_input_edges(None),
        scoped_attempt_provenance=scoped_provenance,
    )

    parse_result = scoped_provenance.parse_result
    assert parse_result.status == "corrupt"
    assert parse_result.marker is not None
    assert (
        parse_result.marker.error_code
        == "flow_attempt_provenance_invalid_retention_marker"
    )
    assert lineage.model_dump(mode="json") == {"status": "not_tracked"}


@pytest.mark.parametrize(
    "missing_tag",
    ["schema_version", "selector_kind", "source_kind", "selection_encoding"],
)
def test_parse_resolved_input_edges_rejects_missing_persisted_tags(
    missing_tag: str,
) -> None:
    payload = {"schema_version": 1, "edges": [_edge_payload()]}
    edge = payload["edges"][0]
    assert isinstance(edge, dict)
    source = edge["source"]
    selection = edge["selection"]
    assert isinstance(source, dict)
    assert isinstance(selection, dict)

    if missing_tag == "schema_version":
        payload.pop("schema_version")
    elif missing_tag == "selector_kind":
        selector = source["selector"]
        assert isinstance(selector, dict)
        selector.pop("kind")
    elif missing_tag == "source_kind":
        source.pop("kind")
    else:
        selection.pop("encoding")

    result = parse_resolved_input_edges(payload)

    assert result.status == "corrupt"
    assert result.aggregate is None
    assert result.marker is not None


def test_canonical_json_bytes_preserve_hash_serialization_contract() -> None:
    payload = {"z": "räksmörgås", "a": [1, True, None]}
    serialized = canonical_json_bytes(payload)

    assert serialized == b'{"a":[1,true,null],"z":"r\xc3\xa4ksm\xc3\xb6rg\xc3\xa5s"}'
    assert canonical_json_hash(payload) == hashlib.sha256(serialized).hexdigest()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_bytes_reject_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json_bytes({"value": value})
