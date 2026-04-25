"""Suitability checks for the AI Builder LLM-facing planner contract."""

from __future__ import annotations

from pydantic import BaseModel

from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionPayload,
    PlannerOutput,
    PlanningStateDelta,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningSignal,
    ResolvedSlot,
)

LLM_FACING_MODELS: tuple[type[BaseModel], ...] = (
    PlanningStateDelta,
    AskQuestionPayload,
    ArchitectureCommitDraft,
    PlanningSignal,
    ResolvedSlot,
)

SUSPICIOUS_SUFFIXES: tuple[str, ...] = (
    "_hash",
    "_at",
    "_version",
    "_id",
)

# Every suspicious-looking field that remains in an LLM-facing model
# must have an explicit ownership classification. This keeps legitimate
# copy tokens and canonical ids visible while rejecting accidental
# reintroduction of server-derived mechanics.
FIELD_OWNERSHIP_CLASSIFICATION: dict[str, str] = {
    "PlanningStateDelta.base_planning_state_version": "server_provided_copy_token",
    "AskQuestionPayload.question_id": "model_owned_canonical_question_id",
    "PlanningSignal.question_id": "self_reported_guardrail_claim",
}


def test_suspicious_llm_facing_fields_are_explicitly_classified() -> None:
    discovered: set[str] = set()
    for model in LLM_FACING_MODELS:
        for field_name in model.model_fields:
            if field_name.endswith(SUSPICIOUS_SUFFIXES):
                discovered.add(f"{model.__name__}.{field_name}")

    assert discovered == set(FIELD_OWNERSHIP_CLASSIFICATION), (
        "LLM-facing DTOs gained or lost suspicious fields. Classify each "
        "field as model-owned semantic choice, server-provided copy token, "
        "or server-owned derived value before exposing it to the planner."
    )


def test_planner_schema_does_not_expose_server_derived_commit_fields() -> None:
    field_names = _schema_property_names(PlannerOutput.model_json_schema())

    assert "architecture_hash" not in field_names
    assert "committed_at" not in field_names


def _schema_property_names(value: object) -> set[str]:
    if isinstance(value, dict):
        found: set[str] = set()
        properties = value.get("properties")
        if isinstance(properties, dict):
            found.update(str(key) for key in properties)
        for nested in value.values():
            found.update(_schema_property_names(nested))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for nested in value:
            found.update(_schema_property_names(nested))
        return found
    return set()
