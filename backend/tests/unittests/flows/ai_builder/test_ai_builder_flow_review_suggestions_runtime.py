from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderKnownProviderRejectionException,
    AIBuilderProviderOutcomeUnknownException,
)
from eneo.flows.ai_builder.ai_builder_flow_review import (
    FlowReviewCohort,
    FlowReviewOmittedRuns,
    FlowReviewPacket,
)
from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
    FlowReviewSample,
    ReviewSampleExcerpt,
    ReviewSampleRun,
    ReviewSampleStep,
)
from eneo.flows.ai_builder.ai_builder_flow_review_suggestions import (
    generate_review_suggestions,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)


def _sample() -> FlowReviewSample:
    run_id = uuid4()
    packet = FlowReviewPacket(
        flow_id=uuid4(),
        flow_version=2,
        definition_checksum="sum-2",
        generated_at=datetime.now(timezone.utc),
        evidence_classification_level=1,
        steps=[],
        cohort=FlowReviewCohort(
            completed_run_ids=[run_id],
            failed_run_ids=[],
            omitted=FlowReviewOmittedRuns(),
        ),
        facts=[],
    )
    return FlowReviewSample(
        packet=packet,
        generated_at=datetime.now(timezone.utc),
        evidence_classification_level=1,
        steps=[
            ReviewSampleStep(
                step_order=1,
                label="Sammanfatta",
                input_source="flow_input",
                input_type="text",
                output_type="text",
                output_mode="pass_through",
                binding_summary=None,
                output_contract_fields=[],
                review_mode=None,
            )
        ],
        runs=[
            ReviewSampleRun(
                run_id=run_id, status="completed", evidence_classification_level=1
            )
        ],
        excerpts=[
            ReviewSampleExcerpt(
                run_id=run_id,
                step_order=1,
                field="output",
                availability="included",
                text="Sammanfattningen upprepar hela källtexten.",
                recorded_chars=42,
            )
        ],
    )


class _Client:
    def __init__(
        self,
        content: str | None = None,
        error: Exception | None = None,
        finish_reason: str = "stop",
    ):
        self.content = content
        self.error = error
        self.finish_reason = finish_reason
        self.calls: list[dict] = []

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=self.finish_reason)]
        )


def _route():
    return SimpleNamespace(
        litellm_model="openai/gpt-test",
        provider_type="openai",
        prepare_provider_kwargs=lambda kwargs: {},
    )


async def _generate(
    client,
    *,
    max_input_tokens: int = 100_000,
    max_output_tokens: int = 4000,
    sample=None,
    budget_policy: AIBuilderBudgetPolicy | None = None,
):
    return await generate_review_suggestions(
        sample=sample or _sample(),
        litellm_client=client,
        completion_model_route=_route(),
        model_id=uuid4(),
        model_name="gpt-test",
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy or resolve_ai_builder_budget_policy(None),
        tenant_id=uuid4(),
        ui_language="sv",
    )


