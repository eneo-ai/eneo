"""Behavior matrix for the citation summary projection.

The projection is the single owner of the review-surface citation contract:
status precedence, off-versus-unavailable honesty, identity resolution,
truncation, and staleness. These tests cover the public status and
resolution matrix directly with minimal domain models, without a database.
"""

from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.application.citation_summary_projection import (
    build_citation_summary,
    citation_grounded_step_orders,
)
from eneo.flows.domain.flow import FlowStepAttempt, FlowStepResult
from eneo.flows.enums import FlowStepAttemptStatus, FlowStepResultStatus
from eneo.flows.flow_run_provenance import FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION

_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
_CITATIONS_ON = {"citation_mode": "inline_inref_sidecar"}


def _attempt(
    citations: dict[str, object] | None,
    *,
    step_order: int = 2,
) -> FlowStepAttempt:
    provenance: dict[str, object] = {
        "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
    }
    if citations is not None:
        provenance["citations"] = citations
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        attempt_no=1,
        status=FlowStepAttemptStatus.COMPLETED,
        provenance_json=provenance,
        started_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _sidecar(
    *,
    cited: list[str],
    unknown: list[str] | None = None,
    compliance: str = "observed",
    grounded: list[int] | None = None,
) -> dict[str, object]:
    return {
        "citation_compliance": compliance,
        "cited_source_ids": cited,
        "unknown_citation_ids": unknown or [],
        "upstream_grounded_step_orders": grounded or [],
    }


def _result(
    sources: list[dict[str, object]] | None,
    *,
    step_order: int = 2,
) -> FlowStepResult:
    return FlowStepResult(
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        status=FlowStepResultStatus.COMPLETED,
        input_payload_json=(
            {"rag": {"citation_sources": sources}} if sources is not None else None
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _source(source_id: str, name: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {"id": source_id}
    if name is not None:
        entry["source_display_name"] = name
    return entry


def test_citations_off_produces_no_summary() -> None:
    assert (
        build_citation_summary(
            output_config={},
            current_attempt=_attempt(_sidecar(cited=["a"])),
            step_result=_result([_source("a", "Doc")]),
        )
        is None
    )


def test_citations_on_without_decodable_provenance_is_unavailable_not_off() -> None:
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(None),
        step_result=_result([_source("a", "Doc")]),
    )
    assert summary is not None
    assert summary.status == "unavailable"


def test_direct_source_resolution_observed() -> None:
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(_sidecar(cited=["a"])),
        step_result=_result([_source("a", "Direct doc")]),
    )
    assert summary is not None
    assert summary.status == "observed"
    assert summary.matched_cited_source_count == 1
    assert summary.sources[0].identity_resolved is True
    assert summary.sources[0].display_name == "Direct doc"


def test_inherited_source_resolution_from_named_upstream_only() -> None:
    upstream_named = _result([_source("up", "Upstream doc")], step_order=1)
    upstream_unnamed = _result([_source("other", "Unrelated doc")], step_order=3)
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(_sidecar(cited=["up", "other"], grounded=[1])),
        step_result=_result([]),
        upstream_step_results=[upstream_unnamed, upstream_named],
    )
    assert summary is not None
    # "up" resolves through the grounded step; "other" lives on a step the
    # sidecar does not name, so its identity stays unresolved even though the
    # citation itself still counts.
    assert summary.matched_cited_source_count == 2
    by_name = {source.display_name for source in summary.sources}
    assert "Upstream doc" in by_name
    assert "Unrelated doc" not in by_name
    assert any(not source.identity_resolved for source in summary.sources)


def test_mixed_direct_and_inherited_resolution() -> None:
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(_sidecar(cited=["a", "up"], grounded=[1])),
        step_result=_result([_source("a", "Direct doc")]),
        upstream_step_results=[_result([_source("up", "Upstream doc")], step_order=1)],
    )
    assert summary is not None
    assert summary.matched_cited_source_count == 2
    assert {source.display_name for source in summary.sources} == {
        "Direct doc",
        "Upstream doc",
    }


def test_unknown_ids_take_precedence_even_without_sources() -> None:
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(
            _sidecar(
                cited=[], unknown=["ghost"], compliance="unknown_citation_ids_present"
            )
        ),
        step_result=_result(None),
    )
    assert summary is not None
    assert summary.status == "unknown_citation_ids_present"


def test_missing_required_precedence_over_no_sources() -> None:
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(
            _sidecar(cited=[], compliance="missing_required_citations")
        ),
        step_result=_result(None),
    )
    assert summary is not None
    assert summary.status == "missing_required_citations"


def test_citations_on_without_any_sources_is_its_own_state() -> None:
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(_sidecar(cited=[], compliance="observed")),
        step_result=_result(None),
    )
    assert summary is not None
    assert summary.status == "citations_on_without_sources"


def test_unresolved_identity_still_counts_as_matched() -> None:
    # A cited id with no recoverable display identity is still a matched
    # runtime-validated citation — the old projection reported it as zero.
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(_sidecar(cited=["a"])),
        step_result=_result([]),
    )
    assert summary is not None
    assert summary.matched_cited_source_count == 1
    assert summary.sources[0].identity_resolved is False
    assert summary.sources[0].display_name is None


def test_truncation_keeps_a_possible_denominator() -> None:
    cited = [f"source-{index}" for index in range(21)]
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(_sidecar(cited=cited)),
        step_result=_result(
            [_source(source_id, f"Doc {source_id}") for source_id in cited]
        ),
    )
    assert summary is not None
    assert len(summary.sources) == 20
    assert summary.sources_truncated is True
    # The shown count can never exceed the matched total.
    assert summary.matched_cited_source_count == 21


def test_blank_cited_id_makes_the_sidecar_undecodable() -> None:
    summary = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=_attempt(_sidecar(cited=[" "])),
        step_result=_result([]),
    )
    assert summary is not None
    assert summary.status == "unavailable"


def test_stale_after_edit_flips_with_checkpoint_edit() -> None:
    attempt = _attempt(_sidecar(cited=["a"]))
    fresh = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=attempt,
        step_result=_result([_source("a", "Doc")]),
    )
    stale = build_citation_summary(
        output_config=_CITATIONS_ON,
        current_attempt=attempt,
        step_result=_result([_source("a", "Doc")]),
        edited_at=_NOW,
    )
    assert fresh is not None and fresh.stale_after_edit is False
    assert stale is not None and stale.stale_after_edit is True


def test_unknown_config_with_sidecar_projects_from_runtime_truth() -> None:
    # Unverified definition integrity: the pinned configuration cannot be
    # established. The sidecar's presence proves citations were on at run
    # time, so the summary must not vanish as if citations were off.
    summary = build_citation_summary(
        output_config=None,
        config_known=False,
        current_attempt=_attempt(_sidecar(cited=["a"])),
        step_result=_result([_source("a", "Doc")]),
    )
    assert summary is not None
    assert summary.status == "observed"


def test_unknown_config_without_sidecar_supports_no_claim() -> None:
    # With neither configuration nor runtime evidence there is nothing honest
    # to assert — absence, not a fabricated "unavailable" on every step.
    assert (
        build_citation_summary(
            output_config=None,
            config_known=False,
            current_attempt=_attempt(None),
            step_result=_result(None),
        )
        is None
    )


def test_grounded_step_orders_are_deduplicated_and_sorted() -> None:
    attempt = _attempt(_sidecar(cited=[], grounded=[3, 1, 3]))
    assert citation_grounded_step_orders(attempt) == (1, 3)
