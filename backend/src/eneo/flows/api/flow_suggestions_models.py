from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from eneo.flows.api.flow_suggestion_dismissal_models import (
    FlowSuggestionDismissedPublic,
)
from eneo.flows.domain.flow_suggestion_dismissal import (
    FlowSuggestionDismissal,
    split_dismissed,
)
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFixKind,
    FlowSuggestionImpactBasis,
    FlowSuggestionLevel,
)

_FLOW_ID = "00000000-0000-0000-0000-000000000001"
_FIRST_STEP_ID = "00000000-0000-0000-0000-000000000101"
_SECOND_STEP_ID = "00000000-0000-0000-0000-000000000102"

_DUPLICATE_READ_EXAMPLE: JsonDict = {
    "code": FlowSuggestionCode.DUPLICATE_READ.value,
    "fingerprint": "9b2d3f1a" * 8,
    "steps": [_SECOND_STEP_ID, _FIRST_STEP_ID],
    "params": {
        "producer_step_order": 1,
        "producer_step_id": _FIRST_STEP_ID,
        "contained": False,
        "redundant_reads": [1],
        "reads": [
            {"channel": "input", "site": "input_source", "selector": []},
            {
                "channel": "prompt",
                "site": "assistant_prompt:step_1.output.text",
                "selector": [],
            },
        ],
    },
    "message": (
        "Step 2 reads step 1 twice, as its input (previous_step) and in its "
        "prompt ({{ step_1.output.text }}), so its model receives the same text "
        "twice on every run."
    ),
    "impact": {
        "basis": "runs",
        "level": "high",
        "tokens_per_run": 1840,
        "run_count": 8,
        "version": 3,
        "step_changed_since": False,
    },
    "fix": {
        "kind": "patch",
        "patch": {
            "definition": {},
            "assistants": [
                {
                    "assistant_id": "00000000-0000-0000-0000-000000000202",
                    "step_id": _SECOND_STEP_ID,
                    "changes": {
                        "prompt": {"text": "Sammanfatta.", "description": None}
                    },
                }
            ],
        },
    },
    "dismissed": None,
}

_THIRD_STEP_ID = "00000000-0000-0000-0000-000000000103"

_MODEL_RELAY_EXAMPLE: JsonDict = {
    "code": FlowSuggestionCode.MODEL_RELAY.value,
    "fingerprint": "4c7e0a5d" * 8,
    "steps": [_SECOND_STEP_ID, _FIRST_STEP_ID, _THIRD_STEP_ID],
    "params": {
        "producer_step_order": 1,
        "producer_step_id": _FIRST_STEP_ID,
        "reads": [
            {"channel": "input", "site": "input_source", "selector": []},
            {
                "channel": "prompt",
                "site": "assistant_prompt:step_1.output.text",
                "selector": [],
            },
        ],
        "readers": [
            {"step_order": 3, "step_id": _THIRD_STEP_ID, "sites": ["input_source"]}
        ],
        "copied_share": 0.82,
        "input_share": 0.91,
        "copied_bytes": 24300,
        "run_count": 8,
        "held_runs": 7,
    },
    "message": (
        "In 7 of the last 8 runs, 82 % of step 2's output was step 1's result "
        "copied word for word, and step 3 reads it from step 2; reading step 1 "
        "directly spares the model writing the copy."
    ),
    "impact": {
        "basis": "runs",
        "level": "high",
        "tokens_per_run": 5200,
        "run_count": 8,
        "version": 3,
        "step_changed_since": False,
    },
    "fix": {"kind": "assisted", "patch": None},
    "dismissed": None,
}

_PATCH_EXAMPLE: JsonDict = cast(
    JsonDict, cast(JsonDict, _DUPLICATE_READ_EXAMPLE["fix"])["patch"]
)

FLOW_SUGGESTIONS_EXAMPLE: JsonDict = {
    "flow_id": _FLOW_ID,
    "draft_revision": 4,
    "runs": {"requested": 10, "counted": 8, "left_out": 2},
    "dismissed_count": 1,
    "items": [_MODEL_RELAY_EXAMPLE, _DUPLICATE_READ_EXAMPLE],
}


