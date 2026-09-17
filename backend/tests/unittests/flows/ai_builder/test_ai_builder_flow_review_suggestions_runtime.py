from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_capacity import ModelCapacity
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
    FlowReviewRunAdmission,
)
from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
    FlowReviewSample,
    ReviewSampleExcerpt,
    ReviewSampleRun,
    ReviewSampleStep,
    review_prompt_groups,
)
from eneo.flows.ai_builder.ai_builder_flow_review_suggestions import (
    build_review_suggestions_messages,
    generate_review_suggestions,
)
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from eneo.tokens.token_utils import measure_provider_input_reserve


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
            admission=[
                FlowReviewRunAdmission(
                    run_id=run_id,
                    status="completed",
                    token_share="admitted",
                    latency_share="admitted",
                    consumption="admitted",
                    error_facts="not_applicable",
                )
            ],
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
    capacity: ModelCapacity | None = None,
    sample=None,
    budget_policy: AIBuilderBudgetPolicy | None = None,
):
    return await generate_review_suggestions(
        sample=sample or _sample(),
        litellm_client=client,
        completion_model_route=_route(),
        model_id=uuid4(),
        model_name="gpt-test",
        capacity=capacity or ModelCapacity(max_input_tokens, max_output_tokens),
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
    assert call["stream"] is True and call["max_tokens"] > 0
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
    await _generate(
        client,
        capacity=ModelCapacity(100_000, 16_000),
    )
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
        capacity=ModelCapacity(1_000_000, 4000),
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
        client,
        capacity=ModelCapacity(100_000, 200_000),
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
        capacity=ModelCapacity(1_000_000, 128_000),
        sample=_long_sample(600_000),
        budget_policy=resolve_ai_builder_budget_policy(
            {"ai_builder": {"review_evidence_max_input_tokens": 128_000}}
        ),
    )
    (call,) = client.calls
    assert call["max_tokens"] == 128_000
    assert result.sample.excerpts_truncated == 1


@pytest.mark.asyncio
async def test_the_provider_request_retains_shared_instruction_groups_after_fitting():
    sample = _sample()
    runs = [sample.runs[0].model_copy(update={"run_id": uuid4()}) for _ in range(3)]
    sample = sample.model_copy(
        update={
            "runs": runs,
            "excerpts": [
                sample.excerpts[0].model_copy(
                    update={
                        "run_id": run.run_id,
                        "field": "prompt",
                        "text": "ord " * 10000,
                        "recorded_chars": 40000,
                    }
                )
                for run in runs
            ],
        }
    )
    client = _Client(content=json.dumps({"suggestions": []}))
    result = await _generate(client, max_input_tokens=12000, sample=sample)
    content = client.calls[0]["messages"][1]["content"]
    rows = [line for line in content.splitlines() if line.startswith("[run")]
    assert len(rows) == 1
    assert all(f"[run{index}.step1.prompt]" in rows[0] for index in (1, 2, 3))
    assert "avklippt efter" in rows[0]
    assert result.sample.excerpts_truncated == 3


@pytest.mark.asyncio
async def test_complete_shared_instructions_fit_the_measured_suggestions_cap():
    sample = _sample()
    instruction = "Sammanfatta ärendet."
    runs = [sample.runs[0].model_copy(update={"run_id": uuid4()}) for _ in range(3)]
    sample = sample.model_copy(
        update={
            "runs": runs,
            "excerpts": [
                sample.excerpts[0].model_copy(
                    update={
                        "run_id": run.run_id,
                        "field": "prompt",
                        "text": instruction,
                        "recorded_chars": len(instruction),
                    }
                )
                for run in runs
            ],
        }
    )
    baseline = _Client(content=json.dumps({"suggestions": []}))
    await _generate(baseline, sample=sample)
    full_request = baseline.calls[0]
    schema_tokens = measure_provider_input_reserve(
        [
            {
                "role": "system",
                "content": json.dumps(
                    full_request["response_format"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        ],
        [],
        _route().litellm_model,
    ).tokens

    def request_tokens(messages):
        return (
            measure_provider_input_reserve(messages, [], _route().litellm_model).tokens
            + schema_tokens
        )

    full_messages = build_review_suggestions_messages(sample, ui_language="sv")
    cap = request_tokens(full_messages)
    prefix_sample = sample.model_copy(
        update={
            "excerpts": [
                excerpt.model_copy(
                    update={"text": instruction[:1], "availability": "truncated"}
                )
                for excerpt in sample.excerpts
            ]
        }
    )
    assert (
        request_tokens(
            build_review_suggestions_messages(
                prefix_sample,
                ui_language="sv",
                prompt_groups=review_prompt_groups(sample.excerpts),
            )
        )
        > cap
    )
    client = _Client(content=json.dumps({"suggestions": []}))
    result = await _generate(
        client,
        sample=sample,
        budget_policy=resolve_ai_builder_budget_policy(
            {"ai_builder": {"review_evidence_max_input_tokens": cap}}
        ),
    )
    assert result.sample.excerpts_included == 3
    assert result.sample.excerpts_omitted_by_budget == 0
    assert client.calls[0]["messages"] == full_messages
    assert request_tokens(client.calls[0]["messages"]) == cap


@pytest.mark.asyncio
async def test_review_forwards_capacity():
    capacity = ModelCapacity(32_000, 4_000)
    policy = resolve_ai_builder_budget_policy(None)
    client = _Client(content=json.dumps({"suggestions": []}))
    with patch.object(
        AIBuilderBudgetPolicy,
        "review_request_budget",
        wraps=policy.review_request_budget,
    ) as factory:
        await _generate(client, capacity=capacity, budget_policy=policy)
    factory.assert_called_once_with(capacity=capacity)
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", ["high", "none"])
async def test_local_reasoning_refusal_preserves_known_rejection_before_review(effort):
    from eneo.ai_models.completion_models.completion_model import ModelKwargs
    from eneo.completion_models.domain.model_kwargs_capabilities import (
        SupportedModelKwargs,
    )
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )

    client = _Client()
    route = ResolvedCompletionModelRoute(
        litellm_model="mistral/plain-model",
        provider_type="mistral",
        litellm_kwargs={},
        supported_model_kwargs=SupportedModelKwargs(),
        requested_model_kwargs=ModelKwargs(reasoning_effort=effort),
    )
    with pytest.raises(AIBuilderKnownProviderRejectionException) as error:
        await generate_review_suggestions(
            sample=_sample(),
            litellm_client=client,
            completion_model_route=route,
            model_id=uuid4(),
            model_name="plain-model",
            capacity=ModelCapacity(100_000, 4000),
            budget_policy=resolve_ai_builder_budget_policy(None),
            tenant_id=uuid4(),
            ui_language="sv",
        )
    assert error.value.public_error.code is AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR
    assert error.value.public_error.details["provider_disposition"] == "known_rejection"
    assert error.value.public_error.details["reason"] == "reasoning_effort_unsupported"
    assert error.value.public_error.details["another_call_permitted"] is False
    assert client.calls == []
