"""Reading the actor snapshots stored on a legal hold (created_by_actor, released_by_actor).

Only type, id and name reach the API; anything unreadable is shown as no actor,
never as an error.
"""

from __future__ import annotations

import pytest

from eneo.flows.domain.flow_retention_hold import (
    FlowRetentionHoldActor,
    flow_retention_hold_actor,
)


def test_a_user_snapshot_is_narrowed_to_type_id_and_name() -> None:
    snapshot = {"type": "user", "id": "u-1", "name": "anna", "email": "a@x.se"}
    assert flow_retention_hold_actor(snapshot) == FlowRetentionHoldActor(
        type="user", id="u-1", name="anna"
    )


def test_a_service_key_snapshot_keeps_its_name_without_an_email() -> None:
    snapshot = {"type": "service_key", "id": "k-1", "name": "ci", "key_prefix": "sk"}
    assert flow_retention_hold_actor(snapshot) == FlowRetentionHoldActor(
        type="service_key", id="k-1", name="ci"
    )


@pytest.mark.parametrize(
    "snapshot",
    [None, {}, [], ["user"], "user", 1, {"type": None}, {"type": ""}, {"type": 3}],
)
def test_an_unreadable_snapshot_is_no_actor(snapshot: object) -> None:
    assert flow_retention_hold_actor(snapshot) is None


def test_missing_or_mistyped_id_and_name_are_absent() -> None:
    assert flow_retention_hold_actor({"type": "user", "id": 5}) == (
        FlowRetentionHoldActor(type="user", id=None, name=None)
    )