class FlowSuggestionImpactPublic(BaseModel):
    basis: FlowSuggestionImpactBasis = Field(
        description=(
            "What the impact is judged from: `definition`, the draft alone, "
            "which proves the finding but not its size; `runs`, measured over "
            "recent runs as well (asked for with `runs`), with the measured "
            "fields set."
        ),
        examples=["runs"],
    )
    level: FlowSuggestionLevel = Field(
        description=(
            "How much the suggestion is worth acting on, judged from the "
            "definition: `high` when a whole result reaches a model twice or "
            "once per item, `medium` for a duplicate through "
            "`all_previous_steps`, unread contract fields or results, derived "
            "results taken together and material digested twice, `low` for the "
            "rest (a read contained in another, a broad or whole read, a "
            "relay, an unused form field). The measured codes: `high` for "
            "`identical_inputs`, `context_headroom` and `model_relay`, `medium` "
            "for `format_fallback`, `overlapping_inputs` and "
            "`deterministic_candidate`, `low` for `oversized_reasoning`."
        ),
        examples=["high"],
    )
    tokens_per_run: int | None = Field(
        default=None,
        description=(
            "Measured: the tokens per run the duplicated or unused part cost, "
            "averaged over the runs that measured it. For a duplicate, the "
            "size of the redundant input times the tokens per byte of each "
            "call that sent it; for a step run once per item, the copies "
            "beyond the first item's; for an unread result, everything the "
            "step was billed. From the forwarding facts, averaged over the runs "
            "in which the finding held: for `model_relay`, the output tokens of "
            "the measured call times the share of its output that was copied; "
            "for `overlapping_inputs`, the shared bytes times the tokens per "
            "byte of each call that sent both inputs; for "
            "`deterministic_candidate`, everything the step was billed, which a "
            "step without a model does not cost. Null when the impact is from "
            "the definition, when the runs did not report the tokens, and for a "
            "measured finding without a token cost of its own "
            "(`context_headroom`, `format_fallback`, `oversized_reasoning`)."
        ),
        examples=[1840],
    )
    run_count: int | None = Field(
        default=None,
        description="Measured: how many of the counted runs measured it.",
        examples=[8],
    )
    version: int | None = Field(
        default=None,
        description=("Measured: the published version of the newest of those runs."),
        examples=[3],
    )
    step_changed_since: bool | None = Field(
        default=None,
        description=(
            "Measured: true when the draft's step (its input, output, prompt "
            "or model) differs from the step in `version`, so the number "
            "describes the step as it was."
        ),
        examples=[False],
    )


class FlowSuggestionFixPublic(BaseModel):
    kind: FlowSuggestionFixKind = Field(
        description=(
            "How the suggestion is acted on: `patch`, a mechanical edit the "
            "core can make; `assisted`, a change that needs judgement, for the "
            "authoring chat to propose; `advice`, explained only."
        ),
        examples=["patch"],
    )
    patch: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Present exactly when `kind` is `patch`: the editor update that "
            "makes the fix, without `expected_revision` (`definition`, "
            "`step_edits`, `assistants`, `step_order`, whichever it needs), "
            "as `PATCH /api/v1/flows/{id}/editor/` takes it once the draft "
            "revision is added. Steps and assistants are named by id; an "
            "assistant change names its step, so an assistant other steps "
            "share is copied for that step. The patch was applied to the "
            "draft in memory and passes publish's step rules wherever the "
            "draft does; it is for the `draft_revision` of this answer."
        ),
        examples=[_PATCH_EXAMPLE],
    )


class FlowSuggestionPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _DUPLICATE_READ_EXAMPLE})

    code: FlowSuggestionCode = Field(
        description=(
            "What the suggestion is about. `duplicate_read`: the same earlier "
            "step reaches the step's model twice, through its input and its "
            "prompt or twice in one of them. `broad_all_previous_steps`: a "
            "step takes every earlier step, where one is derived from another "
            "it also gets, or three or more of them. `whole_structured_read`: "
            "a step reads all of a JSON result with four or more fields. "
            "`unread_contract_fields`: fields of a step's contract no later "
            "step reads. `unread_result`: a step whose result no later step "
            "reads. `relay_step`: a step that only passes another result on. "
            "`per_item_prompt_read`: a step that runs once per item with a "
            "whole earlier result in its prompt. `repeated_long_material`: two "
            "steps digest the same source as long material. "
            "`unused_form_field`: a run form field no step reads. Measured "
            "from recent runs, only with `runs`: `identical_inputs`, two inputs "
            "of a step carried the same value though they are read from "
            "different steps; `context_headroom`, a step's model came close to "
            "its input limit or the step failed the inline input limit; "
            "`format_fallback`, a step often needed a second call because its "
            "model did not accept the structured format. From the forwarding "
            "facts the worker records for each model call, also only with "
            "`runs`: `model_relay`, most of a model step's output was an "
            "earlier result copied word for word, which a later step reads "
            "from it (that step can read the original); `overlapping_inputs`, "
            "two inputs of a step shared half or more of the shorter one's "
            "text without being identical; `deterministic_candidate`, a model "
            "step's output was its inputs copied word for word with little of "
            "its own, which a `compose_text` step does without a model. "
            "Measured against what the model catalogue knows, also only with "
            "`runs`: `oversized_reasoning`, a step asks its reasoning-capable "
            "model for high reasoning effort while its calls were a small "
            "extraction into a JSON result."
        ),
        examples=[
            "duplicate_read",
            "model_relay",
            "overlapping_inputs",
            "deterministic_candidate",
            "oversized_reasoning",
        ],
    )
    fingerprint: str = Field(
        description=(
            "The suggestion's identity: a hash of its code, the steps it is "
            "about and the reads that triggered it. The same across edits that "
            "do not touch them; gone when the premise is."
        ),
        examples=["9b2d3f1a" * 8],
    )
    steps: list[UUID] = Field(
        description=(
            "The steps the suggestion is about; the first is the step it is "
            "shown on, the second, when there is one, the step it reads, "
            "copies or shares a source with; for `model_relay` the later steps "
            "that read the step follow. Empty for `unused_form_field`, which is "
            "about the run form."
        ),
    )
    params: dict[str, Any] = Field(
        description=(
            "Typed per code, for a client to render its own text from. For "
            "`duplicate_read`: `producer_step_order`, `producer_step_id`, "
            "`contained` (one read is a field of what the other already "
            "carries), `redundant_reads` (the indexes in `reads` of the reads "
            "the others already carry, never a whole read next to a narrower "
            "one) and `reads`, each with `channel` (`input` or `prompt`), "
            "`site` (`input_source`, `input_bindings.question`, "
            "`input_bindings.source_refs[N]`, `assistant_prompt:<expression>`) "
            'and `selector` (empty for the whole text, `["structured", ...]` '
            "for a structured value or a path in it). "
            "`broad_all_previous_steps`: `earlier_step_count`, `derived` "
            "(`step_order`, `from_step_order`) and `suggested_source_refs` "
            "(`step_order`, `step_id` of the earlier steps the prompt does not "
            "already read). `whole_structured_read`: `producer_step_order`, "
            "`producer_step_id`, `fields` and `reads`. "
            "`unread_contract_fields`: `fields` (unread) and `read_fields`. "
            "`unread_result`: `remove_patch`, the editor update that removes "
            "the step, checked like `fix.patch` and left out when it would "
            "not publish. `relay_step`: `source_step_order`, `source_step_id` "
            "(null when the relay copies the run input) and `readers` "
            "(`step_order`, `step_id`, `sites`). `per_item_prompt_read`: "
            "`execution_mode`, `producer_step_order`, `producer_step_id`, "
            "`reads`. `repeated_long_material`: `earlier_step_order`, "
            "`earlier_step_id`, `shared_step_orders`, `shares_run_input`. "
            "`unused_form_field`: `field`. `identical_inputs`: "
            "`producer_step_ids`, `producer_step_orders`, `sites`, "
            "`byte_size`, `observed_runs`, `step_runs`. `context_headroom`: "
            "`peak_input_tokens`, `token_limit`, `limit_share`, "
            "`inline_cap_failures`, `duplicated_tokens_per_run` and "
            "`duplicated_share` (what the step's measured duplicates account "
            "for), `related_fingerprints` (those duplicates), `step_runs`. "
            "`format_fallback`: `fallback_runs`, `step_runs`. `model_relay`: "
            "`producer_step_order`, `producer_step_id`, `reads` (the step's "
            "reads of that result), `readers` (`step_order`, `step_id`, "
            "`sites` of the later steps that read the step), `copied_share` "
            "(the share of the output found in that result), `input_share` "
            "(the share of that result the copy holds), `copied_bytes`. "
            "`overlapping_inputs`: `inputs` (two, each `step_order`, `step_id` "
            "and `sites`), `shared_bytes`, `shared_share` (of the shorter "
            "input). `deterministic_candidate`: `output_verbatim_ratio`, "
            "`own_bytes` (the output's bytes not found in its inputs), "
            "`input_share` (the share of the copied inputs the output holds). "
            "The three carry `run_count` (runs that measured the finding) and "
            "`held_runs` (runs in which it held), their shares and sizes "
            "averaged over the latter. `oversized_reasoning`: "
            "`reasoning_effort`, `peak_input_tokens` and `peak_output_tokens` "
            "(the largest call of the runs in which it held, the output with "
            "the model's reasoning), `token_limit`, `limit_share`, "
            "`run_count`, `held_runs`. A measured overlap of the two reads a "
            "`duplicate_read` or `broad_all_previous_steps` names is added to "
            "it as `measured_overlaps`: a list of the `overlapping_inputs` "
            "params, each with `tokens_per_run`, `version` and "
            "`step_changed_since`. No param holds run content."
        ),
    )
    message: str = Field(
        description="One English sentence saying what was found, for API and chat consumers.",
    )
    impact: FlowSuggestionImpactPublic
    fix: FlowSuggestionFixPublic
    dismissed: FlowSuggestionDismissedPublic | None = Field(
        default=None,
        description=(
            "Who dismissed the suggestion and when, for a suggestion an editor "
            "of the flow dismissed (listed only with `include_dismissed`); "
            "null for one that is shown."
        ),
    )

    @classmethod
    def from_suggestion(
        cls,
        suggestion: FlowSuggestion,
        dismissal: FlowSuggestionDismissal | None = None,
    ) -> Self:
        return cls(
            code=suggestion.code,
            fingerprint=suggestion.fingerprint,
            steps=list(suggestion.steps),
            params=dict(suggestion.params),
            message=suggestion.message,
            impact=FlowSuggestionImpactPublic.model_validate(
                suggestion.impact.model_dump()
            ),
            fix=FlowSuggestionFixPublic(
                kind=suggestion.fix.kind,
                patch=(
                    dict(suggestion.fix.patch)
                    if suggestion.fix.patch is not None
                    else None
                ),
            ),
            dismissed=(
                FlowSuggestionDismissedPublic.from_dismissal(dismissal)
                if dismissal is not None
                else None
            ),
        )


