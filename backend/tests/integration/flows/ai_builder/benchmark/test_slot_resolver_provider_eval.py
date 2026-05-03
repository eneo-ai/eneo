from __future__ import annotations

import json
from dataclasses import asdict
from uuid import uuid4

import pytest

from tests.integration.flows.ai_builder.benchmark.cases import (
    ExpectedSlot,
    SlotCoverageTag,
    SlotResolverCorpusCase,
)
from tests.integration.flows.ai_builder.benchmark.slot_resolver_provider_eval import (
    ENV_API_BASE,
    ENV_API_KEY,
    ENV_MODEL,
    ENV_TENANT_ID,
    LiveEvalConfig,
    RedactedModelConfig,
    build_dry_run_scorecard,
    build_live_scorecard,
    load_live_eval_config,
    serialize_scorecard,
)
from tests.integration.flows.ai_builder.benchmark.slot_resolver_scoring import (
    SlotObservation,
    score_expected_slots,
    slot_resolver_corpus_hash,
    summarize_slot_scores,
)


def _case(
    *,
    case_id: str = "provider_eval_case",
    prompt: str = "Sammanfatta texten som användaren skriver.",
    expected_slots: tuple[ExpectedSlot, ...] = (
        ExpectedSlot("primary_runtime_input", "text"),
        ExpectedSlot("terminal_output", "structured_text"),
    ),
) -> SlotResolverCorpusCase:
    return SlotResolverCorpusCase(
        case_id=case_id,
        ui_language="sv",
        prompt=prompt,
        expected_slots=expected_slots,
        coverage_tags=frozenset({SlotCoverageTag.TEXT_ONLY}),
    )


class _FakeResponseMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeResponseChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeResponseMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeResponseChoice(content)]


class _FakeLiteLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content

    async def acompletion(self, **_: object) -> object:
        return _FakeResponse(self.content)


class _FailingLiteLLMClient:
    async def acompletion(self, **_: object) -> object:
        raise RuntimeError("provider unavailable")


def _config() -> LiveEvalConfig:
    return LiveEvalConfig(
        model="gpt-test",
        tenant_id=uuid4(),
        litellm_kwargs={},
        redacted_model_config=RedactedModelConfig(
            model="gpt-test",
            tenant_id_present=True,
            api_key_present=False,
            api_base_sha256=None,
            api_version=None,
            api_type=None,
        ),
    )


def test_unknown_expected_slot_matches_absent_or_unknown_observation() -> None:
    expected_slots = (ExpectedSlot("primary_runtime_input", "unknown"),)

    absent_summary = summarize_slot_scores(score_expected_slots(expected_slots, {}))
    explicit_summary = summarize_slot_scores(
        score_expected_slots(
            expected_slots,
            {"primary_runtime_input": SlotObservation(value="unknown")},
        )
    )

    assert absent_summary.matching_slots == 1
    assert explicit_summary.matching_slots == 1


def test_corpus_hash_includes_expected_slot_values() -> None:
    first = _case(expected_slots=(ExpectedSlot("terminal_output", "structured_text"),))
    second = _case(expected_slots=(ExpectedSlot("terminal_output", "pdf_document"),))

    assert slot_resolver_corpus_hash((first,)) != slot_resolver_corpus_hash((second,))


def test_dry_run_scorecard_has_no_live_provider_results() -> None:
    scorecard = build_dry_run_scorecard((_case(),))
    serialized = serialize_scorecard(scorecard)
    payload = json.loads(serialized)

    assert scorecard.live is False
    assert scorecard.target_claimable is False
    assert scorecard.target_met is None
    assert scorecard.provider_call_stats.call_count == 0
    assert scorecard.runtime_full_summary is None
    assert all("prompt" not in case_payload for case_payload in payload["cases"])
    assert "Sammanfatta texten" not in serialized


def test_live_config_requires_model_and_tenant_id() -> None:
    with pytest.raises(ValueError, match=ENV_MODEL):
        load_live_eval_config({})

    with pytest.raises(ValueError, match=ENV_TENANT_ID):
        load_live_eval_config({ENV_MODEL: "gpt-test"})


def test_live_config_redacts_api_key_base_and_tenant_id() -> None:
    tenant_id = uuid4()
    api_key = "secret-api-key"
    api_base = "https://internal.example.test/openai"

    config = load_live_eval_config(
        {
            ENV_MODEL: "gpt-test",
            ENV_TENANT_ID: str(tenant_id),
            ENV_API_KEY: api_key,
            ENV_API_BASE: api_base,
        }
    )
    redacted_payload = json.dumps(asdict(config.redacted_model_config))

    assert config.litellm_kwargs["api_key"] == api_key
    assert config.litellm_kwargs["api_base"] == api_base
    assert config.redacted_model_config.api_key_present is True
    assert config.redacted_model_config.api_base_sha256 is not None
    assert api_key not in redacted_payload
    assert api_base not in redacted_payload
    assert str(tenant_id) not in redacted_payload


@pytest.mark.asyncio
async def test_live_scorecard_scores_runtime_overlay_with_fake_provider() -> None:
    fake_client = _FakeLiteLLMClient(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "text input",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "high",
                        "reason": "summary output",
                    },
                ]
            }
        )
    )

    scorecard = await build_live_scorecard(
        config=_config(),
        litellm_client=fake_client,
        cases=(_case(),),
    )

    assert scorecard.live is True
    assert scorecard.provider_success_case_count == 1
    assert scorecard.provider_call_stats.call_count == 1
    assert scorecard.provider_call_stats.error_count == 0
    assert scorecard.target_claimable is True
    assert scorecard.runtime_llm_resolvable_provider_success_summary is not None
    assert scorecard.runtime_llm_resolvable_provider_success_summary.score == 1.0
    assert scorecard.target_met is True


@pytest.mark.asyncio
async def test_live_scorecard_separates_provider_errors_from_accuracy() -> None:
    scorecard = await build_live_scorecard(
        config=_config(),
        litellm_client=_FailingLiteLLMClient(),
        cases=(
            _case(
                case_id="provider_error_case",
                prompt="Skapa en PDF-rapport utifrån text som användaren skriver.",
                expected_slots=(
                    ExpectedSlot("primary_runtime_input", "text"),
                    ExpectedSlot("terminal_output", "pdf_document"),
                ),
            ),
        ),
    )

    assert scorecard.provider_call_stats.call_count == 1
    assert scorecard.provider_call_stats.error_count == 1
    assert scorecard.provider_success_case_count == 0
    assert scorecard.target_claimable is False
    assert scorecard.target_met is False
    assert scorecard.cases[0].provider_status == "error"


def test_serialized_scorecard_exposes_score_and_schema_version() -> None:
    scorecard = build_dry_run_scorecard((_case(),))
    payload = json.loads(serialize_scorecard(scorecard))

    assert payload["scorecard_schema_version"] == 1
    assert "schema_bump_policy" in payload
    assert "score" in payload["keyword_prior_summary"]
