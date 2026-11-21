from __future__ import annotations

import pytest

from eneo.flows.domain.run_deliverables import (
    StepDeliverableFacts,
    deliverable_positions,
)


def _step(
    output_type: str,
    output_mode: str = "pass_through",
    *,
    marked: bool = False,
    sends_run_result: bool = False,
):
    return StepDeliverableFacts(
        output_type=output_type,
        output_mode=output_mode,
        marked=marked,
        sends_run_result=sends_run_result,
    )


def _send() -> StepDeliverableFacts:
    return _step("text", "http_post", sends_run_result=True)


def _post() -> StepDeliverableFacts:
    return _step("text", "http_post")


def _word(*, marked: bool = False) -> StepDeliverableFacts:
    return _step("docx", "render_verbatim", marked=marked)


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


@pytest.mark.parametrize(
    ("steps", "positions"),
    [
        # The step before the one that sends the run's result is its result.
        ([_step("text"), _send()], [0]),
        ([_word(), _send()], [0]),
        # A step before it that cannot be delivered is passed over in silence.
        ([_step("text"), _step("json"), _send()], []),
        ([_step("text", marked=True), _step("json"), _send()], [0]),
        # A plain request is never skipped: it is last, and sends itself.
        ([_word(), _post()], []),
        ([_send()], []),
        # Marked steps come once, in published order, beside the last one.
        ([_word(marked=True), _word(marked=True), _send()], [0, 1]),
    ],
)
def test_the_step_before_the_one_that_sends_the_result_is_delivered(
    steps: list[StepDeliverableFacts], positions: list[int]
) -> None:
    assert deliverable_positions(steps) == positions


@pytest.mark.parametrize(
    ("text_marked", "count"),
    [(False, 2), (True, 3)],
)
def test_markdown_then_two_word_documents_then_the_result(
    text_marked: bool, count: int
) -> None:
    """Word 1 is kept with "Behåll"; Word 2 stands before the step that
    sends. The markdown is sent only when it is kept too."""
    steps = [_step("text", marked=text_marked), _word(marked=True), _word(), _send()]

    positions = deliverable_positions(steps)

    assert len(positions) == count
    assert positions == ([0, 1, 2] if text_marked else [1, 2])
