from __future__ import annotations

from typing import Any, Final

from intric.flows.ai_builder.ai_builder_ask_question_contract import (
    canonical_ask_question_targets,
    format_ask_question_targets,
)
from intric.flows.ai_builder.ai_builder_commit_invariance import (
    CommitDriftError,
    assert_architecture_commit_draft_matches_pinned,
)
from intric.flows.ai_builder.ai_builder_litellm_completion import (
    call_planner_completion,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    OrchestrationContext,
    PlannerOutput,
    RejectionCode,
    RejectionReason,
    evaluate_planner_output,
    parse_planner_output,
    summarize_parse_failure,
)
from intric.flows.ai_builder.ai_builder_planner_output_normalizer import (
    normalize_planner_output,
)
from intric.flows.ai_builder.ai_builder_structured_turn import (
    Message,
    StructuredCompletion,
    StructuredTurnResult,
    run_structured_turn,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
)

MAX_ORCHESTRATOR_REPAIR_RETRIES: Final[int] = 3
MAX_PARSE_REPAIR_RETRIES: Final[int] = 1


async def run_planner_pipeline(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: dict[str, Any],
    base_messages: list[dict[str, Any]],
    orchestration_context: OrchestrationContext,
) -> StructuredTurnResult[PlannerOutput, RejectionReason]:
    prior_commit = orchestration_context.session_state.architecture_commit

    async def complete(messages: list[Message]) -> StructuredCompletion:
        completion = await call_planner_completion(
            litellm_client=litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            messages=messages,
        )
        return StructuredCompletion(
            raw_content=completion.raw_content,
            metadata=completion.metadata,
        )

    return await run_structured_turn(
        initial_messages=base_messages,
        complete=complete,
        parse=parse_planner_output,
        normalize=lambda output: normalize_planner_output(
            output,
            orchestration_context,
        ),
        validate=lambda output: evaluate_planner_output(
            output,
            orchestration_context,
        ),
        can_retry_semantic=_is_repair_eligible,
        build_semantic_retry_messages=lambda output, rejection: build_repair_messages(
            base_messages=base_messages,
            output=output,
            rejection=rejection,
        ),
        build_parse_retry_messages=build_parse_repair_messages,
        summarize_parse_failure=summarize_parse_failure,
        max_semantic_retries=MAX_ORCHESTRATOR_REPAIR_RETRIES,
        max_parse_retries=MAX_PARSE_REPAIR_RETRIES,
        repair_guard=lambda output: _detect_commit_drift(
            prior=prior_commit,
            after=output.planning_state_delta.architecture_commit,
        ),
    )


_REPAIR_ELIGIBLE_CODES: frozenset[RejectionCode] = frozenset(
    {
        "architecture_commit_premature_unresolved_choices",
        "architecture_commit_missing_delta",
        "off_topic_question",
        "duplicate_question",
    }
)

_PREMATURE_COMMIT_DIRECTIVE: Final[str] = (
    "The valid next action is `ask_question` about one of the "
    "unresolved slots named above. Emit `planner_action` with "
    '`kind="ask_question"` and a `question_id` that targets one of '
    "those slots. Do NOT emit `commit_architecture` again this turn."
)
_PRESERVE_COMMIT_DIRECTIVE: Final[str] = (
    "Re-emit a planner JSON product that honors the constraint. Do "
    "NOT change the committed architecture."
)
_DUPLICATE_QUESTION_DIRECTIVE: Final[str] = (
    "Do NOT repeat the same `ask_question`. Use the latest user message "
    "and conversation context as evidence. If the answer resolves the "
    "slot, emit a valid non-duplicate next action such as "
    "`confirm_requirements` or `commit_architecture` when all required "
    "choices are resolved. If more information is still needed, ask a "
    "different unresolved slot from the allowed target surface; do not "
    "re-ask the rejected question ID this turn."
)
_MISSING_COMMIT_DELTA_DIRECTIVE: Final[str] = (
    "If `planner_action.kind` is `commit_architecture`, keep "
    "`planning_state_delta.architecture_commit` as null; the server derives "
    "the architecture from resolved planning slots and the Flow Capability "
    "Manifest. Do NOT emit `architecture_hash` or `committed_at`. If this "
    "turn still lacks enough resolved state to commit, pivot to "
    "`ask_question` for the unresolved slot instead of re-emitting "
    "`commit_architecture`."
)


