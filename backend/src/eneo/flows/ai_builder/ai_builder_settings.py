from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from eneo.completion_models.domain.model_capacity import (
    ModelCapacity,
    ModelCapacityNoFit,
    UnknownModelCapacityError,
)
from eneo.completion_models.domain.model_kwargs_capabilities import (
    request_may_think,
)
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
    parse_ai_builder_timing_seconds,
)
from eneo.main.ai_builder_timing_order import (
    TimingOrderRule,
    ai_builder_timing_order_violation,
)
from eneo.main.config import (
    AI_BUILDER_ANSWER_RESERVE_SHARE_DEFAULT,
    AI_BUILDER_CLASSIFICATION_REASONING_EFFORT_DEFAULT,
    AI_BUILDER_PROVIDER_CALL_CEILING_SECONDS_DEFAULT,
    AIBuilderClassificationReasoningEffort,
    get_settings,
)

AI_BUILDER_PROPOSAL_TIMEOUT_SECONDS = 300.0

# How often a classification reply cut off at the output cap is asked again
# with the identical request: runaway replies come per call, not per input, and
# a bounded retry is an invariant, not a tunable.
SLOT_CLASSIFICATION_CUT_OFF_REASKS = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class AIBuilderRequestBudget:
    """One provider call's budget, allocated from the selected model's limits.

    Input and answer share the model's input limit, so a request is allocated in
    two steps. ``plan`` reserves answer room once the required input is
    measured: the ceiling when it fits within the policy share of the room the
    required input leaves, otherwise that share, so optional input never
    crowds the answer out and the answer never crowds optional input out.
    ``resolve`` then measures the packed request whole and sends the model the
    most it may write in the room that remains, never a fixed number, unless
    the call's answer has a known bound of its own (``answer_cap_tokens``).
    """

    capacity: ModelCapacity
    safety_buffer_tokens: int
    # Silence deadline: the longest wait for the provider's next chunk.
    timeout_seconds: float
    # The share of the room after the required input that packing keeps free
    # for the answer. Dimensionless deployment policy, never a token count.
    answer_reserve_share: float = AI_BUILDER_ANSWER_RESERVE_SHARE_DEFAULT
    # The whole call's bound: whether it keeps producing or, for a call that
    # may think, never produces.
    ceiling_seconds: float = AI_BUILDER_PROVIDER_CALL_CEILING_SECONDS_DEFAULT
    request_id: str | None = None
    # Bounds the complete input only; the answer is never charged to it.
    input_cap_tokens: int | None = None
    # The most this kind of call's answer can need, below the model's own
    # ceiling. None leaves the answer bounded by the model alone.
    answer_cap_tokens: int | None = None

    def __post_init__(self) -> None:
        missing = self.capacity.missing_dimensions()
        if missing:
            raise UnknownModelCapacityError(missing)
        if self.input_cap_tokens is not None and self.input_cap_tokens < 1:
            raise ValueError("AI Builder input cap must be positive")
        if self.answer_cap_tokens is not None and self.answer_cap_tokens < 1:
            raise ValueError("AI Builder answer cap must be positive")
        if self.safety_buffer_tokens < 0:
            raise ValueError("AI Builder safety buffer cannot be negative")
        if not (
            math.isfinite(self.answer_reserve_share)
            and 0 < self.answer_reserve_share < 1
        ):
            raise ValueError("AI Builder answer reserve share must be within (0, 1)")
        if not (math.isfinite(self.timeout_seconds) and self.timeout_seconds > 0):
            raise ValueError("AI Builder request timeout must be positive and finite")
        if not (
            math.isfinite(self.ceiling_seconds)
            and self.ceiling_seconds >= self.timeout_seconds
        ):
            raise ValueError(
                "AI Builder call ceiling must be finite and not below the silence deadline"
            )

    def first_output_timeout_seconds(
        self, *, reasoning_effort: object, route_reasons: bool
    ) -> float:
        """The longest wait before the model's first output for this request.

        A call that thinks may yield no output while it does (providers that
        stream their reasoning do yield it), and that is not different from a
        hung call until output arrives, so a request that may think waits for
        the whole-call ceiling; any other request waits only the silence
        deadline. Once output has started a stall is detectable and the
        silence deadline applies again.
        """

        if request_may_think(
            reasoning_effort=reasoning_effort, route_reasons=route_reasons
        ):
            return self.ceiling_seconds
        return self.timeout_seconds

    @property
    def request_budget_tokens(self) -> int:
        return self.capacity.require_input_tokens()

    @property
    def model_output_ceiling_tokens(self) -> int:
        return self.capacity.require_output_tokens()

    @property
    def answer_ceiling_tokens(self) -> int:
        """The most the answer may take: the model's ceiling or the call's cap."""

        if self.answer_cap_tokens is None:
            return self.model_output_ceiling_tokens
        return min(self.model_output_ceiling_tokens, self.answer_cap_tokens)

    @property
    def usable_request_budget_tokens(self) -> int:
        """What input and answer share once the safety buffer is set aside."""

        return self.request_budget_tokens - self.safety_buffer_tokens

    def plan(
        self, *, required_input_tokens: int
    ) -> AIBuilderPlannedRequestBudget | None:
        """Allocate the request budget for a request whose required input is measured.

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
        room = self.usable_request_budget_tokens - required_input_tokens
        if room < 1:
            return None
        reserved_output_tokens = min(
            self.answer_ceiling_tokens,
            math.ceil(room * self.answer_reserve_share),
        )
        available_input_tokens = self.capacity.input_allowance(
            output_reserve_tokens=reserved_output_tokens,
            safety_tokens=self.safety_buffer_tokens,
        )
        if self.input_cap_tokens is not None:
            available_input_tokens = min(available_input_tokens, self.input_cap_tokens)
        return AIBuilderPlannedRequestBudget(
            capacity=self.capacity,
            safety_buffer_tokens=self.safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            ceiling_seconds=self.ceiling_seconds,
            timeout_seconds=self.timeout_seconds,
            request_id=self.request_id,
            input_cap_tokens=self.input_cap_tokens,
            answer_cap_tokens=self.answer_cap_tokens,
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
            capacity=self.capacity,
            safety_buffer_tokens=self.safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            ceiling_seconds=self.ceiling_seconds,
            timeout_seconds=self.timeout_seconds,
            request_id=self.request_id,
            input_cap_tokens=self.input_cap_tokens,
            answer_cap_tokens=self.answer_cap_tokens,
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
        provider_output_cap_tokens = self.capacity.resolve_output_cap(
            input_tokens=input_tokens,
            safety_tokens=self.safety_buffer_tokens,
            caller_cap=self.answer_cap_tokens,
        )
        if isinstance(provider_output_cap_tokens, ModelCapacityNoFit):
            return None
        return AIBuilderResolvedRequestBudget(
            capacity=self.capacity,
            safety_buffer_tokens=self.safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            ceiling_seconds=self.ceiling_seconds,
            timeout_seconds=self.timeout_seconds,
            request_id=self.request_id,
            input_cap_tokens=self.input_cap_tokens,
            answer_cap_tokens=self.answer_cap_tokens,
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
    # See AIBuilderRequestBudget.ceiling_seconds.
    call_ceiling_seconds: float = AI_BUILDER_PROVIDER_CALL_CEILING_SECONDS_DEFAULT
    # Classification shares the proposal deadline unless deployment policy
    # explicitly gives it a different one.
    classification_timeout_seconds: float | None = None
    # See Settings.ai_builder_classification_ceiling_seconds.
    classification_ceiling_seconds: float | None = None
    # See Settings.ai_builder_classification_answer_cap_tokens.
    classification_answer_cap_tokens: int | None = None
    classification_reasoning_effort: AIBuilderClassificationReasoningEffort = (
        AI_BUILDER_CLASSIFICATION_REASONING_EFFORT_DEFAULT
    )
    silence_timeout_seconds: float = AI_BUILDER_PROPOSAL_TIMEOUT_SECONDS
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
    # The admin's own deadline settings, None where the field above is
    # the deployment default. They say which side of an ordering conflict an
    # admin can change, and what the settings page shows as the override.
    silence_timeout_override_seconds: int | None = None
    call_ceiling_override_seconds: int | None = None

    def answer_reserve_tokens(
        self,
        *,
        capacity: ModelCapacity,
        required_input_tokens: int,
    ) -> int:
        """The answer room packing keeps free beside ``required_input_tokens``.

        For a packer that runs before the request's prompt exists (attached
        sources are read first), with the policy's conversation minimum
        standing in for the input it cannot measure yet. A budget with no room
        keeps the whole ceiling: such a packer admits nothing, and the request
        is refused where it is measured.
        """

        planned = self.proposal_request_budget(
            capacity=capacity,
        ).plan(required_input_tokens=required_input_tokens)
        return (
            capacity.require_output_tokens()
            if planned is None
            else planned.reserved_output_tokens
        )

    def classification_request_budget(
        self,
        *,
        capacity: ModelCapacity,
        request_id: str | None = None,
    ) -> AIBuilderRequestBudget:
        timeout_seconds = (
            self.classification_timeout_seconds
            if self.classification_timeout_seconds is not None
            else self.silence_timeout_seconds
        )
        return AIBuilderRequestBudget(
            capacity=capacity,
            safety_buffer_tokens=self.conversation_safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            ceiling_seconds=(
                self.classification_ceiling_seconds
                if self.classification_ceiling_seconds is not None
                else min(
                    (1 + SLOT_CLASSIFICATION_CUT_OFF_REASKS) * timeout_seconds,
                    self.call_ceiling_seconds,
                )
            ),
            timeout_seconds=timeout_seconds,
            request_id=request_id,
            answer_cap_tokens=self.classification_answer_cap_tokens,
        )

    def review_request_budget(
        self,
        *,
        capacity: ModelCapacity,
        request_id: str | None = None,
    ) -> AIBuilderRequestBudget:
        """Review uses the selected model's limits and the tenant's evidence cap."""

        return AIBuilderRequestBudget(
            capacity=capacity,
            input_cap_tokens=self.review_evidence_max_input_tokens,
            safety_buffer_tokens=self.conversation_safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            ceiling_seconds=self.call_ceiling_seconds,
            timeout_seconds=self.silence_timeout_seconds,
            request_id=request_id,
        )

    def proposal_request_budget(
        self,
        *,
        capacity: ModelCapacity,
        request_id: str | None = None,
        carries_review_evidence: bool = False,
    ) -> AIBuilderRequestBudget:
        return AIBuilderRequestBudget(
            capacity=capacity,
            input_cap_tokens=(
                self.review_evidence_max_input_tokens
                if carries_review_evidence
                else None
            ),
            safety_buffer_tokens=self.conversation_safety_buffer_tokens,
            answer_reserve_share=self.answer_reserve_share,
            ceiling_seconds=self.call_ceiling_seconds,
            timeout_seconds=self.silence_timeout_seconds,
            request_id=request_id,
        )


class AIBuilderTimingOrderError(AIBuilderBadRequestException):
    """Effective provider-call deadlines that cannot work together."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
        )


