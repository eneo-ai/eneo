from __future__ import annotations

import json

from intric.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from intric.flows.ai_builder.ai_builder_events import encode_ai_builder_stream_event
from intric.flows.ai_builder.ai_builder_planner_failure_events import (
    build_planner_upstream_error_event,
    build_session_send_lease_lost_event,
)


def test_build_session_send_lease_lost_event_uses_stable_error_contract() -> None:
    event = build_session_send_lease_lost_event(request_id="req-lock")
    wire_event = encode_ai_builder_stream_event(event)
    data = json.loads(wire_event["data"])

    assert wire_event["event"] == "error"
    assert data["code"] == AIBuilderErrorCode.SESSION_SEND_LEASE_LOST.value
    assert data["request_id"] == "req-lock"


def test_build_planner_upstream_error_event_uses_stable_error_contract() -> None:
    event = build_planner_upstream_error_event(request_id="req-upstream")
    wire_event = encode_ai_builder_stream_event(event)
    data = json.loads(wire_event["data"])

    assert wire_event["event"] == "error"
    assert data["code"] == AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR.value
    assert data["request_id"] == "req-upstream"
