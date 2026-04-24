"""Failure-event coverage for AI Builder planner terminal outcomes.

These tests pin the "outcome but not the reason" gap closed by the
`log_failure_event` wiring. Each non-success `PlannerTurnResult.kind`
the production path emits must produce a structured failure event with
a stable schema — otherwise log queries and replay tooling lose their
grip on the failure taxonomy.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest

from intric.flows.ai_builder import ai_builder_planner
from intric.flows.ai_builder.ai_builder_orchestrator import RejectionReason
from intric.flows.ai_builder.ai_builder_planner import _emit_planner_failure_event


class _FakeTurnResult:
    def __init__(
        self,
        *,
        kind: str,
        rejection: RejectionReason | None = None,
    ) -> None:
        self.kind = kind
        self.rejection = rejection


@pytest.fixture
def captured() -> Iterator[tuple[logging.Logger, list[logging.LogRecord]]]:
    planner_logger: logging.Logger = ai_builder_planner.logger
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.msg == "failure_event":
                records.append(record)

    handler = _Capture()
    planner_logger.addHandler(handler)
    planner_logger.setLevel(logging.DEBUG)
    try:
        yield planner_logger, records
    finally:
        planner_logger.removeHandler(handler)


def _extras(record: logging.LogRecord, keys: list[str]) -> dict[str, Any]:
    return {k: getattr(record, k, None) for k in keys}


class TestParseFailedFailureEvent:
    def test_emits_event_with_required_fields(
        self,
        captured: tuple[logging.Logger, list[logging.LogRecord]],
    ) -> None:
        _, records = captured
        session_id = uuid4()
        tenant_id = uuid4()
        _emit_planner_failure_event(
            turn_result=_FakeTurnResult(kind="parse_failed"),
            request_id="req-abc",
            session_id=session_id,
            tenant_id=tenant_id,
            planning_state_version=7,
            planner_prompt_hash="abcd1234abcd1234",
            parse_failure_diagnostics={
                "parse_error_kind": "validation_error",
                "validation_locs": [
                    {"loc": "planner_action.type", "type": "literal_error"},
                ],
                "raw_sha256_prefix": "deadbeef",
            },
        )

        assert len(records) == 1
        rec = records[0]
        extras = _extras(
            rec,
            [
                "event",
                "component",
                "operation",
                "failure_kind",
                "failure_code",
                "failure_fingerprint",
                "request_id",
                "session_id",
                "tenant_id",
                "schema_version",
            ],
        )
        assert extras["event"] == "ai_builder.failure"
        assert extras["component"] == "ai_builder"
        assert extras["operation"] == "planner_turn"
        assert extras["failure_kind"] == "parse_failed"
        assert extras["failure_code"] == "validation_error"
        assert extras["failure_fingerprint"] is not None
        assert len(extras["failure_fingerprint"]) == 12
        assert extras["schema_version"] == 1
        assert extras["request_id"] == "req-abc"
        assert extras["session_id"] == str(session_id)
        assert extras["tenant_id"] == str(tenant_id)

    def test_replay_handle_carries_fingerprints_and_versions(
        self,
        captured: tuple[logging.Logger, list[logging.LogRecord]],
    ) -> None:
        _, records = captured
        _emit_planner_failure_event(
            turn_result=_FakeTurnResult(kind="parse_failed"),
            request_id=None,
            session_id=uuid4(),
            tenant_id=uuid4(),
            planning_state_version=12,
            planner_prompt_hash="prompt_hash_16ch",
            parse_failure_diagnostics={"parse_error_kind": "json_decode_error"},
        )
        replay: dict[str, Any] = getattr(records[0], "replay_handle")
        assert replay["planning_state_version"] == 12
        assert replay["planner_prompt_hash"] == "prompt_hash_16ch"
        assert "planner_output_schema_hash" in replay
        assert "pattern_registry_version" in replay
        assert "fcm_version" in replay
        assert "planner_contract_version" in replay
        assert "builder_schema_version" in replay

    def test_safe_detail_excludes_raw_body(
        self,
        captured: tuple[logging.Logger, list[logging.LogRecord]],
    ) -> None:
        _, records = captured
        _emit_planner_failure_event(
            turn_result=_FakeTurnResult(kind="parse_failed"),
            request_id=None,
            session_id=uuid4(),
            tenant_id=uuid4(),
            planning_state_version=1,
            planner_prompt_hash="x",
            parse_failure_diagnostics={
                "parse_error_kind": "validation_error",
                "raw_sha256_prefix": "cafebabe",
                "raw_length": 1296,
                "looks_like_markdown_fence": True,
            },
        )
        safe_detail: dict[str, Any] = getattr(records[0], "safe_detail")
        joined = " ".join(str(v).lower() for v in safe_detail.values())
        assert "raw_body" not in safe_detail
        assert "content" not in safe_detail
        assert "{" not in joined


class TestRejectedFailureEvent:
    def test_event_carries_rejection_code_as_failure_code(
        self,
        captured: tuple[logging.Logger, list[logging.LogRecord]],
    ) -> None:
        _, records = captured
        rejection = RejectionReason(
            code="duplicate_question",
            detail="planner re-asked question_id=foo without new evidence",
            current_version=3,
        )
        _emit_planner_failure_event(
            turn_result=_FakeTurnResult(kind="rejected", rejection=rejection),
            request_id="req-xyz",
            session_id=uuid4(),
            tenant_id=uuid4(),
            planning_state_version=3,
            planner_prompt_hash="prompt_hash",
            parse_failure_diagnostics={},
        )
        rec = records[0]
        assert getattr(rec, "failure_kind") == "rejected"
        assert getattr(rec, "failure_code") == "duplicate_question"
        safe_detail: dict[str, Any] = getattr(rec, "safe_detail")
        assert safe_detail["rejection_code"] == "duplicate_question"
        assert safe_detail["current_version"] == 3

    def test_fingerprint_clusters_same_code_same_locus(
        self,
        captured: tuple[logging.Logger, list[logging.LogRecord]],
    ) -> None:
        _, records = captured
        rejection = RejectionReason(
            code="version_mismatch",
            detail="planner submitted stale version",
            current_version=5,
        )
        for _ in range(2):
            _emit_planner_failure_event(
                turn_result=_FakeTurnResult(kind="rejected", rejection=rejection),
                request_id=None,
                session_id=uuid4(),
                tenant_id=uuid4(),
                planning_state_version=5,
                planner_prompt_hash="prompt",
                parse_failure_diagnostics={},
            )
        fp_a = getattr(records[0], "failure_fingerprint")
        fp_b = getattr(records[1], "failure_fingerprint")
        assert fp_a == fp_b
