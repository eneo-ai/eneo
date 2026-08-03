"""Storage-boundary tests for PlanningState persistence.

`builder_sessions.planning_state_jsonb` is written only through a single
typed helper, `_planning_state_for_storage`, so the column never drifts
out of Pydantic's typed world. These tests pin:

- the helper emits the JSONB column the save path needs;
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

from eneo.flows.ai_builder.ai_builder_repo import _planning_state_for_storage
from eneo.flows.ai_builder.planning_state import (
    ARCHITECTURE_HASH_HEX_LENGTH,
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)

_VALID_HASH = "a" * ARCHITECTURE_HASH_HEX_LENGTH


def _state_with_resolved_slot() -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        resolved_slots={
            "primary_runtime_input": ResolvedSlot(
                name="primary_runtime_input",
                value="documents",
                source="model",
                evidence=[
                    "model:primary_runtime_input:prompt-hash",
                    "quote:user_message:test:documents",
                ],
                confidence="medium",
                evidence_level="explicit",
            )
        },
    )


def _ready_state() -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
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
    def test_returns_jsonb_column(self) -> None:
        state = _state_with_resolved_slot()
        values = _planning_state_for_storage(state)
        assert set(values.keys()) == {"planning_state_jsonb"}

    def test_jsonb_payload_is_full_validated_snapshot(self) -> None:
        """The jsonb payload must be the full Pydantic dump — partial
        updates are forbidden so the column never drifts."""
        state = _state_with_resolved_slot()
        values = _planning_state_for_storage(state)
        payload = values["planning_state_jsonb"]
        assert isinstance(payload, dict)
        assert payload == state.validated_snapshot().model_dump(mode="json")

    def test_container_mutation_that_skips_snapshot_is_rejected(self) -> None:
        """A container-level mutation that bypassed Pydantic's validator
        (list append, dict set) would drift the model away from the
        stamped invariants. The storage helper calls
        `validated_snapshot()` so that drift fails here rather than
        landing in JSONB."""
        state = _state_with_resolved_slot()
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
        state = _state_with_resolved_slot()
        values = _planning_state_for_storage(state)
        loaded = PlanningState.model_validate(values["planning_state_jsonb"])
        assert loaded == state.validated_snapshot()

    def test_render_verbatim_output_mode_round_trips(self) -> None:
        state = PlanningState(
            fcm_version=FCM_VERSION,
            planner_contract_version=PLANNER_CONTRACT_VERSION,
            builder_schema_version=BUILDER_SCHEMA_VERSION,
            architecture_commit=ArchitectureCommit(
                tuples_chain=[
                    StepTriple(
                        input_type="text",
                        output_type="pdf",
                        output_mode="render_verbatim",
                    )
                ],
                chosen_patterns=["text_to_artifact_report"],
                committed_at=datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc),
                architecture_hash=_VALID_HASH,
            ),
        )

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
