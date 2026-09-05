"""What a model may say about a published flow's runs, and how it is checked.

The sample (`ai_builder_flow_review_sample`) is what the model reads. This
module owns the closed set of judgements it may return, the prompt that asks
for them, and the parser that admits an answer only when every claim points
at something the sample actually contains: a step of the reviewed definition,
an excerpt whose text holds the quoted words, a fact id from the packet.
Invalid output is a distinct outcome from a valid empty list; a suggestion
with an unknown kind or an unverifiable source makes the whole answer
invalid rather than being dropped in silence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputMode,
    resolve_structured_output_capability,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderKnownProviderRejectionException,
    build_ai_builder_request_budget_exhausted_error,
    record_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_flow_review_sample import (
    ExcerptField,
    FlowReviewSample,
    ReviewSampleExcerpt,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.main.logging import get_logger
from eneo.tokens.token_utils import count_tokens, measure_provider_input_reserve

logger = get_logger(__name__)

REVIEW_SUGGESTIONS_SCHEMA_VERSION = 1
MAX_SUGGESTIONS = 6
MAX_SOURCES_PER_SUGGESTION = 3
# One limit from the model's answer to the investigation request built on it.
MAX_SUGGESTION_STEPS = 10
MAX_RATIONALE_CHARS = 400
MAX_QUOTE_CHARS = 200

FlowReviewSuggestionKind = Literal[
    "duplicated_work",
    "instruction_outcome_drift",
    "step_not_useful",
    "missing_check",
]
SUGGESTION_KINDS: tuple[str, ...] = (
    "duplicated_work",
    "instruction_outcome_drift",
    "step_not_useful",
    "missing_check",
)


class FlowReviewSuggestionSource(BaseModel):
    """One quoted place in the sample a suggestion rests on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    step_order: int
    field: ExcerptField
    quote: str = Field(min_length=1, max_length=MAX_QUOTE_CHARS)


class FlowReviewSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: FlowReviewSuggestionKind
    step_orders: list[int] = Field(min_length=1, max_length=MAX_SUGGESTION_STEPS)
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE_CHARS)
    sources: list[FlowReviewSuggestionSource] = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)


class FlowReviewSuggestionSampleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_ids: list[UUID]
    excerpts_included: int
    excerpts_truncated: int
    excerpts_omitted_by_budget: int
    excerpts_omitted_by_reader: int
    excerpts_not_recorded: int
    excerpts_unavailable: int