def build_repair_messages(
    *,
    base_messages: list[Message],
    output: PlannerOutput,
    rejection: RejectionReason,
) -> list[Message]:
    return [
        *base_messages,
        {"role": "assistant", "content": output.model_dump_json()},
        {
            "role": "user",
            "content": build_repair_user_message(rejection=rejection),
        },
    ]


def build_parse_repair_messages(
    base_messages: list[Message],
    failed_raw: str,
    failed_error: str,
) -> list[Message]:
    return [
        *base_messages,
        {"role": "assistant", "content": failed_raw},
        {
            "role": "user",
            "content": build_parse_repair_user_message(
                parse_error_message=failed_error,
            ),
        },
    ]


def build_repair_user_message(*, rejection: RejectionReason) -> str:
    return (
        "The previous response was rejected because: "
        f"{rejection.detail}. {_repair_directive_for(rejection.code)}"
    )


def build_parse_repair_user_message(*, parse_error_message: str) -> str:
    return (
        "The previous response could not be parsed as a PlannerOutput "
        f"JSON object. Parser error: {parse_error_message}. Re-emit the "
        "response as a single raw JSON object matching the "
        "PlannerOutput schema. Do NOT wrap the JSON in markdown code "
        "fences. Do NOT add prose before or after the JSON. Do NOT "
        "invent keys not declared in the schema. Reminders: "
        "For `kind=commit_architecture`, prefer "
        "`architecture_commit: null`; the server derives the architecture "
        "from resolved planning slots and the Flow Capability Manifest. "
        "Do NOT emit `architecture_hash` or `committed_at`; the server "
        "owns those values."
    )


def _is_repair_eligible(rejection: RejectionReason) -> bool:
    return rejection.code in _REPAIR_ELIGIBLE_CODES


def _repair_directive_for(code: RejectionCode) -> str:
    if code == "architecture_commit_premature_unresolved_choices":
        return _PREMATURE_COMMIT_DIRECTIVE
    if code == "architecture_commit_missing_delta":
        return _MISSING_COMMIT_DELTA_DIRECTIVE
    if code == "off_topic_question":
        return _off_topic_question_directive()
    if code == "duplicate_question":
        return _DUPLICATE_QUESTION_DIRECTIVE
    return _PRESERVE_COMMIT_DIRECTIVE


def _off_topic_question_directive() -> str:
    return (
        "The valid next action is `ask_question`. Replace invented "
        "domain-specific identifiers with one of the allowed targets "
        "named in the rejection detail. Emit that target in both "
        "`payload.question_id` and `payload.slot_name`; keep any narrower "
        "domain concept in `payload.prompt` only. Canonical ask_question "
        "targets are: "
        f"{format_ask_question_targets(canonical_ask_question_targets())}."
    )


def _detect_commit_drift(
    *,
    prior: ArchitectureCommit | None,
    after: ArchitectureCommitDraft | None,
) -> RejectionReason | None:
    if after is None:
        return None
    try:
        assert_architecture_commit_draft_matches_pinned(before=prior, after=after)
    except CommitDriftError as exc:
        return RejectionReason(
            code="repair_attempted_commit_drift",
            detail=str(exc),
        )
    return None


__all__ = [
    "MAX_ORCHESTRATOR_REPAIR_RETRIES",
    "MAX_PARSE_REPAIR_RETRIES",
    "build_parse_repair_user_message",
    "build_repair_user_message",
    "run_planner_pipeline",
]
