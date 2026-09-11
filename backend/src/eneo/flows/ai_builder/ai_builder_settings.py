from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_DEFAULT_MAX_TEMPLATE_PLACEHOLDERS,
    AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
    AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
    AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS,
    AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
    extract_ai_builder_budget_settings,
    parse_ai_builder_budget_token,
    parse_ai_builder_operating_limit,
)
from eneo.main.config import AI_BUILDER_ANSWER_RESERVE_SHARE_DEFAULT, get_settings

AI_BUILDER_PROPOSAL_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True, slots=True, kw_only=True)
class AIBuilderRequestBudget:
    """One provider call's window, allocated from the selected model's limits.

    The model contributes two facts: its context window and its output
    ceiling. Input and answer share the window, so a request is allocated in
    two steps. ``plan`` reserves answer room once the required input is
    measured: the ceiling when it fits within the policy share of the room the
    required input leaves, otherwise that share, so optional input never
    crowds the answer out and the answer never crowds optional input out.
    ``resolve`` then measures the packed request whole and sends the model the
    most it may write in the room that remains, never a fixed number.
    """

    context_window_tokens: int
    model_output_ceiling_tokens: int
    safety_buffer_tokens: int
    timeout_seconds: float
    # The share of the room after the required input that packing keeps free
    # for the answer. Dimensionless deployment policy, never a token count.
    answer_reserve_share: float = AI_BUILDER_ANSWER_RESERVE_SHARE_DEFAULT
    request_id: str | None = None
    # Bounds the complete input only; the answer is never charged to it.
    input_cap_tokens: int | None = None

    def __post_init__(self) -> None:
        positive_values = {
            "context window": self.context_window_tokens,
            "model output ceiling": self.model_output_ceiling_tokens,
        }
        for name, value in positive_values.items():
            if value < 1:
                raise ValueError(f"AI Builder {name} must be positive")
        if self.input_cap_tokens is not None and self.input_cap_tokens < 1:
            raise ValueError("AI Builder input cap must be positive")
        if self.safety_buffer_tokens < 0:
            raise ValueError("AI Builder safety buffer cannot be negative")
        if not (
            math.isfinite(self.answer_reserve_share)
            and 0 < self.answer_reserve_share < 1
        ):
            raise ValueError("AI Builder answer reserve share must be within (0, 1)")
        if self.timeout_seconds <= 0:
            raise ValueError("AI Builder request timeout must be positive")

    @property
    def usable_window_tokens(self) -> int:
        """What input and answer share once the safety buffer is set aside."""

        return max(0, self.context_window_tokens - self.safety_buffer_tokens)

    def plan(
        self, *, required_input_tokens: int
    ) -> AIBuilderPlannedRequestBudget | None:
        """Allocate the window for a request whose required input is measured.

        None when that input leaves no room for any answer, or already exceeds
        the tenant input cap: nothing optional can be dropped to recover, so
        the request is refused before any provider work.
        """

        if required_input_tokens < 0:
            raise ValueError("AI Builder input tokens cannot be negative")
        if (
            self.input_cap_tokens is not None
            and required_input_tokens > self.input_cap_tokens
        ):
            return None
        room = self.usable_window_tokens - required_input_tokens
        if room < 1:
            return None
        reserved_output_tokens = min(
            self.model_output_ceiling_tokens,
            max(1, math.ceil(room * self.answer_reserve_share)),
        )
        available_input_tokens = self.usable_window_tokens - reserved_output_tokens
        if self.input_cap_tokens is not None:
            available_input_tokens = min(available_input_tokens, self.input_cap_tokens)
        return AIBuilderPlannedRequestBudget(
            context_window_tokens=self.context_window_tokens,
            model_output_ceiling_tokens=self.model_output_ceiling_tokens,
            safety_buffer_tokens=self.safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            timeout_seconds=self.timeout_seconds,
            request_id=self.request_id,
            input_cap_tokens=self.input_cap_tokens,
            required_input_tokens=required_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
            available_input_tokens=available_input_tokens,
        )

    def resolve_whole(
        self, *, input_tokens: int
    ) -> AIBuilderResolvedRequestBudget | None:
        """The budget of a request whose complete input is required.

        For a payload that carries nothing optional: the plan and the packed
        measurement are the same number.
        """

        planned = self.plan(required_input_tokens=input_tokens)
        return None if planned is None else planned.resolve(input_tokens=input_tokens)


