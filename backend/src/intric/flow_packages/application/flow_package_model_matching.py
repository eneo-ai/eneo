from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from intric.flow_packages.domain.flow_package_import_plan import (
    MAX_IMPORT_PLAN_SUGGESTIONS,
    FlowPackageImportPlanStatus,
    FlowPackageModelCandidate,
    FlowPackageModelDependencyResolution,
    FlowPackageModelMatchIssue,
    FlowPackagePolicyStatus,
    FlowPackageRejectedModelCandidate,
)
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageCompletionModelConstraints,
    FlowPackageModelIdentity,
    FlowPackageModelRequirement,
)

_IdentityKey: TypeAlias = tuple[str, str]

_TESTED_IDENTITY_RANK = 0
_PUBLISHER_SUGGESTED_IDENTITY_RANK = 1
_UNKNOWN_IDENTITY_RANK = 2


@dataclass(frozen=True)
class _ModelCandidateEvaluation:
    candidate: FlowPackageModelCandidate
    rejection_reasons: tuple[FlowPackageModelMatchIssue, ...]
    selection_warnings: tuple[FlowPackageModelMatchIssue, ...]
    identity_rank: int

    def __post_init__(self) -> None:
        if self.rejection_reasons and self.selection_warnings:
            raise ValueError(
                "Rejected model candidates cannot carry selection warnings."
            )

    @property
    def is_eligible(self) -> bool:
        return not self.rejection_reasons


@dataclass(frozen=True)
class _ModelResolutionOutcome:
    status: FlowPackageImportPlanStatus
    publish_blocks: bool
    auto_select_allowed: bool
    suggestions: list[FlowPackageModelCandidate]
    selection_warnings: list[FlowPackageModelMatchIssue]


def resolve_model_requirement(
    *,
    requirement: FlowPackageModelRequirement,
    candidates: tuple[FlowPackageModelCandidate, ...],
) -> FlowPackageModelDependencyResolution:
    tested_identities = _identity_key_set(
        tuple(requirement.matching_preferences.tested_with)
    )
    publisher_suggested_identities = _identity_key_set(
        tuple(requirement.matching_preferences.publisher_suggested)
    )
    policy_status = _policy_status(requirement)
    evaluations = [
        _evaluate_candidate(
            requirement=requirement,
            candidate=candidate,
            tested_identities=tested_identities,
            publisher_suggested_identities=publisher_suggested_identities,
        )
        for candidate in candidates
    ]
    eligible_evaluations = sorted(
        (evaluation for evaluation in evaluations if evaluation.is_eligible),
        key=_evaluation_sort_key,
    )
    rejected_candidates = [
        FlowPackageRejectedModelCandidate(
            candidate=evaluation.candidate,
            reasons=list(evaluation.rejection_reasons),
        )
        for evaluation in evaluations
        if evaluation.rejection_reasons
    ]
    outcome = _resolution_outcome(
        required=requirement.required,
        eligible_evaluations=eligible_evaluations,
        policy_status=policy_status,
    )

    return FlowPackageModelDependencyResolution(
        slot_ref=requirement.slot_ref,
        required=requirement.required,
        used_by_steps=list(requirement.used_by_steps),
        data_sensitivity=requirement.data_sensitivity,
        guidance=requirement.guidance,
        model_kind=requirement.model_kind,
        matching_preferences=requirement.matching_preferences,
        completion_constraints=requirement.completion_constraints,
        status=outcome.status,
        publish_blocks=outcome.publish_blocks,
        auto_select_allowed=outcome.auto_select_allowed,
        suggestions=outcome.suggestions,
        total_candidate_count=len(candidates),
        eligible_candidate_count=len(eligible_evaluations),
        policy_status=policy_status,
        selection_warnings=outcome.selection_warnings,
        rejected_candidates=rejected_candidates,
    )


def _evaluate_candidate(
    *,
    requirement: FlowPackageModelRequirement,
    candidate: FlowPackageModelCandidate,
    tested_identities: frozenset[_IdentityKey],
    publisher_suggested_identities: frozenset[_IdentityKey],
) -> _ModelCandidateEvaluation:
    rejection_reasons = hard_model_candidate_rejection_reasons(
        requirement=requirement,
        candidate=candidate,
    )
    identity_rank, selection_warnings = _identity_rank_and_warnings(
        candidate.identity,
        tested_identities=tested_identities,
        publisher_suggested_identities=publisher_suggested_identities,
    )
    if rejection_reasons:
        selection_warnings = ()
    return _ModelCandidateEvaluation(
        candidate=candidate,
        rejection_reasons=rejection_reasons,
        selection_warnings=selection_warnings,
        identity_rank=identity_rank,
    )


def hard_model_candidate_rejection_reasons(
    *,
    requirement: FlowPackageModelRequirement,
    candidate: FlowPackageModelCandidate,
) -> tuple[FlowPackageModelMatchIssue, ...]:
    if candidate.model_kind is not requirement.model_kind:
        return (FlowPackageModelMatchIssue.MODEL_KIND_MISMATCH,)

    reasons: list[FlowPackageModelMatchIssue] = []
    if requirement.completion_constraints is not None:
        reasons.extend(
            _completion_constraint_rejections(
                requirement.completion_constraints,
                candidate,
            )
        )
    return tuple(sorted(set(reasons), key=lambda reason: reason.value))


