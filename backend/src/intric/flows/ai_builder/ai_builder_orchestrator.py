"""AI Builder orchestrator — structured JSON contract for the planner turn.

Every planner turn emits one JSON product with two halves:

- `planning_state_delta` — what the planner understood (signals added,
  slots resolved, optional architecture commit, optional draft plan).
  The delta carries `base_planning_state_version` so the repo's
  optimistic-concurrency guard can reject stale writes.
- `planner_action` — what the planner wants to do next. A discriminated
  union on `kind`: `ask_question`, `commit_architecture`,
  `confirm_requirements`, `propose_plan`.

This module is the scaffold only: parse + typed access. Action dispatch
and monotonicity guardrails land in later slices and import from here.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningSignal,
    ResolvedSlot,
)


class _OrchestratorModel(BaseModel):
    """Strict base for orchestrator I/O models.

    `extra="forbid"` catches planner drift at parse time — the most
    common failure mode is the LLM inventing new keys.
    """

    model_config = ConfigDict(extra="forbid")


class PlanningStateDelta(_OrchestratorModel):
    base_planning_state_version: NonNegativeInt
    signals_added: list[PlanningSignal] = Field(default_factory=list[PlanningSignal])
    slots_resolved: list[ResolvedSlot] = Field(default_factory=list[ResolvedSlot])
    architecture_commit: Optional[ArchitectureCommit] = None
    draft_plan: Optional[dict[str, Any]] = None


class AskQuestionPayload(_OrchestratorModel):
    question_id: str
    slot_name: str
    prompt: str


class CommitArchitecturePayload(_OrchestratorModel):
    note: str = ""


class ConfirmRequirementsPayload(_OrchestratorModel):
    summary: str


class ProposePlanPayload(_OrchestratorModel):
    plan_reference: str = "latest"


class AskQuestionAction(_OrchestratorModel):
    kind: Literal["ask_question"]
    payload: AskQuestionPayload


class CommitArchitectureAction(_OrchestratorModel):
    kind: Literal["commit_architecture"]
    payload: CommitArchitecturePayload


class ConfirmRequirementsAction(_OrchestratorModel):
    kind: Literal["confirm_requirements"]
    payload: ConfirmRequirementsPayload


class ProposePlanAction(_OrchestratorModel):
    kind: Literal["propose_plan"]
    payload: ProposePlanPayload


PlannerAction = Annotated[
    Union[
        AskQuestionAction,
        CommitArchitectureAction,
        ConfirmRequirementsAction,
        ProposePlanAction,
    ],
    Field(discriminator="kind"),
]


class PlannerOutput(_OrchestratorModel):
    planning_state_delta: PlanningStateDelta
    planner_action: PlannerAction


def parse_planner_output(raw: str | dict[str, Any]) -> PlannerOutput:
    """Parse a planner turn's JSON product into a typed PlannerOutput.

    Accepts either a JSON string or an already-decoded dict so callers
    can plumb through whatever their LLM transport hands back. Raises
    `pydantic.ValidationError` on any shape violation — unknown keys,
    unknown action kinds, negative version stamps, or payload shapes
    that don't match the declared `kind`.
    """
    payload = json.loads(raw) if isinstance(raw, str) else raw
    return PlannerOutput.model_validate(payload)


__all__ = [
    "AskQuestionAction",
    "AskQuestionPayload",
    "CommitArchitectureAction",
    "CommitArchitecturePayload",
    "ConfirmRequirementsAction",
    "ConfirmRequirementsPayload",
    "PlannerAction",
    "PlannerOutput",
    "PlanningStateDelta",
    "ProposePlanAction",
    "ProposePlanPayload",
    "parse_planner_output",
]