@dataclass(frozen=True, slots=True, kw_only=True)
class AIBuilderPlannedRequestBudget(AIBuilderRequestBudget):
    required_input_tokens: int
    # Kept free for the answer while optional input is packed; fixed for the
    # whole packing pass so growing input cannot shrink it.
    reserved_output_tokens: int
    # The most the packed request may carry, required input included.
    available_input_tokens: int

    def plan(
        self, *, required_input_tokens: int
    ) -> AIBuilderPlannedRequestBudget | None:
        """A planned budget is one allocation; it is not re-planned in passing.

        Packing that has already grown the protected input must not shrink
        the reserve it was packed against. A genuinely new call (a repair
        with new protected content) plans again from ``unplanned()``.
        """

        raise TypeError(
            "A planned AI Builder budget is not re-planned implicitly; use "
            "unplanned().plan(...) for a new provider call"
        )

    def unplanned(self) -> AIBuilderRequestBudget:
        """The model and policy facts alone, for a deliberately new plan."""

        return AIBuilderRequestBudget(
            context_window_tokens=self.context_window_tokens,
            model_output_ceiling_tokens=self.model_output_ceiling_tokens,
            safety_buffer_tokens=self.safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            timeout_seconds=self.timeout_seconds,
            request_id=self.request_id,
            input_cap_tokens=self.input_cap_tokens,
        )

    def resolve(self, *, input_tokens: int) -> AIBuilderResolvedRequestBudget | None:
        """The packed request, measured whole, and what the model may write.

        The provider cap is the ceiling within the room the packed input
        leaves; it is never below the reserve while the input stays within
        ``available_input_tokens``.
        """

        if input_tokens < 0:
            raise ValueError("AI Builder input tokens cannot be negative")
        if input_tokens > self.available_input_tokens:
            return None
        provider_output_cap_tokens = min(
            self.model_output_ceiling_tokens,
            self.usable_window_tokens - input_tokens,
        )
        return AIBuilderResolvedRequestBudget(
            context_window_tokens=self.context_window_tokens,
            model_output_ceiling_tokens=self.model_output_ceiling_tokens,
            safety_buffer_tokens=self.safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            timeout_seconds=self.timeout_seconds,
            request_id=self.request_id,
            input_cap_tokens=self.input_cap_tokens,
            required_input_tokens=self.required_input_tokens,
            reserved_output_tokens=self.reserved_output_tokens,
            available_input_tokens=self.available_input_tokens,
            fixed_input_tokens=input_tokens,
            provider_output_cap_tokens=provider_output_cap_tokens,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AIBuilderResolvedRequestBudget(AIBuilderPlannedRequestBudget):
    fixed_input_tokens: int
    provider_output_cap_tokens: int


@dataclass(frozen=True)
class AIBuilderBudgetPolicy:
    conversation_safety_buffer_tokens: int
    minimum_conversation_budget_tokens: int
    # See AIBuilderRequestBudget.answer_reserve_share.
    answer_reserve_share: float = AI_BUILDER_ANSWER_RESERVE_SHARE_DEFAULT
    # Classification shares the proposal deadline unless deployment policy
    # explicitly gives it a different one.
    classification_timeout_seconds: float | None = None
    proposal_timeout_seconds: float = AI_BUILDER_PROPOSAL_TIMEOUT_SECONDS
    max_attachments: int = AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT
    max_message_chars: int = AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT
    max_template_inspection_uncompressed_bytes: int = (
        AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES
    )
    max_template_placeholders: int = AI_BUILDER_DEFAULT_MAX_TEMPLATE_PLACEHOLDERS
    # Limits the complete input of requests carrying run evidence. Output
    # remains bounded by the model, independently of this tenant input cap.
    review_evidence_max_input_tokens: int | None = None
    # The share of a review-backed proposal prompt the review evidence block
    # may take: a conservative system bound based on limited testing, which a
    # tenant may lower, never raise.
    review_investigation_evidence_max_tokens: int = (
        AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS
    )

    def answer_reserve_tokens(
        self,
        *,
        context_window_tokens: int,
        model_output_ceiling_tokens: int,
        required_input_tokens: int,
    ) -> int:
        """The answer room packing keeps free beside ``required_input_tokens``.

        For a packer that runs before the request's prompt exists (attached
        sources are read first), with the policy's conversation minimum
        standing in for the input it cannot measure yet. A window with no room
        keeps the whole ceiling: such a packer admits nothing, and the request
        is refused where it is measured.
        """

        planned = self.proposal_request_budget(
            context_window_tokens=context_window_tokens,
            model_output_ceiling_tokens=model_output_ceiling_tokens,
        ).plan(required_input_tokens=required_input_tokens)
        return (
            model_output_ceiling_tokens
            if planned is None
            else planned.reserved_output_tokens
        )

    def classification_request_budget(
        self,
        *,
        context_window_tokens: int,
        model_output_ceiling_tokens: int,
        request_id: str | None = None,
    ) -> AIBuilderRequestBudget:
        return AIBuilderRequestBudget(
            context_window_tokens=context_window_tokens,
            model_output_ceiling_tokens=model_output_ceiling_tokens,
            safety_buffer_tokens=self.conversation_safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            timeout_seconds=(
                self.classification_timeout_seconds
                if self.classification_timeout_seconds is not None
                else self.proposal_timeout_seconds
            ),
            request_id=request_id,
        )

    def review_request_budget(
        self,
        *,
        context_window_tokens: int,
        model_output_ceiling_tokens: int,
        request_id: str | None = None,
    ) -> AIBuilderRequestBudget:
        """Review uses the selected model's limits and the tenant's evidence cap."""

        return AIBuilderRequestBudget(
            context_window_tokens=context_window_tokens,
            input_cap_tokens=self.review_evidence_max_input_tokens,
            model_output_ceiling_tokens=model_output_ceiling_tokens,
            safety_buffer_tokens=self.conversation_safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            timeout_seconds=self.proposal_timeout_seconds,
            request_id=request_id,
        )

    def proposal_request_budget(
        self,
        *,
        context_window_tokens: int,
        model_output_ceiling_tokens: int,
        request_id: str | None = None,
        carries_review_evidence: bool = False,
    ) -> AIBuilderRequestBudget:
        return AIBuilderRequestBudget(
            context_window_tokens=context_window_tokens,
            input_cap_tokens=(
                self.review_evidence_max_input_tokens
                if carries_review_evidence
                else None
            ),
            model_output_ceiling_tokens=model_output_ceiling_tokens,
            safety_buffer_tokens=self.conversation_safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            timeout_seconds=self.proposal_timeout_seconds,
            request_id=request_id,
        )


def _default_policy(defaults: Any | None = None) -> AIBuilderBudgetPolicy:
    source = defaults or get_settings()
    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=int(
            source.ai_builder_conversation_safety_buffer_tokens
        ),
        minimum_conversation_budget_tokens=int(
            source.ai_builder_minimum_conversation_budget_tokens
        ),
        answer_reserve_share=float(
            getattr(
                source,
                "ai_builder_answer_reserve_share",
                AI_BUILDER_ANSWER_RESERVE_SHARE_DEFAULT,
            )
        ),
        classification_timeout_seconds=(
            float(source.ai_builder_classification_timeout_seconds)
            if source.ai_builder_classification_timeout_seconds is not None
            else None
        ),
        proposal_timeout_seconds=float(source.ai_builder_proposal_timeout_seconds),
        max_attachments=AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
        max_message_chars=AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
        max_template_inspection_uncompressed_bytes=(
            AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES
        ),
        max_template_placeholders=AI_BUILDER_DEFAULT_MAX_TEMPLATE_PLACEHOLDERS,
    )


