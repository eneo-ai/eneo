from __future__ import annotations

from eneo.flows.domain.flow_run_input_revision import (
    build_flow_run_input_revision,
    canonical_input_hash,
    changed_input_paths,
)

# --- canonical_input_hash ---


def test_hash_ignores_key_order() -> None:
    assert canonical_input_hash({"a": 1, "b": 2}) == canonical_input_hash(
        {"b": 2, "a": 1}
    )


def test_hash_distinguishes_absent_payload_from_empty_one() -> None:
    assert canonical_input_hash(None) != canonical_input_hash({})


def test_hash_changes_when_a_value_changes() -> None:
    assert canonical_input_hash({"a": 1}) != canonical_input_hash({"a": 2})


# --- changed_input_paths ---


def test_changed_paths_names_the_changed_field() -> None:
    prior = {"subject": "old", "body": "same"}
    resulting = {"subject": "new", "body": "same"}

    assert changed_input_paths(prior, resulting) == ("subject",)


def test_changed_paths_reports_added_and_removed_keys() -> None:
    assert changed_input_paths({"a": 1}, {"b": 2}) == ("a", "b")


def test_changed_paths_walks_nested_objects() -> None:
    prior = {"applicant": {"name": "Alice", "id": "1"}}
    resulting = {"applicant": {"name": "Bob", "id": "1"}}

    assert changed_input_paths(prior, resulting) == ("applicant.name",)


def test_changed_paths_distinguishes_missing_key_from_explicit_null() -> None:
    assert changed_input_paths({}, {"a": None}) == ("a",)


def test_changed_paths_compares_lists_whole() -> None:
    prior = {"tags": ["a", "b"]}
    resulting = {"tags": ["b", "a"]}

    assert changed_input_paths(prior, resulting) == ("tags",)


def test_unchanged_payload_reports_no_paths() -> None:
    payload = {"a": 1, "nested": {"b": 2}}

    assert changed_input_paths(payload, dict(payload)) == ()


# --- build_flow_run_input_revision ---


def test_revision_keeps_the_prior_payload_not_the_resulting_one() -> None:
    revision = build_flow_run_input_revision(
        prior={"subject": "v0"},
        resulting={"subject": "v1"},
    )

    assert revision.prior_input_payload == {"subject": "v0"}
    assert revision.changed_paths == ("subject",)
    assert revision.changed


def test_revision_of_an_unchanged_payload_is_marked_unchanged() -> None:
    revision = build_flow_run_input_revision(
        prior={"subject": "v0"},
        resulting={"subject": "v0"},
    )

    assert not revision.changed
    assert revision.changed_paths == ()
    assert revision.prior_input_hash == revision.resulting_input_hash


def test_two_reruns_over_disjoint_fields_reconstruct_every_revision_in_order() -> None:
    """The chain v0 -> v1 -> v2 must be rebuildable from the stored priors.

    Each rerun stores the payload it replaced, so walking the reruns in order
    and finishing at the run's current payload yields every revision.
    """
    v0 = {"subject": "original", "body": "original"}
    v1 = {"subject": "edited", "body": "original"}
    v2 = {"subject": "edited", "body": "edited"}

    first = build_flow_run_input_revision(prior=v0, resulting=v1)
    second = build_flow_run_input_revision(prior=v1, resulting=v2)

    reconstructed = [first.prior_input_payload, second.prior_input_payload, v2]
    assert reconstructed == [v0, v1, v2]

    assert first.changed_paths == ("subject",)
    assert second.changed_paths == ("body",)
    # The chain links: what the first rerun produced is what the second replaced.
    assert first.resulting_input_hash == second.prior_input_hash


def test_unchanged_values_stay_hash_provably_unchanged_across_reruns() -> None:
    v0 = {"subject": "original", "body": "keep"}
    v1 = {"subject": "edited", "body": "keep"}

    revision = build_flow_run_input_revision(prior=v0, resulting=v1)

    assert "body" not in revision.changed_paths
    assert canonical_input_hash({"body": v0["body"]}) == canonical_input_hash(
        {"body": v1["body"]}
    )
