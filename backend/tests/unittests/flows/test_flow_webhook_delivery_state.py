"""Where a run's outbound delivery stands, read from its outbox row: the one
rule the run's status and its detail answer with."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from eneo.database.tables.flow_tables import FlowOutboxDeliveryStatus
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    webhook_delivery_state,
)

NOW = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)
PAST = NOW - timedelta(minutes=1)
FUTURE = NOW + timedelta(minutes=5)


@pytest.mark.parametrize(
    ("attempts", "claim_expires_at", "next_delivery_at", "state"),
    [
        # Not tried yet.
        (0, None, PAST, "sending"),
        # The first attempt, while it is being sent.
        (1, FUTURE, PAST, "sending"),
        # A claim that ran out before its attempt was booked: the sender
        # takes it up again at once.
        (1, PAST, PAST, "sending"),
        # A failed attempt with the next one ahead.
        (1, None, FUTURE, "retry_scheduled"),
        (3, PAST, FUTURE, "retry_scheduled"),
        # The next attempt is due, so it is never shown as ahead.
        (2, None, PAST, "sending"),
        (2, None, NOW, "sending"),
        # A later attempt, while it is being sent.
        (2, FUTURE, PAST, "sending"),
    ],
)
def test_a_pending_delivery_is_retry_scheduled_only_between_attempts(
    attempts: int,
    claim_expires_at: datetime | None,
    next_delivery_at: datetime,
    state: str,
) -> None:
    assert (
        webhook_delivery_state(
            delivery_status=FlowOutboxDeliveryStatus.PENDING,
            delivery_attempts=attempts,
            claim_expires_at=claim_expires_at,
            next_delivery_at=next_delivery_at,
            now=NOW,
        )
        == state
    )


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (FlowOutboxDeliveryStatus.DELIVERED, "delivered"),
        (FlowOutboxDeliveryStatus.DEAD_LETTERED, "dead_lettered"),
    ],
)
def test_a_finished_delivery_keeps_its_status(
    status: FlowOutboxDeliveryStatus, state: str
) -> None:
    assert (
        webhook_delivery_state(
            delivery_status=status,
            delivery_attempts=2,
            claim_expires_at=None,
            next_delivery_at=None,
            now=NOW,
        )
        == state
    )