def _parse_token_int(
    value: Any, field_name: str, *, allow_none: bool = False
) -> int | None:
    try:
        return parse_ai_builder_budget_token(
            value,
            field_name,
            allow_none=allow_none,
        )
    except ValueError as error:
        raise AIBuilderBadRequestException(
            str(error),
            code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
        ) from error


def resolve_ai_builder_budget_policy(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    defaults: Any | None = None,
) -> AIBuilderBudgetPolicy:
    resolved_defaults = _default_policy(defaults)
    raw = extract_ai_builder_budget_settings(tenant_flow_settings)

    safety_buffer = resolved_defaults.conversation_safety_buffer_tokens
    if "conversation_safety_buffer_tokens" in raw:
        parsed_safety_buffer = _parse_token_int(
            raw["conversation_safety_buffer_tokens"],
            "conversation_safety_buffer_tokens",
        )
        if parsed_safety_buffer is not None:
            safety_buffer = parsed_safety_buffer

    minimum_budget = resolved_defaults.minimum_conversation_budget_tokens
    if "minimum_conversation_budget_tokens" in raw:
        parsed_minimum_budget = _parse_token_int(
            raw["minimum_conversation_budget_tokens"],
            "minimum_conversation_budget_tokens",
        )
        if parsed_minimum_budget is not None:
            minimum_budget = parsed_minimum_budget

    review_evidence_cap = resolved_defaults.review_evidence_max_input_tokens
    if "review_evidence_max_input_tokens" in raw:
        review_evidence_cap = _parse_token_int(
            raw["review_evidence_max_input_tokens"],
            "review_evidence_max_input_tokens",
            allow_none=True,
        )
    investigation_evidence_cap = (
        resolved_defaults.review_investigation_evidence_max_tokens
    )
    if "review_investigation_evidence_max_tokens" in raw:
        try:
            investigation_evidence_cap = parse_ai_builder_operating_limit(
                raw["review_investigation_evidence_max_tokens"],
                "review_investigation_evidence_max_tokens",
            )
        except ValueError as error:
            raise AIBuilderBadRequestException(
                str(error),
                code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
            ) from error

    operating_limits = {
        "max_attachments": resolved_defaults.max_attachments,
        "max_message_chars": resolved_defaults.max_message_chars,
        "max_template_inspection_uncompressed_bytes": (
            resolved_defaults.max_template_inspection_uncompressed_bytes
        ),
        "max_template_placeholders": resolved_defaults.max_template_placeholders,
    }
    for field_name in operating_limits:
        if field_name not in raw:
            continue
        try:
            operating_limits[field_name] = parse_ai_builder_operating_limit(
                raw[field_name],
                field_name,
            )
        except ValueError as error:
            raise AIBuilderBadRequestException(
                str(error),
                code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
            ) from error

    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=safety_buffer,
        minimum_conversation_budget_tokens=minimum_budget,
        answer_reserve_share=resolved_defaults.answer_reserve_share,
        classification_timeout_seconds=(
            resolved_defaults.classification_timeout_seconds
        ),
        proposal_timeout_seconds=resolved_defaults.proposal_timeout_seconds,
        max_attachments=operating_limits["max_attachments"],
        max_message_chars=operating_limits["max_message_chars"],
        max_template_inspection_uncompressed_bytes=operating_limits[
            "max_template_inspection_uncompressed_bytes"
        ],
        max_template_placeholders=operating_limits["max_template_placeholders"],
        review_evidence_max_input_tokens=review_evidence_cap,
        review_investigation_evidence_max_tokens=investigation_evidence_cap,
    )


