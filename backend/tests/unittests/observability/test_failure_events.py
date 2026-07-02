"""Tests for the stable-schema failure-event contract.

These tests pin the wire shape callers (AI Builder, flows runtime, worker
jobs) rely on. A regression here is a breaking change for log queries
and replay tooling, so the tests assert field names, types, and the
core-schema-wins-on-collision rule explicitly.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from eneo.observability.failure_events import (
    FAILURE_EVENT_SCHEMA_VERSION,
    log_failure_event,
    make_failure_fingerprint,
    schema_fingerprint,
    stable_hash,
)


class _RecordingHandler(logging.Handler):
    """In-memory handler that captures `LogRecord` objects verbatim."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured_logger() -> tuple[logging.Logger, _RecordingHandler]:
    logger = logging.getLogger("test.observability.failure_events")
    logger.handlers.clear()
    handler = _RecordingHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, handler


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    """Extract the caller-passed `extra=` payload off a `LogRecord`.

    The stdlib mixes extras with built-in LogRecord attributes. We only
    care about the fields `log_failure_event` wrote, so we intersect
    against the required schema keys.
    """
    expected = {
        "event",
        "schema_version",
        "component",
        "operation",
        "failure_kind",
        "failure_code",
        "failure_fingerprint",
        "request_id",
        "session_id",
        "tenant_id",
        "replay_handle",
        "safe_detail",
    }
    return {k: getattr(record, k) for k in expected if hasattr(record, k)}


class TestLogFailureEvent:
    def test_emits_all_core_fields(
        self,
        captured_logger: tuple[logging.Logger, _RecordingHandler],
    ) -> None:
        logger, handler = captured_logger
        log_failure_event(
            logger,
            event="ai_builder.failure",
            component="ai_builder",
            operation="planner_turn",
            failure_kind="parse_failed",
            failure_code="validation_error",
            failure_fingerprint="abc123def456",
            request_id="req-1",
            session_id="sess-1",
            tenant_id="tenant-1",
            replay_handle={"session_id": "sess-1", "planning_state_version": 3},
            safe_detail={
                "parse_error_kind": "validation_error",
                "locs": ["planner_action.type"],
            },
        )

        assert len(handler.records) == 1
        extras = _extras(handler.records[0])
        assert extras == {
            "event": "ai_builder.failure",
            "schema_version": FAILURE_EVENT_SCHEMA_VERSION,
            "component": "ai_builder",
            "operation": "planner_turn",
            "failure_kind": "parse_failed",
            "failure_code": "validation_error",
            "failure_fingerprint": "abc123def456",
            "request_id": "req-1",
            "session_id": "sess-1",
            "tenant_id": "tenant-1",
            "replay_handle": {"session_id": "sess-1", "planning_state_version": 3},
            "safe_detail": {
                "parse_error_kind": "validation_error",
                "locs": ["planner_action.type"],
            },
        }
        assert handler.records[0].msg == "failure_event"

    def test_optional_fields_default_to_none(
        self,
        captured_logger: tuple[logging.Logger, _RecordingHandler],
    ) -> None:
        logger, handler = captured_logger
        log_failure_event(
            logger,
            event="flows.failure",
            component="flows",
            operation="flow_dispatch",
            failure_kind="upstream_error",
        )

        extras = _extras(handler.records[0])
        assert extras["failure_code"] is None
        assert extras["failure_fingerprint"] is None
        assert extras["request_id"] is None
        assert extras["session_id"] is None
        assert extras["tenant_id"] is None
        assert extras["replay_handle"] is None
        assert extras["safe_detail"] is None

    def test_extra_cannot_shadow_core_fields(
        self,
        captured_logger: tuple[logging.Logger, _RecordingHandler],
    ) -> None:
        logger, handler = captured_logger
        log_failure_event(
            logger,
            event="ai_builder.failure",
            component="ai_builder",
            operation="planner_turn",
            failure_kind="rejected",
            extra={
                "event": "HIJACKED",
                "failure_kind": "HIJACKED",
                "caller_field": "ok",
            },
        )

        extras = _extras(handler.records[0])
        assert extras["event"] == "ai_builder.failure"
        assert extras["failure_kind"] == "rejected"
        assert getattr(handler.records[0], "caller_field") == "ok"


class TestMakeFailureFingerprint:
    def test_same_parts_hash_to_same_digest(self) -> None:
        a = make_failure_fingerprint(
            "parse_failed", "validation_error", "planner_action.type"
        )
        b = make_failure_fingerprint(
            "parse_failed", "validation_error", "planner_action.type"
        )
        assert a == b

    def test_different_parts_hash_to_different_digests(self) -> None:
        a = make_failure_fingerprint("parse_failed", "validation_error", "action.a")
        b = make_failure_fingerprint("parse_failed", "validation_error", "action.b")
        assert a != b

    def test_digest_is_twelve_hex_chars(self) -> None:
        fp = make_failure_fingerprint("parse_failed", "validation_error")
        assert len(fp) == 12
        assert all(c in "0123456789abcdef" for c in fp)

    def test_none_segments_are_empty_strings_not_repr(self) -> None:
        with_none = make_failure_fingerprint("parse_failed", None, "action.a")
        with_empty = make_failure_fingerprint("parse_failed", "", "action.a")
        assert with_none == with_empty

        with_literal_none = make_failure_fingerprint("parse_failed", "None", "action.a")
        assert with_none != with_literal_none


class TestStableHash:
    def test_deterministic(self) -> None:
        value = "system prompt with some specific content"
        assert stable_hash(value) == stable_hash(value)

    def test_digest_is_sixteen_hex_chars(self) -> None:
        digest = stable_hash("anything")
        assert len(digest) == 16
        assert all(c in "0123456789abcdef" for c in digest)

    def test_different_values_differ(self) -> None:
        assert stable_hash("foo") != stable_hash("bar")


class TestSchemaFingerprint:
    def test_order_independent(self) -> None:
        schema_a: dict[str, Any] = {
            "title": "PlannerOutput",
            "type": "object",
            "properties": {"kind": {"type": "string"}, "payload": {"type": "object"}},
        }
        schema_b: dict[str, Any] = {
            "properties": {"payload": {"type": "object"}, "kind": {"type": "string"}},
            "type": "object",
            "title": "PlannerOutput",
        }
        assert schema_fingerprint(schema_a) == schema_fingerprint(schema_b)

    def test_changes_on_field_addition(self) -> None:
        before: dict[str, Any] = {"type": "object", "properties": {"a": {}}}
        after: dict[str, Any] = {"type": "object", "properties": {"a": {}, "b": {}}}
        assert schema_fingerprint(before) != schema_fingerprint(after)

    def test_matches_manual_canonical_hash(self) -> None:
        schema: dict[str, Any] = {"z": 1, "a": 2}
        expected = stable_hash(
            json.dumps(schema, sort_keys=True, separators=(",", ":"))
        )
        assert schema_fingerprint(schema) == expected
