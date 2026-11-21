from __future__ import annotations

import pytest

from eneo.flows.domain.run_deliverables import (
    StepDeliverableFacts,
    deliverable_positions,
)


def _step(output_type: str, output_mode: str = "pass_through", *, marked: bool = False):
    return StepDeliverableFacts(
        output_type=output_type, output_mode=output_mode, marked=marked
    )


@pytest.mark.parametrize(
    ("steps", "positions"),
    [
        ([], []),
        ([_step("text")], [0]),
        ([_step("json")], []),
        ([_step("text"), _step("pdf", "render_verbatim")], [1]),
        ([_step("docx", marked=True), _step("text")], [0, 1]),
        ([_step("docx", marked=True), _step("docx")], [0, 1]),
        ([_step("pdf"), _step("json")], []),
        ([_step("text", marked=True), _step("json")], [0]),
        ([_step("docx", "http_post", marked=True)], []),
        ([_step("text", "http_post", marked=True)], []),
    ],
)
def test_marked_steps_and_the_last_step_are_delivered_when_they_can_be(
    steps: list[StepDeliverableFacts], positions: list[int]
) -> None:
    assert deliverable_positions(steps) == positions