def apply_ai_builder_budget_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    conversation_safety_buffer_tokens: int | None = None,
    minimum_conversation_budget_tokens: int | None = None,
    max_attachments: int | None = None,
    max_message_chars: int | None = None,
    max_template_inspection_uncompressed_bytes: int | None = None,
    max_template_placeholders: int | None = None,
    review_evidence_max_input_tokens: int | None = None,
    review_investigation_evidence_max_tokens: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    current = extract_ai_builder_budget_settings(result)
    next_settings: dict[str, Any] = dict(current)

    if conversation_safety_buffer_tokens is not None:
        next_settings["conversation_safety_buffer_tokens"] = _parse_token_int(
            conversation_safety_buffer_tokens,
            "conversation_safety_buffer_tokens",
        )
    if minimum_conversation_budget_tokens is not None:
        next_settings["minimum_conversation_budget_tokens"] = _parse_token_int(
            minimum_conversation_budget_tokens,
            "minimum_conversation_budget_tokens",
        )
    if review_evidence_max_input_tokens is not None:
        next_settings["review_evidence_max_input_tokens"] = _parse_token_int(
            review_evidence_max_input_tokens,
            "review_evidence_max_input_tokens",
        )
    if review_investigation_evidence_max_tokens is not None:
        try:
            lowered_to = parse_ai_builder_operating_limit(
                review_investigation_evidence_max_tokens,
                "review_investigation_evidence_max_tokens",
            )
        except ValueError as error:
            raise AIBuilderBadRequestException(
                str(error),
                code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
            ) from error
        # The bound itself is no override: the tenant follows the system
        # bound, including a later change of it, instead of pinning today's.
        if lowered_to == AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS:
            next_settings.pop("review_investigation_evidence_max_tokens", None)
        else:
            next_settings["review_investigation_evidence_max_tokens"] = lowered_to
    operating_updates = {
        "max_attachments": max_attachments,
        "max_message_chars": max_message_chars,
        "max_template_inspection_uncompressed_bytes": (
            max_template_inspection_uncompressed_bytes
        ),
        "max_template_placeholders": max_template_placeholders,
    }
    for field_name, value in operating_updates.items():
        if value is not None:
            next_settings[field_name] = parse_ai_builder_operating_limit(
                value,
                field_name,
            )

    for key in remove_keys or ():
        next_settings.pop(key, None)

    if next_settings:
        result["ai_builder"] = next_settings
    else:
        result.pop("ai_builder", None)
    return result
