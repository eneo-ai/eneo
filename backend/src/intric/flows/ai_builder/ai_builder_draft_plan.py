from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class DraftPlanEnvelope(BaseModel):
    """Strict envelope consumed by the legacy materialization bridge.

    This is intentionally not part of the planner `PlannerOutput`
    contract. Plan proposal now flows through the task-specific
    create/edit tool-call path; this envelope remains only for the
    isolated bridge tests and any downstream compiler code still using
    that shape.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: Optional[str] = None
    steps: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    form_fields: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


__all__ = ["DraftPlanEnvelope"]
