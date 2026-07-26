from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from time import perf_counter_ns
from typing import Any, cast
from uuid import UUID

from eneo.ai_models.completion_models.completion_model import (
    FunctionDefinition,
    function_definition_to_tool,
)
from eneo.completion_models.domain.skill_context import (
    SkillContextMeasurement,
    measure_skill_context,
)
from eneo.skills.domain.skill import (
    MAX_RETAINED_SKILL_ACTIVATION_REJECTIONS,
    MAX_SKILL_ACTIVATIONS_PER_TURN,
    ResolvedSkillBinding,
    SkillActivationFallbackReason,
    SkillActivationRejectionReason,
    SkillTurnEffectiveMode,
    compose_skill_instructions,
)
from eneo.tokens.token_utils import (
    TokenCountSource,
    measure_provider_input_tokens,
)

SKILL_ACTIVATION_TOOL_NAME = "eneo_activate_skill"


class SkillPromptOwnershipError(RuntimeError):
    """The rendered prompt no longer belongs to the frozen Skill plan."""


class InvalidSkillToolCallError(RuntimeError):
    """Provider tool-call identifiers cannot form a valid transcript."""


@dataclass(frozen=True)
class FrozenSkillInstruction:
    """Provider-safe, exact per-turn Skill candidate."""

    activation_key: str
    binding: ResolvedSkillBinding
    initially_active: bool

    @property
    def display_name(self) -> str:
        return self.binding.display_name

    @property
    def description(self) -> str:
        return self.binding.description

    @property
    def position(self) -> int:
        return self.binding.position


@dataclass(frozen=True)
class SkillActivationSnapshot:
    effective_mode: SkillTurnEffectiveMode
    fallback_reason: SkillActivationFallbackReason | None
    initially_active: tuple[str, ...]
    active: tuple[str, ...]
    accepted: tuple[str, ...]
    repeated: tuple[str, ...]
    rejected: tuple[SkillActivationRejectionSnapshot, ...]
    measurement: SkillContextMeasurement
    activation_rounds: int
    selection_latency_ms: int

    @property
    def changed(self) -> bool:
        return bool(
            self.activation_rounds or self.accepted or self.repeated or self.rejected
        )


@dataclass(frozen=True)
class SkillActivationRejectionSnapshot:
    activation_key: str
    reason: SkillActivationRejectionReason


@dataclass(frozen=True)
class SkillActivationCandidateAssessment:
    """Non-mutating fit result for one on-demand candidate."""

    skill_id: UUID
    display_name: str
    activation_key: str
    prompt: str
    rejection_reason: SkillActivationRejectionReason | None
    measurement: SkillContextMeasurement


@dataclass(frozen=True)
class SkillActivationRequest:
    call_id: str
    activation_key: str | None


@dataclass(frozen=True)
class SkillActivationDecision:
    call_id: str
    provider_payload: dict[str, bool]


@dataclass(frozen=True)
class SkillActivationRoundResult:
    decisions: tuple[SkillActivationDecision, ...]
    accepted_any: bool


