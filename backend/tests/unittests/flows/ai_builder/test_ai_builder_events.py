from __future__ import annotations

import json

from intric.flows.ai_builder.ai_builder_api_models import SessionTelemetrySummary
from intric.flows.ai_builder.ai_builder_events import (
    build_done_event,
    build_usage_event,
)


def test_done_event_preserves_empty_data_frame() -> None:
    assert build_done_event() == {"event": "done", "data": ""}


def test_usage_event_serializes_typed_telemetry() -> None:
    telemetry = SessionTelemetrySummary(
        planner_request_count=1,
        prompt_tokens_total=120,
        completion_tokens_total=30,
        total_tokens_total=150,
        last_request_id="request-1",
        last_model="gpt-5.4",
    )

    event = build_usage_event(telemetry)

    assert event["event"] == "usage"
    data = json.loads(event["data"])
    assert data["planner_request_count"] == 1
    assert data["total_tokens_total"] == 150
    assert data["last_request_id"] == "request-1"
    assert data["last_model"] == "gpt-5.4"
