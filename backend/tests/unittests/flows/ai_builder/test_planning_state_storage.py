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
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.ai_builder.ai_builder_repo import (
    AIBuilderRepository,
    _planning_state_for_storage,
)
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


class _StubSession:
    """The two session calls `load_planning_state` makes, with a canned row."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def in_transaction(self) -> bool:
        return True

    async def execute(self, _statement: object) -> "_StubResult":
        return _StubResult((uuid4(), self._payload))


class _StubResult:
    def __init__(self, row: tuple[object, object]) -> None:
        self._row = row

    def one_or_none(self) -> tuple[object, object]:
        return self._row


class TestLoadPlanningState:
    """The repository is the one owner of "this build does not read that state"."""

    @pytest.mark.asyncio
    async def test_a_payload_stamped_by_another_schema_version_loads_as_none(
        self,
    ) -> None:
        payload = _planning_state_for_storage(_ready_state())["planning_state_jsonb"]
        assert isinstance(payload, dict)
        payload["builder_schema_version"] = BUILDER_SCHEMA_VERSION - 1
        payload["field_this_build_never_had"] = ["x"]
        repo = AIBuilderRepository(cast(AsyncSession, _StubSession(payload)))

        loaded = await repo.load_planning_state(session_id=uuid4(), tenant_id=uuid4())

        assert loaded is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "drift",
        [
            {"builder_schema_version": None},
            {"builder_schema_version": "22"},
            {"builder_schema_version": True},
            {"field_this_build_never_had": ["x"]},
        ],
        ids=["missing_stamp", "malformed_stamp", "boolean_stamp", "extra_field"],
    )
    async def test_drift_under_the_current_version_fails_strict_validation(
        self,
        drift: dict[str, object],
    ) -> None:
        # A missing or malformed stamp is drift, never another version: it
        # reaches strict validation instead of reading as never saved.
        payload = _planning_state_for_storage(_ready_state())["planning_state_jsonb"]
        assert isinstance(payload, dict)
        for key, value in drift.items():
            if value is None:
                payload.pop(key, None)
            else:
                payload[key] = value
        repo = AIBuilderRepository(cast(AsyncSession, _StubSession(payload)))

        with pytest.raises(ValidationError):
            await repo.load_planning_state(session_id=uuid4(), tenant_id=uuid4())

    @pytest.mark.asyncio
    async def test_a_current_payload_loads(self) -> None:
        state = _ready_state()
        payload = _planning_state_for_storage(state)["planning_state_jsonb"]
        repo = AIBuilderRepository(cast(AsyncSession, _StubSession(payload)))

        loaded = await repo.load_planning_state(session_id=uuid4(), tenant_id=uuid4())

        assert loaded == state.validated_snapshot()
