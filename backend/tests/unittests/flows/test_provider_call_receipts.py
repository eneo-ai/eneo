from __future__ import annotations

from eneo.ai_models.completion_models.completion_model import (
    ProviderDispatch,
    TokenUsage,
)
from eneo.flows.runtime.step_execution_runtime import build_provider_call_receipts


def _build(dispatches, **overrides):
    kwargs = dict(
        dispatches=dispatches,
        fallback_provider_response_id="resp-aggregate",
        first_call_index=1,
        aggregate_num_tokens_input=100,
        aggregate_num_tokens_output=40,
        aggregate_input_source="provider",
        aggregate_output_source="provider",
        requested_model="gpt-x",
        response_model="gpt-x-2026",
        provider="openai",
        mapped_call=None,
    )
    kwargs.update(overrides)
    return build_provider_call_receipts(**kwargs)


def test_tool_rounds_produce_one_receipt_per_billed_request() -> None:
    """Two dispatches were billed, so two receipts must exist."""
    receipts = _build(
        (
            ProviderDispatch(
                ordinal=1,
                provider_response_id="resp-1",
                usage=TokenUsage(prompt_tokens=60, completion_tokens=10),
                reason="initial",
            ),
            ProviderDispatch(
                ordinal=2,
                provider_response_id="resp-2",
                usage=TokenUsage(prompt_tokens=40, completion_tokens=30),
                reason="tool_round",
            ),
        )
    )

    assert [r.call_index for r in receipts] == [1, 2]
    assert [r.provider_response_id for r in receipts] == ["resp-1", "resp-2"]
    assert [r.num_tokens_input for r in receipts] == [60, 40]
    assert [r.num_tokens_output for r in receipts] == [10, 30]


def test_per_dispatch_receipts_continue_the_step_call_numbering() -> None:
    receipts = _build(
        (
            ProviderDispatch(ordinal=1, reason="initial"),
            ProviderDispatch(ordinal=2, reason="tool_round"),
        ),
        first_call_index=4,
    )

    assert [r.call_index for r in receipts] == [4, 5]


def test_dispatch_without_reported_usage_is_unknown_not_estimated() -> None:
    """An unreported per-dispatch share is unknown; estimating it would invent it."""
    receipts = _build(
        (
            ProviderDispatch(ordinal=1, reason="initial"),
            ProviderDispatch(ordinal=2, reason="tool_round"),
        )
    )

    assert all(r.input_source == "not_reported" for r in receipts)
    assert all(r.output_source == "not_reported" for r in receipts)
    assert all(r.num_tokens_input is None for r in receipts)
    assert all(r.num_tokens_output is None for r in receipts)


def test_provider_reported_zero_is_preserved_as_measured_zero() -> None:
    receipts = _build(
        (
            ProviderDispatch(
                ordinal=1,
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
                reason="initial",
            ),
            ProviderDispatch(
                ordinal=2,
                usage=TokenUsage(prompt_tokens=4, completion_tokens=2),
                reason="tool_round",
            ),
        )
    )

    assert receipts[0].num_tokens_input == 0
    assert receipts[0].num_tokens_output == 0
    assert receipts[0].input_source == "provider"
    assert receipts[0].output_source == "provider"


def test_adapter_reporting_no_dispatches_still_yields_the_aggregate_receipt() -> None:
    """Adapters that do not report dispatches keep the previous behavior."""
    receipts = _build(())

    assert len(receipts) == 1
    assert receipts[0].call_index == 1
    assert receipts[0].num_tokens_input == 100
    assert receipts[0].num_tokens_output == 40
    assert receipts[0].input_source == "provider"
    assert receipts[0].provider_response_id == "resp-aggregate"


def test_single_dispatch_uses_the_aggregate_rather_than_splitting_it() -> None:
    receipts = _build((ProviderDispatch(ordinal=1, reason="initial"),))

    assert len(receipts) == 1
    assert receipts[0].num_tokens_input == 100
    assert receipts[0].input_source == "provider"