@dataclass(frozen=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class SkillToolCallApplication:
    external_calls: tuple[ProviderToolCall, ...]
    deferred_calls: tuple[ProviderToolCall, ...]
    assistant_message_appended: bool


def _compose_prompt(
    *,
    base_instructions: str,
    skills: tuple[FrozenSkillInstruction, ...],
) -> str:
    return compose_skill_instructions(
        base_instructions=base_instructions,
        bindings=[skill.binding for skill in skills],
    ).prompt


def _activation_tool(
    skills: tuple[FrozenSkillInstruction, ...],
) -> FunctionDefinition:
    catalogue = "\n".join(
        f"- {skill.activation_key}: {skill.display_name} — {skill.description}"
        for skill in skills
    )
    return FunctionDefinition(
        name=SKILL_ACTIVATION_TOOL_NAME,
        description=(
            "Load the full instructions for one available Skill when they are "
            "needed for the current request.\n\nAvailable Skills:\n"
            f"{catalogue}"
        ),
        schema={
            "type": "object",
            "properties": {
                "skill_key": {
                    "type": "string",
                    "enum": [skill.activation_key for skill in skills],
                }
            },
            "required": ["skill_key"],
            "additionalProperties": False,
        },
    )


class SkillActivationRuntime:
    """Concrete mutable state for one frozen selective-Skill turn."""

    def __init__(
        self,
        *,
        base_instructions: str,
        prompt: str,
        tool_definition: FunctionDefinition | None,
        effective_mode: SkillTurnEffectiveMode,
        fallback_reason: SkillActivationFallbackReason | None,
        skills: tuple[FrozenSkillInstruction, ...],
        blocked_keys: frozenset[str],
        max_activations_per_turn: int,
        context_share_percent: int,
        model_route: str,
        max_input_tokens: int,
        measurement: SkillContextMeasurement,
    ) -> None:
        self._base_instructions = base_instructions
        self.prompt = prompt
        self.tool_definition = tool_definition
        self._effective_mode = effective_mode
        self._fallback_reason = fallback_reason
        self._skills = skills
        self._skills_by_key = {skill.activation_key: skill for skill in skills}
        self._blocked_keys = blocked_keys
        self._max_activations_per_turn = max_activations_per_turn
        self._context_share_percent = context_share_percent
        self._model_route = model_route
        self._max_input_tokens = max_input_tokens
        self._measurement = measurement
        self._active_keys = {
            skill.activation_key for skill in skills if skill.initially_active
        }
        self._accepted: list[str] = []
        self._repeated: list[str] = []
        self._rejected: list[SkillActivationRejectionSnapshot] = []
        self._rejected_keys: set[tuple[str, SkillActivationRejectionReason]] = set()
        self._activation_rounds = 0
        self._selection_latency_ms = 0

    @classmethod
    def create(
        cls,
        *,
        base_instructions: str,
        skills: tuple[FrozenSkillInstruction, ...],
        blocked_keys: frozenset[str],
        selective_activation_enabled: bool,
        max_activations_per_turn: int,
        context_share_percent: int,
        model_route: str,
        max_input_tokens: int,
        supports_tool_calling: bool,
    ) -> SkillActivationRuntime:
        ordered = tuple(sorted(skills, key=lambda skill: skill.position))
        initially_active = tuple(skill for skill in ordered if skill.initially_active)
        on_demand = tuple(skill for skill in ordered if not skill.initially_active)
        required_prompt = _compose_prompt(
            base_instructions=base_instructions,
            skills=initially_active,
        )

        fallback_reason: SkillActivationFallbackReason | None = None
        tool: FunctionDefinition | None = None
        if not selective_activation_enabled:
            fallback_reason = (
                SkillActivationFallbackReason.SELECTIVE_ACTIVATION_DISABLED
            )
        elif not supports_tool_calling:
            fallback_reason = SkillActivationFallbackReason.MODEL_LACKS_TOOL_CALLING
        elif on_demand:
            candidate_tool = _activation_tool(on_demand)
            selective_measurement = measure_skill_context(
                base_instructions=base_instructions,
                composed_instructions=required_prompt,
                model_name=model_route,
                max_input_tokens=max_input_tokens,
                context_share_percent=context_share_percent,
                tools=[function_definition_to_tool(candidate_tool)],
            )
            if selective_measurement.source is TokenCountSource.FALLBACK_ESTIMATE:
                fallback_reason = (
                    SkillActivationFallbackReason.TOKEN_MEASUREMENT_UNAVAILABLE
                )
            elif selective_measurement.tokens <= selective_measurement.limit:
                return cls(
                    base_instructions=base_instructions,
                    prompt=required_prompt,
                    tool_definition=candidate_tool,
                    effective_mode=SkillTurnEffectiveMode.SELECTIVE,
                    fallback_reason=None,
                    skills=ordered,
                    blocked_keys=blocked_keys,
                    max_activations_per_turn=max_activations_per_turn,
                    context_share_percent=context_share_percent,
                    model_route=model_route,
                    max_input_tokens=max_input_tokens,
                    measurement=selective_measurement,
                )
            else:
                fallback_reason = SkillActivationFallbackReason.CATALOG_BUDGET_EXCEEDED

        measurement = measure_skill_context(
            base_instructions=base_instructions,
            composed_instructions=required_prompt,
            model_name=model_route,
            max_input_tokens=max_input_tokens,
            context_share_percent=context_share_percent,
        )
        return cls(
            base_instructions=base_instructions,
            prompt=required_prompt,
            tool_definition=tool,
            effective_mode=SkillTurnEffectiveMode.ALWAYS_ONLY,
            fallback_reason=fallback_reason,
            skills=ordered,
            blocked_keys=blocked_keys,
            max_activations_per_turn=max_activations_per_turn,
            context_share_percent=context_share_percent,
            model_route=model_route,
            max_input_tokens=max_input_tokens,
            measurement=measurement,
        )

    def _active_skills(
        self, extra_key: str | None = None
    ) -> tuple[FrozenSkillInstruction, ...]:
        keys = set(self._active_keys)
        if extra_key is not None:
            keys.add(extra_key)
        return tuple(skill for skill in self._skills if skill.activation_key in keys)

    def _measure(
        self, skills: tuple[FrozenSkillInstruction, ...]
    ) -> tuple[str, SkillContextMeasurement]:
        prompt = _compose_prompt(
            base_instructions=self._base_instructions,
            skills=skills,
        )
        tools = (
            [function_definition_to_tool(self.tool_definition)]
            if self.tool_definition is not None
            else []
        )
        return (
            prompt,
            measure_skill_context(
                base_instructions=self._base_instructions,
                composed_instructions=prompt,
                model_name=self._model_route,
                max_input_tokens=self._max_input_tokens,
                context_share_percent=self._context_share_percent,
                tools=tools,
            ),
        )

    def assess_on_demand_candidates(
        self,
        skill_ids: frozenset[UUID],
    ) -> tuple[SkillActivationCandidateAssessment, ...]:
        """Measure requested candidates against the current selective state.

        The method reuses the exact runtime measurement path without mutating
        activation state. Callers must handle plan-level fallback before asking
        for candidate results; an ALWAYS_ONLY runtime has no activatable
        candidates to assess. Unknown or blocked Skill ids are omitted because
        binding resolution owns membership and governance validation.
        """
        if self._effective_mode is not SkillTurnEffectiveMode.SELECTIVE:
            return ()

        assessments: list[SkillActivationCandidateAssessment] = []
        for skill in self._skills:
            if skill.initially_active or skill.binding.skill_id not in skill_ids:
                continue
            assessments.append(self._assess_candidate(skill))
        return tuple(assessments)

    def assess_provider_payload_candidates(
        self,
        skill_ids: frozenset[UUID],
        *,
        messages: list[dict[str, Any]],
        provider_tools: list[dict[str, Any]],
    ) -> tuple[SkillActivationCandidateAssessment, ...]:
        """Stage each candidate against the provider-visible request payload.

        Save-time preflight uses the same transcript mutation and token
        measurement as a real activation round. Each probe runs on a fork so
        neither the frozen turn state nor the caller's messages are changed.
        """
        assessments = self.assess_on_demand_candidates(skill_ids)
        provider_assessments: list[SkillActivationCandidateAssessment] = []
        for assessment in assessments:
            staged = self._fork()
            staged_messages = [message.copy() for message in messages]
            staged.apply_provider_tool_calls(
                calls=(
                    ProviderToolCall(
                        call_id=f"preflight-{assessment.activation_key}",
                        name=SKILL_ACTIVATION_TOOL_NAME,
                        arguments=json.dumps({"skill_key": assessment.activation_key}),
                    ),
                ),
                messages=cast("list[dict[str, object]]", staged_messages),
                provider_tools=cast(
                    "list[dict[str, object]]",
                    provider_tools,
                ),
            )
            snapshot = staged.snapshot()
            rejection_reason = next(
                (
                    rejection.reason
                    for rejection in snapshot.rejected
                    if rejection.activation_key == assessment.activation_key
                ),
                None,
            )
            provider_assessments.append(
                replace(
                    assessment,
                    prompt=staged.prompt,
                    rejection_reason=rejection_reason,
                    measurement=snapshot.measurement,
                )
            )
        return tuple(provider_assessments)

    def _assess_candidate(
        self,
        skill: FrozenSkillInstruction,
    ) -> SkillActivationCandidateAssessment:
        prompt, measurement = self._measure(self._active_skills(skill.activation_key))
        rejection_reason: SkillActivationRejectionReason | None = None
        if measurement.source is TokenCountSource.FALLBACK_ESTIMATE:
            rejection_reason = (
                SkillActivationRejectionReason.TOKEN_MEASUREMENT_UNAVAILABLE
            )
        elif measurement.tokens > measurement.limit:
            rejection_reason = SkillActivationRejectionReason.CONTEXT_LIMIT_EXCEEDED
        return SkillActivationCandidateAssessment(
            skill_id=skill.binding.skill_id,
            display_name=skill.display_name,
            activation_key=skill.activation_key,
            prompt=prompt,
            rejection_reason=rejection_reason,
            measurement=measurement,
        )

    @staticmethod
    def _provider_unavailable() -> dict[str, bool]:
        return {"activated": False, "unavailable": True}

    @staticmethod
    def _evidence_key(activation_key: str | None) -> str:
        if not activation_key:
            return "<invalid>"
        if len(activation_key) <= 128:
            return activation_key
        digest = hashlib.sha256(activation_key.encode()).hexdigest()[:16]
        return f"{activation_key[:110]}-{digest}"

    def _reject(
        self,
        *,
        activation_key: str | None,
        reason: SkillActivationRejectionReason,
    ) -> None:
        evidence_key = self._evidence_key(activation_key)
        identity = (evidence_key, reason)
        if (
            identity in self._rejected_keys
            or len(self._rejected) >= MAX_RETAINED_SKILL_ACTIVATION_REJECTIONS
        ):
            return
        self._rejected_keys.add(identity)
        self._rejected.append(
            SkillActivationRejectionSnapshot(
                activation_key=evidence_key,
                reason=reason,
            )
        )

    def _fork(self) -> SkillActivationRuntime:
        staged = SkillActivationRuntime(
            base_instructions=self._base_instructions,
            prompt=self.prompt,
            tool_definition=self.tool_definition,
            effective_mode=self._effective_mode,
            fallback_reason=self._fallback_reason,
            skills=self._skills,
            blocked_keys=self._blocked_keys,
            max_activations_per_turn=self._max_activations_per_turn,
            context_share_percent=self._context_share_percent,
            model_route=self._model_route,
            max_input_tokens=self._max_input_tokens,
            measurement=self._measurement,
        )
        staged._active_keys = set(self._active_keys)
        staged._accepted = list(self._accepted)
        staged._repeated = list(self._repeated)
        staged._rejected = list(self._rejected)
        staged._rejected_keys = set(self._rejected_keys)
        staged._activation_rounds = self._activation_rounds
        staged._selection_latency_ms = self._selection_latency_ms
        return staged

    def _commit(self, staged: SkillActivationRuntime) -> None:
        self.prompt = staged.prompt
        self._measurement = staged._measurement
        self._active_keys = staged._active_keys
        self._accepted = staged._accepted
        self._repeated = staged._repeated
        self._rejected = staged._rejected
        self._rejected_keys = staged._rejected_keys
        self._activation_rounds = staged._activation_rounds
        self._selection_latency_ms = staged._selection_latency_ms

    def record_reserved_tool_collision(self) -> None:
        self._reject(
            activation_key=SKILL_ACTIVATION_TOOL_NAME,
            reason=SkillActivationRejectionReason.RESERVED_TOOL_COLLISION,
        )

    def _apply_round(
        self,
        requests: tuple[SkillActivationRequest, ...],
        *,
        forced_rejections: dict[str, SkillActivationRejectionReason],
    ) -> SkillActivationRoundResult:
        decisions: list[SkillActivationDecision] = []
        accepted_any = False
        if requests:
            self._activation_rounds += 1

        for request in requests:
            key = request.activation_key
            forced_reason = forced_rejections.get(key or "")
            if forced_reason is not None:
                self._reject(
                    activation_key=key,
                    reason=forced_reason,
                )
                decisions.append(
                    SkillActivationDecision(
                        call_id=request.call_id,
                        provider_payload=self._provider_unavailable(),
                    )
                )
                continue

            if key in self._active_keys:
                if key not in self._repeated:
                    self._repeated.append(key)
                decisions.append(
                    SkillActivationDecision(
                        call_id=request.call_id,
                        provider_payload={
                            "activated": True,
                            "already_active": True,
                        },
                    )
                )
                continue

            if key in self._blocked_keys:
                self._reject(
                    activation_key=key,
                    reason=SkillActivationRejectionReason.BLOCKED,
                )
                decisions.append(
                    SkillActivationDecision(
                        call_id=request.call_id,
                        provider_payload=self._provider_unavailable(),
                    )
                )
                continue

            candidate = self._skills_by_key.get(key) if key is not None else None
            if candidate is None:
                self._reject(
                    activation_key=key,
                    reason=SkillActivationRejectionReason.UNKNOWN_KEY,
                )
                decisions.append(
                    SkillActivationDecision(
                        call_id=request.call_id,
                        provider_payload=self._provider_unavailable(),
                    )
                )
                continue

            assert key is not None
            if len(self._accepted) >= self._max_activations_per_turn:
                self._reject(
                    activation_key=key,
                    reason=SkillActivationRejectionReason.ACTIVATION_LIMIT_EXCEEDED,
                )
                decisions.append(
                    SkillActivationDecision(
                        call_id=request.call_id,
                        provider_payload=self._provider_unavailable(),
                    )
                )
                continue

            assessment = self._assess_candidate(candidate)
            if assessment.rejection_reason is not None:
                self._reject(
                    activation_key=key,
                    reason=assessment.rejection_reason,
                )
                decisions.append(
                    SkillActivationDecision(
                        call_id=request.call_id,
                        provider_payload=self._provider_unavailable(),
                    )
                )
                continue

            self._active_keys.add(key)
            self._accepted.append(key)
            self.prompt = assessment.prompt
            self._measurement = assessment.measurement
            accepted_any = True
            decisions.append(
                SkillActivationDecision(
                    call_id=request.call_id,
                    provider_payload={"activated": True},
                )
            )

        return SkillActivationRoundResult(
            decisions=tuple(decisions),
            accepted_any=accepted_any,
        )

    @staticmethod
    def _request_from_provider_call(
        call: ProviderToolCall,
    ) -> SkillActivationRequest:
        try:
            payload: object = json.loads(call.arguments)
        except (TypeError, ValueError):
            payload = None
        activation_key = None
        if isinstance(payload, dict):
            candidate_key = cast("dict[object, object]", payload).get("skill_key")
            if isinstance(candidate_key, str):
                activation_key = candidate_key
        return SkillActivationRequest(
            call_id=call.call_id,
            activation_key=activation_key,
        )

    @staticmethod
    def _capture_rendered_suffix(
        messages: list[dict[str, object]],
        *,
        previous_prompt: str,
    ) -> tuple[bool, str]:
        if messages and messages[0].get("role") == "system":
            rendered_prompt = messages[0].get("content")
            if not isinstance(rendered_prompt, str) or not rendered_prompt.startswith(
                previous_prompt
            ):
                raise SkillPromptOwnershipError(
                    "The rendered system prompt no longer starts with the frozen "
                    "Skill prompt"
                )
            return True, rendered_prompt[len(previous_prompt) :]
        return False, ""

    @staticmethod
    def _replace_system_prompt(
        messages: list[dict[str, object]],
        *,
        prompt: str,
        previous_prompt: str,
        had_system_prompt: bool,
        rendered_suffix: str,
    ) -> None:
        separator = "\n\n" if not previous_prompt and rendered_suffix else ""
        replacement: dict[str, object] = {
            "role": "system",
            "content": f"{prompt}{separator}{rendered_suffix}",
        }
        if had_system_prompt:
            messages[0] = replacement
        else:
            messages.insert(0, replacement)

    @staticmethod
    def _validate_provider_calls(calls: tuple[ProviderToolCall, ...]) -> None:
        call_ids = [call.call_id for call in calls]
        if any(not call_id for call_id in call_ids) or len(call_ids) != len(
            set(call_ids)
        ):
            raise InvalidSkillToolCallError(
                "The model produced an invalid tool call identifier"
            )

    @staticmethod
    def _append_provider_round(
        *,
        messages: list[dict[str, object]],
        calls: tuple[ProviderToolCall, ...],
        assistant_content: str | None,
        result: SkillActivationRoundResult,
    ) -> tuple[tuple[ProviderToolCall, ...], tuple[ProviderToolCall, ...]]:
        internal = tuple(
            call for call in calls if call.name == SKILL_ACTIVATION_TOOL_NAME
        )
        external = tuple(
            call for call in calls if call.name != SKILL_ACTIVATION_TOOL_NAME
        )
        messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    }
                    for call in calls
                ],
            }
        )
        decision_by_call_id = {
            decision.call_id: decision for decision in result.decisions
        }
        for call in internal:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": json.dumps(
                        decision_by_call_id[call.call_id].provider_payload
                    ),
                }
            )
        deferred = external if result.accepted_any else ()
        for call in deferred:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": json.dumps(
                        {
                            "deferred": True,
                            "reason": "skill_context_updated",
                            "retryable": True,
                        }
                    ),
                }
            )
        return (() if deferred else external), deferred

    def apply_provider_tool_calls(
        self,
        *,
        calls: tuple[ProviderToolCall, ...],
        messages: list[dict[str, object]],
        provider_tools: list[dict[str, object]] | None = None,
        assistant_content: str | None = None,
    ) -> SkillToolCallApplication:
        """Close internal calls and return external calls safe to dispatch."""

        internal = tuple(
            call for call in calls if call.name == SKILL_ACTIVATION_TOOL_NAME
        )
        if not internal:
            return SkillToolCallApplication(
                external_calls=calls,
                deferred_calls=(),
                assistant_message_appended=False,
            )
        selection_started_at = perf_counter_ns()
        self._validate_provider_calls(calls)
        requests = tuple(self._request_from_provider_call(call) for call in internal)
        if self.tool_definition is None:
            staged = self._fork()
            result = staged._apply_round(
                requests,
                forced_rejections={
                    request.activation_key or "": (
                        SkillActivationRejectionReason.ACTIVATION_UNAVAILABLE
                    )
                    for request in requests
                },
            )
            external, deferred = self._append_provider_round(
                messages=messages,
                calls=calls,
                assistant_content=assistant_content,
                result=result,
            )
            staged._selection_latency_ms = self._selection_latency_ms + (
                (perf_counter_ns() - selection_started_at) // 1_000_000
            )
            self._commit(staged)
            return SkillToolCallApplication(
                external_calls=external,
                deferred_calls=deferred,
                assistant_message_appended=True,
            )

        previous_prompt = self.prompt
        bounded_requests = requests[:MAX_SKILL_ACTIVATIONS_PER_TURN]
        overflow_requests = requests[MAX_SKILL_ACTIVATIONS_PER_TURN:]
        forced_rejections: dict[str, SkillActivationRejectionReason] = {}

        def stage_round(
            rejections: dict[str, SkillActivationRejectionReason],
        ) -> tuple[
            SkillActivationRuntime,
            list[dict[str, object]],
            tuple[ProviderToolCall, ...],
            tuple[ProviderToolCall, ...],
            tuple[str, ...],
        ]:
            staged = self._fork()
            result = staged._apply_round(
                bounded_requests,
                forced_rejections=rejections,
            )
            overflow_decisions = tuple(
                SkillActivationDecision(
                    call_id=request.call_id,
                    provider_payload=(
                        {
                            "activated": True,
                            "already_active": True,
                        }
                        if request.activation_key in staged._active_keys
                        else self._provider_unavailable()
                    ),
                )
                for request in overflow_requests
            )
            result = SkillActivationRoundResult(
                decisions=(*result.decisions, *overflow_decisions),
                accepted_any=result.accepted_any,
            )
            staged_messages = [message.copy() for message in messages]
            if result.accepted_any:
                had_system_prompt, rendered_suffix = self._capture_rendered_suffix(
                    messages,
                    previous_prompt=previous_prompt,
                )
                self._replace_system_prompt(
                    staged_messages,
                    prompt=staged.prompt,
                    previous_prompt=previous_prompt,
                    had_system_prompt=had_system_prompt,
                    rendered_suffix=rendered_suffix,
                )
            external, deferred = self._append_provider_round(
                messages=staged_messages,
                calls=calls,
                assistant_content=assistant_content,
                result=result,
            )
            newly_accepted = tuple(
                key for key in staged._accepted if key not in self._accepted
            )
            return (
                staged,
                staged_messages,
                external,
                deferred,
                newly_accepted,
            )

        while True:
            staged, staged_messages, external, deferred, newly_accepted = stage_round(
                forced_rejections
            )
            if not newly_accepted:
                break

            provider_measurement = measure_provider_input_tokens(
                cast("list[dict[str, Any]]", staged_messages),
                cast("list[dict[str, Any]]", provider_tools or []),
                self._model_route,
            )
            if provider_measurement.source is TokenCountSource.FALLBACK_ESTIMATE:
                forced_rejections.update(
                    {
                        key: (
                            SkillActivationRejectionReason.TOKEN_MEASUREMENT_UNAVAILABLE
                        )
                        for key in newly_accepted
                    }
                )
                continue
            if provider_measurement.tokens > self._max_input_tokens:
                overflow_key = newly_accepted[-1]
                for index, candidate_key in enumerate(newly_accepted[:-1]):
                    probe_rejections = {
                        **forced_rejections,
                        **{
                            later_key: (
                                SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED
                            )
                            for later_key in newly_accepted[index + 1 :]
                        },
                    }
                    (
                        _probe,
                        probe_messages,
                        _probe_external,
                        _probe_deferred,
                        _probe_accepted,
                    ) = stage_round(probe_rejections)
                    probe_measurement = measure_provider_input_tokens(
                        cast("list[dict[str, Any]]", probe_messages),
                        cast("list[dict[str, Any]]", provider_tools or []),
                        self._model_route,
                    )
                    if probe_measurement.source is TokenCountSource.FALLBACK_ESTIMATE:
                        forced_rejections.update(
                            {
                                key: (
                                    SkillActivationRejectionReason.TOKEN_MEASUREMENT_UNAVAILABLE
                                )
                                for key in newly_accepted
                            }
                        )
                        overflow_key = None
                        break
                    if probe_measurement.tokens > self._max_input_tokens:
                        overflow_key = candidate_key
                        break

                if overflow_key is not None:
                    forced_rejections[overflow_key] = (
                        SkillActivationRejectionReason.MODEL_CONTEXT_LIMIT_EXCEEDED
                    )
                continue
            break

        for request in overflow_requests:
            if request.activation_key in staged._active_keys:
                continue
            staged._reject(
                activation_key=request.activation_key,
                reason=SkillActivationRejectionReason.ACTIVATION_LIMIT_EXCEEDED,
            )
        staged._selection_latency_ms = self._selection_latency_ms + (
            (perf_counter_ns() - selection_started_at) // 1_000_000
        )
        self._commit(staged)
        messages[:] = staged_messages
        return SkillToolCallApplication(
            external_calls=external,
            deferred_calls=deferred,
            assistant_message_appended=True,
        )

    def snapshot(self) -> SkillActivationSnapshot:
        initially_active = tuple(
            skill.activation_key for skill in self._skills if skill.initially_active
        )
        return SkillActivationSnapshot(
            effective_mode=self._effective_mode,
            fallback_reason=self._fallback_reason,
            initially_active=initially_active,
            active=tuple(
                skill.activation_key
                for skill in self._skills
                if skill.activation_key in self._active_keys
            ),
            accepted=tuple(self._accepted),
            repeated=tuple(self._repeated),
            rejected=tuple(self._rejected),
            measurement=self._measurement,
            activation_rounds=self._activation_rounds,
            selection_latency_ms=self._selection_latency_ms,
        )