class FlowSuggestionRunsPublic(BaseModel):
    requested: int = Field(description="The `runs` asked for.", examples=[10])
    counted: int = Field(
        description=(
            "The finished runs whose evidence was measured: the newest ones in "
            "which a step ran, completed, failed or cancelled, that the caller "
            "may see evidence for."
        ),
        examples=[8],
    )
    left_out: int = Field(
        description=(
            "Runs among the newest `requested` that were left out because the "
            "caller may not see their evidence (another member's run, outside "
            "the caller's space role)."
        ),
        examples=[2],
    )


class FlowSuggestionsPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": FLOW_SUGGESTIONS_EXAMPLE})

    flow_id: UUID = Field(description="The flow.", examples=[_FLOW_ID])
    draft_revision: int = Field(
        description="The draft revision the suggestions judge.", examples=[4]
    )
    runs: FlowSuggestionRunsPublic | None = Field(
        default=None,
        description=(
            "Which runs were measured, when `runs` asked for them; null for "
            "the definition alone."
        ),
    )
    dismissed_count: int = Field(
        default=0,
        description=(
            "How many of the draft's suggestions an editor of the flow "
            "dismissed: left out of `items`, unless `include_dismissed` lists "
            "them with their `dismissed`."
        ),
        examples=[1],
    )
    items: list[FlowSuggestionPublic] = Field(
        description=(
            "The suggestions: those with a measured `impact.tokens_per_run` "
            "first, most tokens first, then by impact level (high, medium, "
            "low), then step order; at most 50, dismissed ones counted among "
            "them. Empty when the draft gives none."
        ),
    )

    @classmethod
    def from_suggestions(
        cls,
        *,
        flow_id: UUID,
        draft_revision: int,
        suggestions: tuple[FlowSuggestion, ...],
        runs: FlowSuggestionRunsPublic | None = None,
        dismissals: Mapping[str, FlowSuggestionDismissal] | None = None,
        include_dismissed: bool = False,
    ) -> Self:
        """The answer for ``suggestions``: those ``dismissals`` name are left
        out and counted, or with ``include_dismissed`` listed in their place
        and marked."""
        dismissals = dismissals or {}
        split = split_dismissed(suggestions, dismissals)
        listed = suggestions if include_dismissed else split.shown
        return cls(
            flow_id=flow_id,
            draft_revision=draft_revision,
            runs=runs,
            dismissed_count=len(split.dismissed),
            items=[
                FlowSuggestionPublic.from_suggestion(
                    item, dismissals.get(item.fingerprint)
                )
                for item in listed
            ],
        )


__all__ = [
    "FLOW_SUGGESTIONS_EXAMPLE",
    "FlowSuggestionFixPublic",
    "FlowSuggestionImpactPublic",
    "FlowSuggestionPublic",
    "FlowSuggestionRunsPublic",
    "FlowSuggestionsPublic",
]