def _timing_value(seconds: float, *, set_by_admin: bool) -> str:
    origin = (
        "set in Admin > Flow settings" if set_by_admin else "the deployment default"
    )
    return f"{seconds:g} s, {origin}"


_TIMING_ORDER_REFUSALS: dict[TimingOrderRule, str] = {
    "silence_above_call_ceiling": (
        "The silence timeout ({value}) is longer than the call ceiling ({bound}). "
        "Lower the silence timeout or raise the call ceiling."
    ),
    "classification_silence_above_call_ceiling": (
        "The classification silence timeout ({value}) is longer than the call "
        "ceiling ({bound}). Raise the call ceiling."
    ),
    "classification_ceiling_above_call_ceiling": (
        "The classification call ceiling ({value}) is longer than the call "
        "ceiling ({bound}). Raise the call ceiling."
    ),
    "classification_ceiling_below_classification_silence": (
        "The classification call ceiling ({value}) is shorter than the "
        "classification silence timeout ({bound}). Lower the silence timeout."
    ),
}


def _set_by_admin(
    rule: TimingOrderRule, policy: AIBuilderBudgetPolicy
) -> tuple[bool, bool]:
    """Whether the violating value and the bound it breaks are the admin's."""

    silence = policy.silence_timeout_override_seconds is not None
    ceiling = policy.call_ceiling_override_seconds is not None
    if rule == "silence_above_call_ceiling":
        return silence, ceiling
    if rule == "classification_ceiling_below_classification_silence":
        # An unset classification silence is the silence timeout itself.
        return False, silence and policy.classification_timeout_seconds is None
    # Only the deployment sets classification deadlines.
    return False, ceiling