@pytest.mark.asyncio
async def test_a_sourced_answer_becomes_suggestions_with_the_sample_floor():
    client = _Client(
        content=json.dumps(
            {
                "suggestions": [
                    {
                        "kind": "duplicated_work",
                        "step_orders": [1],
                        "rationale": "Utdata upprepar källan i stället för att sammanfatta.",
                        "sources": [
                            {
                                "source_id": "run1.step1.output",
                                "quote": "upprepar hela källtexten",
                            }
                        ],
                    }
                ]
            }
        )
    )
    result = await _generate(client)
    assert result.evidence_classification_level == 1
    assert result.flow_version == 2
    assert result.model_name == "gpt-test"
    assert [item.kind for item in result.suggestions] == ["duplicated_work"]
    assert result.sample.excerpts_included == 1
    (call,) = client.calls
    assert call["stream"] is False and call["max_tokens"] > 0
    assert call["num_retries"] == 0
    assert call["max_retries"] == 0
    assert call["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_a_suggestion_that_does_not_resolve_in_the_sample_is_left_out_and_counted():
    """The screen must tell "the model found nothing" from "the model claimed
    things that could not be tied to the runs": the latter is a valid answer
    with nothing admitted and an unverified count."""
    client = _Client(
        content=json.dumps(
            {
                "suggestions": [
                    {
                        "kind": "missing_check",
                        "step_orders": [1],
                        "rationale": "x",
                        "sources": [
                            {"source_id": "run1.step1.output", "quote": "aldrig sagt"}
                        ],
                    }
                ]
            }
        )
    )
    result = await _generate(client)
    assert result.suggestions == []
    assert result.unverified_count == 1


@pytest.mark.asyncio
async def test_a_malformed_envelope_is_refused_whole():
    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        await _generate(_Client(content=json.dumps({"suggestions": "none"})))
    assert excinfo.value.code == AIBuilderErrorCode.REVIEW_SUGGESTIONS_INVALID_OUTPUT
    assert excinfo.value.context["problems"] == ["suggestions_not_list"]


@pytest.mark.asyncio
async def test_an_empty_answer_is_valid():
    result = await _generate(_Client(content=json.dumps({"suggestions": []})))
    assert result.suggestions == []
    assert result.unverified_count == 0


@pytest.mark.asyncio
async def test_no_content_is_invalid_output():
    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        await _generate(_Client(content="   "))
    assert excinfo.value.code == AIBuilderErrorCode.REVIEW_SUGGESTIONS_INVALID_OUTPUT


@pytest.mark.asyncio
async def test_a_request_the_model_cannot_hold_is_refused_before_the_call():
    client = _Client(content=json.dumps({"suggestions": []}))
    with pytest.raises(AIBuilderKnownProviderRejectionException):
        await _generate(client, max_input_tokens=64)
    assert client.calls == []


@pytest.mark.asyncio
async def test_a_provider_error_is_recorded_as_a_provider_failure():
    client = _Client(error=RuntimeError("boom"))
    with pytest.raises(Exception) as excinfo:
        await _generate(client)
    assert not isinstance(excinfo.value, RuntimeError)


@pytest.mark.asyncio
async def test_review_enforces_its_deadline_without_repeating_provider_work():
    async def wait_for_provider(**_kwargs: object) -> None:
        await asyncio.Event().wait()

    client = SimpleNamespace(acompletion=AsyncMock(side_effect=wait_for_provider))
    with pytest.raises(AIBuilderProviderOutcomeUnknownException) as exc_info:
        async with asyncio.timeout(1):
            await _generate(
                client,
                budget_policy=AIBuilderBudgetPolicy(
                    conversation_safety_buffer_tokens=0,
                    minimum_conversation_budget_tokens=0,
                    proposal_timeout_seconds=0.01,
                ),
            )

    client.acompletion.assert_awaited_once()
    assert exc_info.value.public_error.details["provider_exception_class"] == "timeout"
    assert exc_info.value.public_error.details["another_call_permitted"] is False


@pytest.mark.asyncio
async def test_rejected_model_text_never_reaches_the_error_or_the_log(caplog):
    # A malformed field may carry copied evidence; only reason codes may leave.
    sentinel = "PERSONNUMMER-19900101-1234"
    client = _Client(
        content=json.dumps(
            {
                "suggestions": [
                    {
                        "kind": sentinel,
                        "step_orders": [1],
                        "rationale": sentinel,
                        "sources": [{"source_id": sentinel, "quote": sentinel}],
                        "fact_ids": [sentinel],
                    }
                ]
            }
        )
    )
    with caplog.at_level("INFO"):
        result = await _generate(client)
    assert result.suggestions == []
    assert result.unverified_count == 1
    assert sentinel not in result.model_dump_json()
    assert sentinel not in caplog.text


def _long_sample(chars: int) -> FlowReviewSample:
    base = _sample()
    long_excerpt = base.excerpts[0].model_copy(
        update={"text": "ord " * (chars // 4), "recorded_chars": chars}
    )
    return base.model_copy(update={"excerpts": [long_excerpt]})


@pytest.mark.asyncio
async def test_the_evidence_is_fitted_to_the_models_window_and_marked():
    """A window too small for the whole excerpt truncates it and says so, both
    in the request the model sees and in the summary the user sees; the
    answer keeps the size it would have with no evidence at all."""
    client = _Client(content=json.dumps({"suggestions": []}))
    result = await _generate(
        client, max_input_tokens=12_000, sample=_long_sample(40_000)
    )
    (call,) = client.calls
    user_message = call["messages"][1]["content"]
    assert "[avklippt efter" in user_message
    assert result.sample.excerpts_truncated == 1
    assert result.sample.excerpts_included == 0
    # The answer keeps the model ceiling; the evidence did not erode it.
    assert call["max_tokens"] == 4000


@pytest.mark.asyncio
async def test_the_answer_is_sent_with_the_models_full_output_ceiling():
    client = _Client(content=json.dumps({"suggestions": []}))
    await _generate(client, max_input_tokens=100_000, max_output_tokens=16_000)
    (call,) = client.calls
    assert call["max_tokens"] == 16_000


@pytest.mark.asyncio
async def test_a_window_too_small_for_the_scaffold_is_refused_before_the_call():
    client = _Client(content=json.dumps({"suggestions": []}))
    with pytest.raises(AIBuilderKnownProviderRejectionException):
        await _generate(client, max_input_tokens=300)
    assert client.calls == []


@pytest.mark.asyncio
async def test_a_tenant_cap_bounds_the_evidence_below_the_models_window():
    client = _Client(content=json.dumps({"suggestions": []}))
    policy = resolve_ai_builder_budget_policy(
        {"ai_builder": {"review_evidence_max_input_tokens": 12_000}}
    )
    result = await generate_review_suggestions(
        sample=_long_sample(80_000),
        litellm_client=client,
        completion_model_route=_route(),
        model_id=uuid4(),
        model_name="gpt-test",
        max_input_tokens=1_000_000,
        max_output_tokens=4000,
        budget_policy=policy,
        tenant_id=uuid4(),
        ui_language="sv",
    )
    assert result.sample.excerpts_truncated == 1


@pytest.mark.asyncio
async def test_a_ceiling_above_the_window_gets_the_room_the_request_leaves():
    """Catalogue metadata may declare an output ceiling at or above the window.

    The request is not refused for it: the model is told it may write what the
    window leaves after the packed request, never more than the provider
    permits and never less than the room the plan kept for the answer.
    """
    client = _Client(content=json.dumps({"suggestions": []}))
    result = await _generate(
        client, max_input_tokens=100_000, max_output_tokens=200_000
    )
    (call,) = client.calls
    assert 0 < call["max_tokens"] < 200_000
    assert result.sample.excerpts_included >= 1


@pytest.mark.asyncio
async def test_a_length_limited_answer_is_incomplete_even_when_it_parses():
    client = _Client(content=json.dumps({"suggestions": []}), finish_reason="length")
    with pytest.raises(AIBuilderBadRequestException) as error:
        await _generate(client)
    assert error.value.code is AIBuilderErrorCode.REVIEW_SUGGESTIONS_INVALID_OUTPUT
    assert error.value.context == {"problems": ["output_limit_exceeded"]}


@pytest.mark.asyncio
async def test_review_input_cap_can_equal_the_full_model_output_ceiling():
    client = _Client(content=json.dumps({"suggestions": []}))
    result = await _generate(
        client,
        max_input_tokens=1_000_000,
        max_output_tokens=128_000,
        sample=_long_sample(600_000),
        budget_policy=resolve_ai_builder_budget_policy(
            {"ai_builder": {"review_evidence_max_input_tokens": 128_000}}
        ),
    )
    (call,) = client.calls
    assert call["max_tokens"] == 128_000
    assert result.sample.excerpts_truncated == 1
