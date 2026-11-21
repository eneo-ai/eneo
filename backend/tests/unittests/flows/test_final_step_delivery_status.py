"""Where a run's sent result stands is the status of the final step's highest
numbered delivery attempt, whatever order the attempts are read in."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.database.tables.flow_tables import FlowOutboxDeliveryStatus
from eneo.flows.api.flow_run_contract_models import (
    FlowFinalOutputContractPublic,
    FlowRunOutputContract,
    final_step_delivery_status,
)
from eneo.flows.enums import FlowOutputDelivery, FlowOutputMode, FlowOutputType

DELIVERED = FlowOutboxDeliveryStatus.DELIVERED
DEAD = FlowOutboxDeliveryStatus.DEAD_LETTERED
PENDING = FlowOutboxDeliveryStatus.PENDING


def _outputs(step_id, delivery=FlowOutputDelivery.OUTBOUND_HTTP):
    return FlowRunOutputContract(
        final_output=FlowFinalOutputContractPublic(
            step_id=step_id,
            step_order=2,
            output_type=FlowOutputType.TEXT,
            output_mode=FlowOutputMode.HTTP_POST,
            delivery=delivery,
        ),
        deliverables=(),
    )


@pytest.mark.parametrize(
    "attempts",
    [
        [(1, DEAD), (2, PENDING), (3, DELIVERED)],
        [(3, DELIVERED), (1, DEAD), (2, PENDING)],
        [(2, PENDING), (3, DELIVERED), (1, DEAD)],
    ],
)
def test_the_highest_attempt_of_the_final_step_decides(attempts):
    final, earlier = uuid4(), uuid4()
    rows = [(final, attempt_no, status) for attempt_no, status in attempts]
    # An earlier step's later attempt says nothing about the final step.
    rows.insert(1, (earlier, 9, PENDING))

    assert final_step_delivery_status(_outputs(final), rows) is DELIVERED


def test_a_final_step_without_a_delivery_has_no_status():
    final = uuid4()
    assert final_step_delivery_status(_outputs(final), []) is None
    assert final_step_delivery_status(_outputs(final), [(uuid4(), 1, DEAD)]) is None
    assert final_step_delivery_status(None, [(final, 1, DEAD)]) is None


def test_a_final_step_that_sends_nothing_has_no_status():
    final = uuid4()
    outputs = _outputs(final, delivery=FlowOutputDelivery.PAYLOAD)
    assert final_step_delivery_status(outputs, [(final, 1, DEAD)]) is None