def check_ai_builder_timing_order(policy: AIBuilderBudgetPolicy) -> None:
    """Refuse effective deadlines that the request budget cannot honour.

    The rule itself is ``ai_builder_timing_order_violation``; deployment
    startup applies it to env values alone. A tenant value can break it against
    an env value, so the resolver and the settings writer apply it to the
    effective deadlines and word the refusal with both values and where each
    comes from, instead of the request budget's bare ValueError.
    """

    violation = ai_builder_timing_order_violation(
        silence_seconds=policy.silence_timeout_seconds,
        call_ceiling_seconds=policy.call_ceiling_seconds,
        classification_silence_seconds=policy.classification_timeout_seconds,
        classification_ceiling_seconds=policy.classification_ceiling_seconds,
    )
    if violation is None:
        return
    value_by_admin, bound_by_admin = _set_by_admin(violation.rule, policy)
    raise AIBuilderTimingOrderError(
        _TIMING_ORDER_REFUSALS[violation.rule].format(
            value=_timing_value(violation.value, set_by_admin=value_by_admin),
            bound=_timing_value(violation.bound, set_by_admin=bound_by_admin),
        )
    )


def deployment_ai_builder_budget_policy() -> AIBuilderBudgetPolicy:
    """The deployment (env) values an absent admin setting inherits."""

    return _default_policy()


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
        call_ceiling_seconds=float(
            getattr(
                source,
                "ai_builder_provider_call_ceiling_seconds",
                AI_BUILDER_PROVIDER_CALL_CEILING_SECONDS_DEFAULT,
            )
        ),
        classification_timeout_seconds=(
            float(source.ai_builder_classification_timeout_seconds)
            if source.ai_builder_classification_timeout_seconds is not None
            else None
        ),
        classification_ceiling_seconds=getattr(
            source, "ai_builder_classification_ceiling_seconds", None
        ),
        classification_answer_cap_tokens=getattr(
            source, "ai_builder_classification_answer_cap_tokens", None
        ),
        classification_reasoning_effort=getattr(
            source,
            "ai_builder_classification_reasoning_effort",
            AI_BUILDER_CLASSIFICATION_REASONING_EFFORT_DEFAULT,
        ),
        silence_timeout_seconds=float(source.ai_builder_proposal_timeout_seconds),
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