class FlowReviewSuggestions(BaseModel):
    """The model's judgement over one sample; held by the screen, never stored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: UUID
    model_name: str
    generated_at: datetime
    flow_version: int
    definition_checksum: str
    evidence_classification_level: int = Field(ge=0)
    sample: FlowReviewSuggestionSampleSummary
    suggestions: list[FlowReviewSuggestion]
    # Suggestions the model made that could not be tied to the sample and
    # were left out, so an empty list can be told from a refused answer.
    unverified_count: int = Field(ge=0)


def sample_summary(sample: FlowReviewSample) -> FlowReviewSuggestionSampleSummary:
    counts = {
        "included": 0,
        "truncated": 0,
        "omitted_by_budget": 0,
        "omitted_by_reader": 0,
        "not_recorded": 0,
        "unavailable": 0,
    }
    for excerpt in sample.excerpts:
        key = excerpt.availability if excerpt.availability in counts else "unavailable"
        counts[key] += 1
    return FlowReviewSuggestionSampleSummary(
        run_ids=sample.run_ids,
        excerpts_included=counts["included"],
        excerpts_truncated=counts["truncated"],
        excerpts_omitted_by_budget=counts["omitted_by_budget"],
        excerpts_omitted_by_reader=counts["omitted_by_reader"],
        excerpts_not_recorded=counts["not_recorded"],
        excerpts_unavailable=counts["unavailable"],
    )


# ---- prompt ------------------------------------------------------------------


def excerpt_source_id(excerpt: ReviewSampleExcerpt, *, run_index: int) -> str:
    return f"run{run_index}.step{excerpt.step_order}.{excerpt.field}"


def build_review_suggestions_messages(
    sample: FlowReviewSample, *, ui_language: str | None
) -> list[dict[str, Any]]:
    """One system + one user message. Swedish unless the UI asked otherwise."""

    swedish = ui_language is None or ui_language.casefold().startswith("sv")
    system = _SYSTEM_SV if swedish else _SYSTEM_EN
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": render_review_sample(sample)},
    ]


def render_review_sample(sample: FlowReviewSample) -> str:
    lines: list[str] = [
        f"## Flöde version {sample.packet.flow_version} (checksum {sample.packet.definition_checksum})",
        "",
        "### Steg",
    ]
    for step in sample.steps:
        contract = (
            ", ".join(step.output_contract_fields)
            if step.output_contract_fields
            else "–"
        )
        lines.append(
            f'- steg {step.step_order} "{step.label or ""}": {step.input_source}/'
            f"{step.input_type} → {step.output_type} ({step.output_mode}); "
            f"bindningar: {step.binding_summary or '–'}; utdatafält: {contract}; "
            f"granskning: {step.review_mode or '–'}"
        )
    lines.append("")
    lines.append("### Fakta ur körningarna (deterministiska, med id)")
    if sample.packet.facts:
        for fact in sample.packet.facts:
            payload = fact.model_dump(mode="json")
            fact_id = payload.pop("finding_id")
            lines.append(f"- [{fact_id}] {json.dumps(payload, ensure_ascii=False)}")
    else:
        lines.append("- inga")
    lines.append("")
    lines.append("### Körningar")
    run_index_by_id = {run.run_id: index + 1 for index, run in enumerate(sample.runs)}
    for run in sample.runs:
        lines.append(f"#### run{run_index_by_id[run.run_id]} ({run.status})")
        for excerpt in sample.excerpts:
            if excerpt.run_id != run.run_id:
                continue
            source_id = excerpt_source_id(
                excerpt, run_index=run_index_by_id[excerpt.run_id]
            )
            if excerpt.availability in ("included", "truncated"):
                marker = (
                    f" [avklippt efter {len(excerpt.text or '')} av "
                    f"{excerpt.recorded_chars} tecken]"
                    if excerpt.availability == "truncated"
                    else ""
                )
                lines.append(f"[{source_id}]{marker}")
                lines.append(excerpt.text or "")
            else:
                lines.append(
                    f"[{source_id}] ({_AVAILABILITY_SV[excerpt.availability]})"
                )
        lines.append("")
    return "\n".join(lines)


_AVAILABILITY_SV = {
    "included": "ingår",
    "truncated": "avklippt",
    "omitted_by_budget": "utelämnad av budgetskäl – inte läst",
    "omitted_by_reader": "inte läst av bevisläsaren – inte bevis",
    "not_recorded": "inte inspelad i körningen",
    "unavailable_mapped_prompt": "stegets prompt gäller bara första posten – inte bevis",
    "unavailable_template_fill": "mallfyllning spelar inte in någon prompt",
}

_SYSTEM_SV = f"""Du granskar ett publicerat flöde i Eneo utifrån ett urval av körningar.
Du får flödets steg, deterministiska fakta med id, och utdrag ur körningar märkta med käll-id.

Svara med JSON enligt schemat. Föreslå bara det som utdragen faktiskt visar:
- duplicated_work: två steg gör samma arbete på samma underlag.
- instruction_outcome_drift: ett stegs utdata följer inte stegets instruktion.
- step_not_useful: ett stegs utdata bidrar inte till slutresultatet (bara om utdragen visar det; att utdata inte citeras är i sig inget bevis).
- missing_check: en kontroll som instruktionen förutsätter saknas i praktiken.

Regler:
- Varje förslag ska ha 1–{MAX_SOURCES_PER_SUGGESTION} källor: käll-id exakt som i underlaget och ett ordagrant citat (högst {MAX_QUOTE_CHARS} tecken) ur den källan.
- Källor som är avklippta, utelämnade eller inte inspelade kan inte styrka att något saknas; missing_check och step_not_useful kräver att alla citerade källor ingår i sin helhet.
- instruction_outcome_drift kräver minst en citerad utdata som ingår i sin helhet; ett avklippt utdrag säger inget om hur utdata slutade.
- "Avklippt" betyder att läsaren kortade utdraget, inte att flödet gjorde det: att en text slutar tvärt är aldrig ett bevis, och ett stegs utdata får inte bedömas som ofullständig av det skälet.
- Citatet ska vara en exakt teckensträng ur utdraget som det visas här: fyll aldrig i ett avklippt ord och skriv inte om något.
- Använd fact-id i fact_ids bara när faktumet stödjer förslaget.
- Högst {MAX_SUGGESTIONS} förslag, vart och ett om högst {MAX_SUGGESTION_STEPS} steg. Inga förslag är ett giltigt svar.
- Motivering på svenska, högst {MAX_RATIONALE_CHARS} tecken, inga personuppgifter ur utdragen.