def _completion_constraint_rejections(
    constraints: FlowPackageCompletionModelConstraints,
    candidate: FlowPackageModelCandidate,
) -> list[FlowPackageModelMatchIssue]:
    reasons: list[FlowPackageModelMatchIssue] = []
    if constraints.minimum_context_tokens is not None and (
        candidate.max_context_tokens is None
        or candidate.max_context_tokens < constraints.minimum_context_tokens
    ):
        reasons.append(FlowPackageModelMatchIssue.MODEL_CONTEXT_TOO_SMALL)
    if constraints.requires_vision and not candidate.supports_vision:
        reasons.append(FlowPackageModelMatchIssue.MODEL_VISION_REQUIRED)
    if constraints.requires_reasoning and not candidate.supports_reasoning:
        reasons.append(FlowPackageModelMatchIssue.MODEL_REASONING_REQUIRED)
    if constraints.requires_tool_calling and not candidate.supports_tool_calling:
        reasons.append(FlowPackageModelMatchIssue.MODEL_TOOL_CALLING_REQUIRED)
    return reasons


def _identity_rank_and_warnings(
    identity: FlowPackageModelIdentity,
    *,
    tested_identities: frozenset[_IdentityKey],
    publisher_suggested_identities: frozenset[_IdentityKey],
) -> tuple[int, tuple[FlowPackageModelMatchIssue, ...]]:
    identity_key = _identity_key(identity)
    if identity_key in tested_identities:
        return _TESTED_IDENTITY_RANK, ()
    if identity_key in publisher_suggested_identities:
        return _PUBLISHER_SUGGESTED_IDENTITY_RANK, ()
    return (
        _UNKNOWN_IDENTITY_RANK,
        (FlowPackageModelMatchIssue.MODEL_IDENTITY_NOT_PREFERRED,),
    )


def _resolution_outcome(
    *,
    required: bool,
    eligible_evaluations: list[_ModelCandidateEvaluation],
    policy_status: FlowPackagePolicyStatus,
) -> _ModelResolutionOutcome:
    if not eligible_evaluations:
        if required:
            return _ModelResolutionOutcome(
                status=FlowPackageImportPlanStatus.UNRESOLVED_REQUIRED,
                publish_blocks=True,
                auto_select_allowed=False,
                suggestions=[],
                selection_warnings=[],
            )
        return _ModelResolutionOutcome(
            status=FlowPackageImportPlanStatus.SKIPPED_OPTIONAL,
            publish_blocks=False,
            auto_select_allowed=False,
            suggestions=[],
            selection_warnings=[],
        )

    suggestions = [
        evaluation.candidate
        for evaluation in eligible_evaluations[:MAX_IMPORT_PLAN_SUGGESTIONS]
    ]
    if not required:
        return _ModelResolutionOutcome(
            status=FlowPackageImportPlanStatus.SKIPPED_OPTIONAL,
            publish_blocks=False,
            auto_select_allowed=False,
            suggestions=suggestions,
            selection_warnings=[],
        )

    selected_evaluation = eligible_evaluations[0]
    is_exact_allowed = (
        selected_evaluation.identity_rank == _TESTED_IDENTITY_RANK
        and policy_status is FlowPackagePolicyStatus.ALLOWED
    )
    return _ModelResolutionOutcome(
        status=(
            FlowPackageImportPlanStatus.RESOLVED_EXACT
            if is_exact_allowed
            else FlowPackageImportPlanStatus.REQUIRES_HUMAN_CONFIRMATION
        ),
        publish_blocks=not is_exact_allowed,
        auto_select_allowed=is_exact_allowed,
        suggestions=suggestions,
        selection_warnings=list(selected_evaluation.selection_warnings),
    )


def _policy_status(
    requirement: FlowPackageModelRequirement,
) -> FlowPackagePolicyStatus:
    if requirement.data_sensitivity is None:
        return FlowPackagePolicyStatus.ALLOWED
    return FlowPackagePolicyStatus.UNKNOWN


def _evaluation_sort_key(
    evaluation: _ModelCandidateEvaluation,
) -> tuple[int, int, int, str, str, str]:
    candidate = evaluation.candidate
    return (
        evaluation.identity_rank,
        -(candidate.max_context_tokens or 0),
        len(evaluation.selection_warnings),
        candidate.label.casefold(),
        candidate.local_kind.value,
        str(candidate.local_id),
    )


def _identity_key_set(
    identities: tuple[FlowPackageModelIdentity, ...],
) -> frozenset[_IdentityKey]:
    return frozenset(_identity_key(identity) for identity in identities)


def _identity_key(identity: FlowPackageModelIdentity) -> _IdentityKey:
    return identity.provider, identity.model