def _parse_timing_seconds(value: object, key: str) -> int:
    try:
        return parse_ai_builder_timing_seconds(value, key)
    except ValueError as error:
        raise AIBuilderBadRequestException(
            str(error),
            code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
        ) from error


def _with_timing_overrides(
    policy: AIBuilderBudgetPolicy, raw: Mapping[str, object]
) -> AIBuilderBudgetPolicy:
    """Apply the tenant's deadline settings to the deployment values in ``policy``."""

    silence = (
        _parse_timing_seconds(raw["silence_timeout_seconds"], "silence_timeout_seconds")
        if "silence_timeout_seconds" in raw
        else None
    )
    ceiling = (
        _parse_timing_seconds(raw["call_ceiling_seconds"], "call_ceiling_seconds")
        if "call_ceiling_seconds" in raw
        else None
    )
    return replace(
        policy,
        silence_timeout_seconds=(
            policy.silence_timeout_seconds if silence is None else float(silence)
        ),
        call_ceiling_seconds=(
            policy.call_ceiling_seconds if ceiling is None else float(ceiling)
        ),
        silence_timeout_override_seconds=silence,
        call_ceiling_override_seconds=ceiling,
    )


def resolve_ai_builder_budget_policy(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    defaults: Any | None = None,
    check_timing_order: bool = True,
) -> AIBuilderBudgetPolicy:
    """The effective policy: deployment values, then the tenant's overrides.

    Turns keep ``check_timing_order`` so a conflicting pair is refused with a
    message before any provider work. Readers that enforce no deadline (the
    admin page and its audit, the limits endpoint, the model list, the
    readiness CLI) pass False: the admin must still be able to open the page
    and repair the conflict (for example after the deployment lowered its call
    ceiling below a tenant's silence timeout).
    """

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

    policy = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=safety_buffer,
        minimum_conversation_budget_tokens=minimum_budget,
        answer_reserve_share=resolved_defaults.answer_reserve_share,
        call_ceiling_seconds=resolved_defaults.call_ceiling_seconds,
        classification_timeout_seconds=(
            resolved_defaults.classification_timeout_seconds
        ),
        classification_ceiling_seconds=(
            resolved_defaults.classification_ceiling_seconds
        ),
        classification_answer_cap_tokens=(
            resolved_defaults.classification_answer_cap_tokens
        ),
        classification_reasoning_effort=(
            resolved_defaults.classification_reasoning_effort
        ),
        silence_timeout_seconds=resolved_defaults.silence_timeout_seconds,
        max_attachments=operating_limits["max_attachments"],
        max_message_chars=operating_limits["max_message_chars"],
        max_template_inspection_uncompressed_bytes=operating_limits[
            "max_template_inspection_uncompressed_bytes"
        ],
        max_template_placeholders=operating_limits["max_template_placeholders"],
        review_evidence_max_input_tokens=review_evidence_cap,
        review_investigation_evidence_max_tokens=investigation_evidence_cap,
    )
    policy = _with_timing_overrides(policy, raw)
    if check_timing_order:
        check_ai_builder_timing_order(policy)
    return policy


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
    silence_timeout_seconds: int | None = None,
    call_ceiling_seconds: int | None = None,
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

    timing_updates = {
        "silence_timeout_seconds": silence_timeout_seconds,
        "call_ceiling_seconds": call_ceiling_seconds,
    }
    for field_name, value in timing_updates.items():
        if value is not None:
            next_settings[field_name] = _parse_timing_seconds(value, field_name)

    for key in remove_keys or ():
        next_settings.pop(key, None)

    # Only a change of a deadline is held to the ordering rule: an unrelated
    # edit must not fail because the deployment changed under an old pair.
    timing_touched = {
        field_name for field_name, value in timing_updates.items() if value is not None
    } | (set(remove_keys or ()) & set(timing_updates))
    if timing_touched:
        check_ai_builder_timing_order(
            _with_timing_overrides(_default_policy(), next_settings)
        )

    if next_settings:
        result["ai_builder"] = next_settings
    else:
        result.pop("ai_builder", None)
    return result