Svarsform (exakt dessa nycklar, JSON utan kommentarer):
{{"suggestions": [{{"kind": "duplicated_work", "step_orders": [2, 3], "rationale": "…", "sources": [{{"source_id": "run1.step2.output", "quote": "…"}}], "fact_ids": []}}]}}
Utan förslag: {{"suggestions": []}}"""

_SYSTEM_EN = _SYSTEM_SV  # The judgement language follows the workspace; Swedish today.


def review_suggestions_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["suggestions"],
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "step_orders", "rationale", "sources"],
                    "properties": {
                        "kind": {"type": "string", "enum": list(SUGGESTION_KINDS)},
                        "step_orders": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "rationale": {"type": "string"},
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["source_id", "quote"],
                                "properties": {
                                    "source_id": {"type": "string"},
                                    "quote": {"type": "string"},
                                },
                            },
                        },
                        "fact_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }
        },
    }


def review_suggestions_response_format(mode: StructuredOutputMode) -> dict[str, object]:
    if mode is StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION:
        return {}
    if mode is StructuredOutputMode.JSON_OBJECT:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"ai_builder_review_suggestions_v{REVIEW_SUGGESTIONS_SCHEMA_VERSION}",
            "strict": False,
            "schema": review_suggestions_json_schema(),
        },
    }


# ---- parsing -----------------------------------------------------------------


@dataclass(frozen=True)
class ParsedReviewSuggestions:
    """The envelope is admitted or refused whole; each suggestion inside it
    stands or falls on its own evidence, so one unverifiable claim does not
    discard the verified ones beside it. Diagnostics are reason codes with
    positions, never the model's text: a rejected value may carry copied
    evidence and this outcome is logged."""

    outcome: Literal["valid", "invalid"]
    suggestions: tuple[FlowReviewSuggestion, ...] = ()
    # One code per refused suggestion (valid envelope) or one envelope code.
    problems: tuple[str, ...] = field(default_factory=tuple)


ABSENCE_KINDS: frozenset[str] = frozenset({"missing_check", "step_not_useful"})


def parse_review_suggestions(
    content: str, *, sample: FlowReviewSample
) -> ParsedReviewSuggestions:
    """Admit every suggestion whose claims resolve in the sample; refuse the
    rest by code. Only a malformed envelope refuses the whole answer."""

    try:
        raw: object = json.loads(content)
    except json.JSONDecodeError:
        return ParsedReviewSuggestions("invalid", problems=("not_json",))
    if not isinstance(raw, dict):
        return ParsedReviewSuggestions("invalid", problems=("top_level_not_object",))
    raw_suggestions = cast(dict[str, object], raw).get("suggestions")
    if not isinstance(raw_suggestions, list):
        return ParsedReviewSuggestions("invalid", problems=("suggestions_not_list",))
    items = cast(list[object], raw_suggestions)
    if len(items) > MAX_SUGGESTIONS:
        return ParsedReviewSuggestions("invalid", problems=("too_many_suggestions",))

    context = _SampleIndex.build(sample)
    suggestions: list[FlowReviewSuggestion] = []
    problems: list[str] = []
    for position, item in enumerate(items):
        parsed = _parse_suggestion(item, index=context)
        if isinstance(parsed, str):
            problems.append(f"suggestion_{position + 1}:{parsed}")
            continue
        suggestions.append(parsed)
    return ParsedReviewSuggestions(
        "valid", suggestions=tuple(suggestions), problems=tuple(problems)
    )


@dataclass(frozen=True)
class _SampleIndex:
    step_orders: frozenset[int]
    fact_ids: frozenset[str]
    excerpts_by_source_id: dict[str, ReviewSampleExcerpt]
    complete_outputs: frozenset[tuple[UUID, int]]

    @classmethod
    def build(cls, sample: FlowReviewSample) -> "_SampleIndex":
        run_index_by_id = {
            run.run_id: index + 1 for index, run in enumerate(sample.runs)
        }
        excerpts = {
            excerpt_source_id(
                excerpt, run_index=run_index_by_id[excerpt.run_id]
            ): excerpt
            for excerpt in sample.excerpts
            if excerpt.run_id in run_index_by_id
        }
        return cls(
            step_orders=frozenset(step.step_order for step in sample.steps),
            fact_ids=frozenset(fact.finding_id for fact in sample.packet.facts),
            excerpts_by_source_id=excerpts,
            complete_outputs=frozenset(
                (excerpt.run_id, excerpt.step_order)
                for excerpt in sample.excerpts
                if excerpt.field == "output" and excerpt.availability == "included"
            ),
        )


def _parse_suggestion(
    item: object, *, index: _SampleIndex
) -> FlowReviewSuggestion | str:
    if not isinstance(item, dict):
        return "not_object"
    data = cast(dict[str, object], item)
    kind = data.get("kind")
    if kind not in SUGGESTION_KINDS:
        return "unknown_kind"
    raw_steps = data.get("step_orders")
    if not isinstance(raw_steps, list) or not raw_steps:
        return "step_orders_missing"
    steps: list[int] = []
    for raw_step in cast(list[object], raw_steps):
        if isinstance(raw_step, bool) or not isinstance(raw_step, int):
            return "step_orders_not_integers"
        if raw_step not in index.step_orders:
            return "step_not_in_definition"
        steps.append(raw_step)
    if len(set(steps)) > MAX_SUGGESTION_STEPS:
        return "too_many_steps"
    rationale = data.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return "rationale_missing"
    if len(rationale) > MAX_RATIONALE_CHARS:
        return "rationale_too_long"
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        return "sources_missing"
    source_items = cast(list[object], raw_sources)
    if len(source_items) > MAX_SOURCES_PER_SUGGESTION:
        return "too_many_sources"
    sources: list[FlowReviewSuggestionSource] = []
    availabilities: list[str] = []
    for position, raw_source in enumerate(source_items):
        parsed = _parse_source(raw_source, index=index)
        if isinstance(parsed, str):
            return f"source_{position + 1}:{parsed}"
        source, availability = parsed
        sources.append(source)
        availabilities.append(availability)
    raw_fact_ids = data.get("fact_ids", [])
    if not isinstance(raw_fact_ids, list):
        return "fact_ids_not_list"
    cited_facts: list[str] = []
    for raw_fact in cast(list[object], raw_fact_ids):
        if not isinstance(raw_fact, str) or raw_fact not in index.fact_ids:
            return "fact_not_in_packet"
        cited_facts.append(raw_fact)
    if kind in ABSENCE_KINDS:
        # A claim that something is absent is only as good as what was read:
        # every cited source must be complete, and every named step must
        # have a complete output in every run the claim cites. Another run's
        # complete output says nothing about the run the citation comes from.
        if any(availability != "included" for availability in availabilities):
            return "absence_claim_cites_incomplete_source"
        cited_runs = {source.run_id for source in sources}
        if any(
            (run_id, step) not in index.complete_outputs
            for run_id in cited_runs
            for step in steps
        ):
            return "absence_claim_without_complete_step_output"
    if kind == "instruction_outcome_drift":
        # Whether an output follows its instruction can only be judged on
        # the whole output: a cut excerpt shows neither what came after the
        # cut nor whether the step finished. The claim must cite at least
        # one output, and every cited output must be complete.
        cited_outputs = [
            availability
            for source, availability in zip(sources, availabilities)
            if source.field == "output"
        ]
        if not cited_outputs:
            return "drift_claim_without_output_source"
        if any(availability != "included" for availability in cited_outputs):
            return "drift_claim_cites_incomplete_output"
    return FlowReviewSuggestion(
        kind=cast(FlowReviewSuggestionKind, kind),
        step_orders=sorted(set(steps)),
        rationale=rationale.strip(),
        sources=sources,
        fact_ids=sorted(set(cited_facts)),
    )


_WHITESPACE = re.compile(r"\s+")


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _parse_source(
    raw_source: object, *, index: _SampleIndex
) -> tuple[FlowReviewSuggestionSource, str] | str:
    if not isinstance(raw_source, dict):
        return "not_object"
    data = cast(dict[str, object], raw_source)
    source_id = data.get("source_id")
    quote = data.get("quote")
    if not isinstance(source_id, str) or not isinstance(quote, str):
        return "shape"
    excerpt = index.excerpts_by_source_id.get(source_id.strip())
    if excerpt is None:
        return "unknown_source"
    if excerpt.availability not in ("included", "truncated") or not excerpt.text:
        return "source_not_readable"
    quote = _collapse_whitespace(quote)
    if not quote or len(quote) > MAX_QUOTE_CHARS:
        return "quote_length"
    # Verbatim in substance: line breaks and indentation in a markdown output
    # are not evidence, and a model quoting across them still quotes the run.
    if quote not in _collapse_whitespace(excerpt.text):
        return "quote_not_in_excerpt"
    return (
        FlowReviewSuggestionSource(
            run_id=excerpt.run_id,
            step_order=excerpt.step_order,
            field=excerpt.field,
            quote=quote,
        ),
        excerpt.availability,
    )


# ---- provider call -----------------------------------------------------------


async def generate_review_suggestions(
    *,
    sample: FlowReviewSample,
    litellm_client: Any,
    completion_model_route: ResolvedCompletionModelRoute,
    model_id: UUID,
    model_name: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
    tenant_id: UUID,
    ui_language: str | None,
) -> FlowReviewSuggestions:
    """One bounded structured call; the answer is admitted or refused whole.

    The caller has already committed the evidence audits and resolved a model
    that clears the sample's floor. Admission is token-based through the
    same request budget the classifier uses: a request the provider would
    refuse is refused here first, and a model answer that does not resolve
    in the sample is `review_suggestions_invalid_output`, never an empty list.
    """

    litellm_model = completion_model_route.litellm_model
    messages = build_review_suggestions_messages(sample, ui_language=ui_language)
    structured_output_mode = resolve_structured_output_capability(
        litellm_model=litellm_model,
        provider_type=completion_model_route.provider_type,
    ).mode
    response_format = review_suggestions_response_format(structured_output_mode)
    request_tokens = measure_provider_input_reserve(
        messages, [], litellm_model
    ).tokens + count_tokens(
        json.dumps(response_format, ensure_ascii=False, separators=(",", ":")),
        litellm_model,
    )
    request_budget = budget_policy.classification_request_budget(
        context_window_tokens=max_input_tokens,
        model_output_ceiling_tokens=max_output_tokens,
    ).resolve(input_tokens=request_tokens)
    if request_budget is None:
        raise AIBuilderKnownProviderRejectionException(
            build_ai_builder_request_budget_exhausted_error(request_id=None)
        )
    completion_kwargs = completion_model_route.prepare_provider_kwargs(
        ModelKwargs(temperature=0.0)
    )
    if response_format:
        completion_kwargs["response_format"] = response_format
    completion_kwargs.pop("timeout", None)
    completion_kwargs["max_tokens"] = request_budget.resolved_output_tokens
    try:
        response = await litellm_client.acompletion(
            model=litellm_model,
            messages=messages,
            stream=False,
            drop_params=True,
            timeout=request_budget.timeout_seconds,
            **completion_kwargs,
        )
    except Exception as error:
        failure = record_ai_builder_provider_failure(
            error, stage="review_suggestions", tenant_id=tenant_id
        )
        raise failure.as_exception() from error

    content = response.choices[0].message.content if response.choices else None
    if not isinstance(content, str) or not content.strip():
        raise AIBuilderBadRequestException(
            "The review model returned no content.",
            code=AIBuilderErrorCode.REVIEW_SUGGESTIONS_INVALID_OUTPUT,
            context={"problems": ["no_content"]},
        )
    parsed = parse_review_suggestions(content, sample=sample)
    if parsed.outcome == "invalid":
        logger.info(
            "AI Builder review suggestions rejected",
            extra={"model": litellm_model, "problem_codes": list(parsed.problems)},
        )
        raise AIBuilderBadRequestException(
            "The review model answered in a format that could not be read.",
            code=AIBuilderErrorCode.REVIEW_SUGGESTIONS_INVALID_OUTPUT,
            context={"problems": list(parsed.problems)},
        )
    logger.info(
        "AI Builder review suggestions completed",
        extra={
            "model": litellm_model,
            "run_count": len(sample.runs),
            "suggestion_count": len(parsed.suggestions),
            "unverified_count": len(parsed.problems),
            "problem_codes": list(parsed.problems),
            "kinds": sorted({item.kind for item in parsed.suggestions}),
        },
    )
    return FlowReviewSuggestions(
        model_id=model_id,
        model_name=model_name,
        generated_at=datetime.now(timezone.utc),
        flow_version=sample.packet.flow_version,
        definition_checksum=sample.packet.definition_checksum,
        evidence_classification_level=sample.evidence_classification_level,
        sample=sample_summary(sample),
        suggestions=list(parsed.suggestions),
        unverified_count=len(parsed.problems),
    )
