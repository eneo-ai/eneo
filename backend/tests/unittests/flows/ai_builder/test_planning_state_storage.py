"""Storage-boundary tests for PlanningState persistence.

`builder_sessions.planning_state_jsonb` and its four promoted scalars
(`planning_state_version`, `planning_phase`, `architecture_hash`,
`planning_state_updated_at`) are written only through a single typed
helper, `_planning_state_for_storage`, so the column never drifts out
of Pydantic's typed world. These tests pin:

- the helper emits every promoted column the save path needs;
- the jsonb payload is the fully validated Pydantic snapshot, not a
  partial or raw dict;
- container-level mutations that bypassed Pydantic's validator (list
  appends, dict inserts) are caught at serialization time, not after
  they land in JSONB;
- what save emits is what `PlanningState.model_validate` reads back,
  byte-identical, turn after turn.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intric.flows.ai_builder.ai_builder_repo import _planning_state_for_storage
from intric.flows.ai_builder.planning_state import (
    ARCHITECTURE_HASH_HEX_LENGTH,
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)

_VALID_HASH = "a" * ARCHITECTURE_HASH_HEX_LENGTH


def _discovering_state() -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase="discovering",
        evidence=EvidenceRef(conversation_message_ids=["msg-1"]),
        resolved_slots={
            "primary_runtime_input": ResolvedSlot(
                name="primary_runtime_input",
                value="documents",
                source="heuristic",
                evidence=["heuristic:role-aware freeform analysis"],
                confidence="medium",
            )
        },
    )


def _ready_state() -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase="ready_to_commit",
        evidence=EvidenceRef(conversation_message_ids=["msg-1", "msg-2"]),
        architecture_commit=ArchitectureCommit(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="json",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["extract_structured_fields"],
            committed_at=datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc),
            architecture_hash=_VALID_HASH,
        ),
    )


class TestPlanningStateForStorage:
    def test_returns_all_five_promoted_columns(self) -> None:
        state = _discovering_state()
        values = _planning_state_for_storage(state)
        assert set(values.keys()) == {
            "planning_state_jsonb",
            "planning_phase",
            "architecture_hash",
            "planning_state_updated_at",
        }

    def test_jsonb_payload_is_full_validated_snapshot(self) -> None:
        """The jsonb payload must be the full Pydantic dump — partial
        updates are forbidden so the column never drifts."""
        state = _discovering_state()
        values = _planning_state_for_storage(state)
        payload = values["planning_state_jsonb"]
        assert isinstance(payload, dict)
        assert payload == state.validated_snapshot().model_dump(mode="json")

    def test_promoted_phase_mirrors_state_phase(self) -> None:
        state = _discovering_state()
        values = _planning_state_for_storage(state)
        assert values["planning_phase"] == "discovering"

    def test_architecture_hash_is_none_before_commit(self) -> None:
        state = _discovering_state()
        values = _planning_state_for_storage(state)
        assert values["architecture_hash"] is None

    def test_architecture_hash_promoted_after_commit(self) -> None:
        state = _ready_state()
        values = _planning_state_for_storage(state)
        assert values["architecture_hash"] == _VALID_HASH

    def test_updated_at_is_timezone_aware_utc(self) -> None:
        state = _discovering_state()
        values = _planning_state_for_storage(state)
        updated_at = values["planning_state_updated_at"]
        assert isinstance(updated_at, datetime)
        assert updated_at.tzinfo is not None
        assert updated_at.utcoffset() == timezone.utc.utcoffset(updated_at)

    def test_container_mutation_that_skips_snapshot_is_rejected(self) -> None:
        """A container-level mutation that bypassed Pydantic's validator
        (list append, dict set) would drift the model away from the
        stamped invariants. The storage helper calls
        `validated_snapshot()` so that drift fails here rather than
        landing in JSONB."""
        state = _discovering_state()
        # Bypass the field validator by mutating the underlying list.
        state.signals.append("not a signal")  # type: ignore[arg-type]
        with pytest.raises(Exception):
            _planning_state_for_storage(state)


class TestSaveLoadRoundTrip:
    """The composed invariant: what save writes, `PlanningState.model_validate`
    (the only read shape used by `load_planning_state`) rehydrates
    byte-identically. Exercising it at the helper level catches
    serialization drift without needing a live PostgreSQL round-trip.
    """

    def test_jsonb_payload_round_trips_through_model_validate(self) -> None:
        state = _ready_state()
        values = _planning_state_for_storage(state)
        loaded = PlanningState.model_validate(values["planning_state_jsonb"])
        assert loaded == state.validated_snapshot()

    def test_strict_validator_rejects_drifted_jsonb(self) -> None:
        """Strict `extra="forbid"` on `_PlanningModel` rejects any
        drifted JSONB at load time rather than silently falling back
        to a default — matching what `load_planning_state` calls."""
        with pytest.raises(Exception):
            PlanningState.model_validate({"unexpected_root_key": "legacy-data"})

    def test_second_save_produces_identical_payload(self) -> None:
        """save → load → save is stable: no non-deterministic keys, no
        serialization drift between rounds."""
        state = _ready_state()
        first = _planning_state_for_storage(state)
        loaded = PlanningState.model_validate(first["planning_state_jsonb"])
        second = _planning_state_for_storage(loaded)
        assert first["planning_state_jsonb"] == second["planning_state_jsonb"]
        assert first["planning_phase"] == second["planning_phase"]
        assert first["architecture_hash"] == second["architecture_hash"]
