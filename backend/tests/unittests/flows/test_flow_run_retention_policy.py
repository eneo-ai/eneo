from __future__ import annotations

import pytest
from pydantic import ValidationError

from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionPolicy,
    resolve_flow_run_retention_policy,
)


@pytest.mark.parametrize(
    ("space_days", "flow_days", "effective", "source"),
    [
        (30, 7, 7, "flow"),
        (30, 30, 30, "flow"),
        (30, 90, 30, "space"),
        (30, None, 30, "space"),
        (None, 7, 7, "flow"),
    ],
)
def test_the_space_time_caps_the_flow_time(
    space_days: int | None, flow_days: int | None, effective: int, source: str
) -> None:
    resolved = resolve_flow_run_retention_policy(
        space_days=space_days, flow_days=flow_days
    )

    assert resolved.state == "configured"
    assert resolved.effective_days == effective
    assert resolved.source == source
    assert resolved.contributors.model_dump(mode="json") == {
        "space": None if space_days is None else {"days": space_days},
        "flow": None if flow_days is None else {"days": flow_days},
    }


def test_no_time_has_an_explicit_off_projection() -> None:
    resolved = resolve_flow_run_retention_policy(space_days=None, flow_days=None)

    assert resolved.state == "off"
    assert resolved.effective_days is None
    assert resolved.source == "none"


@pytest.mark.parametrize(
    "payload", [{"mode": "preserve", "days": 30}, {"mode": "automatic", "days": 30}]
)
def test_a_policy_with_a_mode_is_refused(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FlowRunRetentionPolicy.model_validate(payload)


@pytest.mark.parametrize("days", [0, 2556])
def test_policy_days_follow_the_existing_retention_bounds(days: int) -> None:
    with pytest.raises(ValidationError):
        FlowRunRetentionPolicy(days=days)
