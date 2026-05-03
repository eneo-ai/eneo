"""Opt-in provider evaluation for the AI Builder slot resolver corpus.

The CLI is intentionally local-only: dry-run is deterministic, while live mode
requires explicit provider configuration and writes redacted scorecards.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_runtime_planning_state,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from intric.model_providers.infrastructure.litellm_runtime_config import (
    configure_litellm_runtime,
)
from tests.integration.flows.ai_builder.benchmark.cases import (
    SLOT_RESOLVER_CORPUS_CASES,
    SlotResolverCorpusCase,
)
from tests.integration.flows.ai_builder.benchmark.eval_support import (
    redacted_sha256,
    serialize_dataclass_scorecard,
    utc_now_iso,
)
from tests.integration.flows.ai_builder.benchmark.slot_resolver_scoring import (
    ScoreSummary,
    SlotAgreementSummary,
    SlotObservation,
    SlotScore,
    agreement_by_slot_name,
    observations_from_resolved_slots,
    score_expected_slots,
    slot_resolver_corpus_hash,
    summarize_agreements,
    summarize_slot_scores,
)

SCORECARD_SCHEMA_VERSION = 1
SLOT_RESOLVER_PROVIDER_TARGET = 0.85

ENV_MODEL = "ENEO_AI_BUILDER_SLOT_EVAL_MODEL"
ENV_TENANT_ID = "ENEO_AI_BUILDER_SLOT_EVAL_TENANT_ID"
ENV_API_KEY = "ENEO_AI_BUILDER_SLOT_EVAL_API_KEY"
ENV_API_BASE = "ENEO_AI_BUILDER_SLOT_EVAL_API_BASE"
ENV_API_VERSION = "ENEO_AI_BUILDER_SLOT_EVAL_API_VERSION"
ENV_API_TYPE = "ENEO_AI_BUILDER_SLOT_EVAL_API_TYPE"

_LITELLM_KWARG_ENV_KEYS: tuple[tuple[str, str], ...] = (
    (ENV_API_KEY, "api_key"),
    (ENV_API_BASE, "api_base"),
    (ENV_API_VERSION, "api_version"),
    (ENV_API_TYPE, "api_type"),
)


@dataclass(frozen=True, slots=True)
class RedactedModelConfig:
    model: str
    tenant_id_present: bool
    api_key_present: bool
    api_base_sha256: str | None
    api_version: str | None
    api_type: str | None


@dataclass(frozen=True, slots=True)
class LiveEvalConfig:
    model: str
    tenant_id: UUID
    litellm_kwargs: dict[str, object]
    redacted_model_config: RedactedModelConfig


@dataclass(frozen=True, slots=True)
class SlotScorecardEntry:
    slot_name: str
    expected_value: str
    observed_value: str | None
    observed_source: str | None
    observed_confidence: str | None
    matched: bool
    llm_resolvable: bool


@dataclass(frozen=True, slots=True)
class CaseScorecard:
    case_id: str
    provider_status: str
    keyword_slots: tuple[SlotScorecardEntry, ...]
    runtime_slots: tuple[SlotScorecardEntry, ...]
    keyword_summary: ScoreSummary
    runtime_full_summary: ScoreSummary
    runtime_llm_resolvable_summary: ScoreSummary


@dataclass(frozen=True, slots=True)
class ProviderCallStats:
    call_count: int = 0
    error_count: int = 0


@dataclass(frozen=True, slots=True)
class SlotResolverProviderScorecard:
    scorecard_schema_version: int
    schema_bump_policy: str
    generated_at: str
    live: bool
    target_score: float
    target_metric: str
    target_claimable: bool
    target_met: bool | None
    corpus_hash: str
    case_count: int
    model_config: RedactedModelConfig | None
    keyword_prior_summary: ScoreSummary
    runtime_full_summary: ScoreSummary | None
    runtime_llm_resolvable_provider_success_summary: ScoreSummary | None
    provider_success_case_count: int
    provider_call_stats: ProviderCallStats
    agreements_by_slot: tuple[SlotAgreementSummary, ...]
    cases: tuple[CaseScorecard, ...]


class CountingLiteLLMClient:
    def __init__(self, litellm_client: Any) -> None:
        self._litellm_client = litellm_client
        self.call_count = 0
        self.error_count = 0

    async def acompletion(self, **kwargs: object) -> object:
        self.call_count += 1
        try:
            return await self._litellm_client.acompletion(**kwargs)
        except Exception:
            self.error_count += 1
            raise

    @property
    def stats(self) -> ProviderCallStats:
        return ProviderCallStats(
            call_count=self.call_count,
            error_count=self.error_count,
        )


def load_live_eval_config(
    env: Mapping[str, str] | None = None,
) -> LiveEvalConfig:
    env_values = env or os.environ
    missing = [
        env_key for env_key in (ENV_MODEL, ENV_TENANT_ID) if not env_values.get(env_key)
    ]
    if missing:
        raise ValueError(
            "Live slot resolver eval requires " + ", ".join(missing) + " to be set."
        )

    tenant_id = UUID(env_values[ENV_TENANT_ID])
    litellm_kwargs = {
        litellm_key: env_values[env_key]
        for env_key, litellm_key in _LITELLM_KWARG_ENV_KEYS
        if env_values.get(env_key)
    }
    return LiveEvalConfig(
        model=env_values[ENV_MODEL],
        tenant_id=tenant_id,
        litellm_kwargs=litellm_kwargs,
        redacted_model_config=RedactedModelConfig(
            model=env_values[ENV_MODEL],
            tenant_id_present=True,
            api_key_present=bool(env_values.get(ENV_API_KEY)),
            api_base_sha256=redacted_sha256(env_values.get(ENV_API_BASE)),
            api_version=env_values.get(ENV_API_VERSION),
            api_type=env_values.get(ENV_API_TYPE),
        ),
    )


def build_dry_run_scorecard(
    cases: Sequence[SlotResolverCorpusCase] = SLOT_RESOLVER_CORPUS_CASES,
) -> SlotResolverProviderScorecard:
    keyword_case_scores = [
        _score_keyword_case(corpus_case) for corpus_case in sorted_cases(cases)
    ]
    keyword_scores = [
        slot_score
        for case_score in keyword_case_scores
        for slot_score in case_score.keyword_scores
    ]
    return SlotResolverProviderScorecard(
        scorecard_schema_version=SCORECARD_SCHEMA_VERSION,
        schema_bump_policy=_schema_bump_policy(),
        generated_at=utc_now_iso(),
        live=False,
        target_score=SLOT_RESOLVER_PROVIDER_TARGET,
        target_metric=_target_metric(),
        target_claimable=False,
        target_met=None,
        corpus_hash=slot_resolver_corpus_hash(cases),
        case_count=len(cases),
        model_config=None,
        keyword_prior_summary=summarize_slot_scores(keyword_scores),
        runtime_full_summary=None,
        runtime_llm_resolvable_provider_success_summary=None,
        provider_success_case_count=0,
        provider_call_stats=ProviderCallStats(),
        agreements_by_slot=(),
        cases=tuple(
            CaseScorecard(
                case_id=case_score.case_id,
                provider_status="not_run",
                keyword_slots=_scorecard_entries(case_score.keyword_scores),
                runtime_slots=(),
                keyword_summary=summarize_slot_scores(case_score.keyword_scores),
                runtime_full_summary=ScoreSummary(0, 0, None),
                runtime_llm_resolvable_summary=ScoreSummary(0, 0, None),
            )
            for case_score in keyword_case_scores
        ),
    )


async def build_live_scorecard(
    *,
    config: LiveEvalConfig,
    litellm_client: Any,
    cases: Sequence[SlotResolverCorpusCase] = SLOT_RESOLVER_CORPUS_CASES,
) -> SlotResolverProviderScorecard:
    counted_client = CountingLiteLLMClient(litellm_client)
    case_scorecards: list[CaseScorecard] = []
    keyword_scores: list[SlotScore] = []
    runtime_scores: list[SlotScore] = []
    provider_success_runtime_scores: list[SlotScore] = []
    per_case_agreements: list[tuple[SlotAgreementSummary, ...]] = []
    provider_success_count = 0

    for corpus_case in sorted_cases(cases):
        keyword_case = _score_keyword_case(corpus_case)
        calls_before = counted_client.call_count
        errors_before = counted_client.error_count
        runtime_observations = await _runtime_observations(
            corpus_case,
            config=config,
            counted_client=counted_client,
        )
        case_status = _provider_status(
            calls_before=calls_before,
            calls_after=counted_client.call_count,
            errors_before=errors_before,
            errors_after=counted_client.error_count,
        )
        runtime_case_scores = score_expected_slots(
            corpus_case.expected_slots,
            runtime_observations,
        )
        keyword_scores.extend(keyword_case.keyword_scores)
        runtime_scores.extend(runtime_case_scores)
        if case_status == "success":
            provider_success_count += 1
            provider_success_runtime_scores.extend(runtime_case_scores)
        per_case_agreements.append(
            agreement_by_slot_name(keyword_case.keyword_scores, runtime_case_scores)
        )
        case_scorecards.append(
            CaseScorecard(
                case_id=corpus_case.case_id,
                provider_status=case_status,
                keyword_slots=_scorecard_entries(keyword_case.keyword_scores),
                runtime_slots=_scorecard_entries(runtime_case_scores),
                keyword_summary=summarize_slot_scores(keyword_case.keyword_scores),
                runtime_full_summary=summarize_slot_scores(runtime_case_scores),
                runtime_llm_resolvable_summary=summarize_slot_scores(
                    runtime_case_scores,
                    llm_resolvable_only=True,
                ),
            )
        )

    runtime_provider_success_summary = summarize_slot_scores(
        provider_success_runtime_scores,
        llm_resolvable_only=True,
    )
    target_claimable = (
        counted_client.error_count == 0 and provider_success_count == len(cases)
    )
    target_met = (
        target_claimable
        and runtime_provider_success_summary.score is not None
        and runtime_provider_success_summary.score >= SLOT_RESOLVER_PROVIDER_TARGET
    )
    return SlotResolverProviderScorecard(
        scorecard_schema_version=SCORECARD_SCHEMA_VERSION,
        schema_bump_policy=_schema_bump_policy(),
        generated_at=utc_now_iso(),
        live=True,
        target_score=SLOT_RESOLVER_PROVIDER_TARGET,
        target_metric=_target_metric(),
        target_claimable=target_claimable,
        target_met=target_met,
        corpus_hash=slot_resolver_corpus_hash(cases),
        case_count=len(cases),
        model_config=config.redacted_model_config,
        keyword_prior_summary=summarize_slot_scores(keyword_scores),
        runtime_full_summary=summarize_slot_scores(runtime_scores),
        runtime_llm_resolvable_provider_success_summary=(
            runtime_provider_success_summary
        ),
        provider_success_case_count=provider_success_count,
        provider_call_stats=counted_client.stats,
        agreements_by_slot=summarize_agreements(per_case_agreements),
        cases=tuple(case_scorecards),
    )


def sorted_cases(
    cases: Sequence[SlotResolverCorpusCase],
) -> tuple[SlotResolverCorpusCase, ...]:
    return tuple(sorted(cases, key=lambda corpus_case: corpus_case.case_id))


def serialize_scorecard(scorecard: SlotResolverProviderScorecard) -> str:
    return serialize_dataclass_scorecard(scorecard)


def write_scorecard(
    scorecard: SlotResolverProviderScorecard,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialize_scorecard(scorecard), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the AI Builder slot resolver provider eval.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the configured provider. Omit for deterministic dry-run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the redacted scorecard JSON to this path.",
    )
    args = parser.parse_args(argv)

    if args.live:
        try:
            config = load_live_eval_config()
        except ValueError as exc:
            parser.error(str(exc))
        scorecard = asyncio.run(_build_live_scorecard_from_litellm(config))
    else:
        scorecard = build_dry_run_scorecard()

    if args.output is not None:
        write_scorecard(scorecard, args.output)
    else:
        print(serialize_scorecard(scorecard), end="")

    if args.live and scorecard.target_met is not True:
        return 1
    return 0


@dataclass(frozen=True, slots=True)
class _KeywordCaseScore:
    case_id: str
    keyword_scores: tuple[SlotScore, ...]


def _score_keyword_case(corpus_case: SlotResolverCorpusCase) -> _KeywordCaseScore:
    state = build_planning_state_from_conversation(
        [ConversationMessage(role="user", content=corpus_case.prompt)]
    )
    return _KeywordCaseScore(
        case_id=corpus_case.case_id,
        keyword_scores=score_expected_slots(
            corpus_case.expected_slots,
            observations_from_resolved_slots(state.resolved_slots),
        ),
    )


async def _runtime_observations(
    corpus_case: SlotResolverCorpusCase,
    *,
    config: LiveEvalConfig,
    counted_client: CountingLiteLLMClient,
) -> Mapping[str, SlotObservation]:
    state = await build_runtime_planning_state(
        [ConversationMessage(role="user", content=corpus_case.prompt)],
        litellm_client=counted_client,
        litellm_model=config.model,
        litellm_kwargs=config.litellm_kwargs,
        tenant_id=config.tenant_id,
        ui_language=corpus_case.ui_language,
    )
    return observations_from_resolved_slots(state.resolved_slots)


async def _build_live_scorecard_from_litellm(
    config: LiveEvalConfig,
) -> SlotResolverProviderScorecard:
    import litellm

    configure_litellm_runtime(litellm)
    return await build_live_scorecard(config=config, litellm_client=litellm)


def _scorecard_entries(scores: Sequence[SlotScore]) -> tuple[SlotScorecardEntry, ...]:
    return tuple(
        SlotScorecardEntry(
            slot_name=score.slot_name,
            expected_value=score.expected_value,
            observed_value=score.observed_value,
            observed_source=score.observed_source,
            observed_confidence=score.observed_confidence,
            matched=score.matched,
            llm_resolvable=score.llm_resolvable,
        )
        for score in scores
    )


def _provider_status(
    *,
    calls_before: int,
    calls_after: int,
    errors_before: int,
    errors_after: int,
) -> str:
    if errors_after > errors_before:
        return "error"
    if calls_after > calls_before:
        return "success"
    # Cache hits produce no provider call; they cannot claim a fresh live target.
    return "not_attempted"


def _schema_bump_policy() -> str:
    return (
        "Additive fields keep the version; field removal, rename, or semantic "
        "change bumps scorecard_schema_version."
    )


def _target_metric() -> str:
    return (
        "per-slot LLM-resolvable score on provider-success cases; full runtime "
        "score and keyword-prior score are context only"
    )


if __name__ == "__main__":
    raise SystemExit(main())
