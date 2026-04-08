from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from intric.main.models import InDB
from intric.services.service import Service


class FilterType(str, Enum):
    BOOLEAN = "boolean_filter"


class Filter(BaseModel):
    type: FilterType
    chain_breaker_message: str


class FilterInDB(InDB, Filter):
    pass


class Step(BaseModel):
    filter: Optional[Filter] = None
    service_id: UUID


class StepInDB(InDB, Step):
    service: Service
    filter: Optional[FilterInDB] = None  # type: ignore[assignment]  # intentional narrowing: FilterInDB extends Filter; Pydantic handles covariant override


class WorkflowBase(BaseModel):
    name: str
    steps: list[Step]


class WorkflowInDB(InDB, WorkflowBase):
    steps: list[StepInDB]  # type: ignore[assignment]  # intentional narrowing: list[StepInDB] is list[Step] at runtime via Pydantic covariant field


# Rebuild models
Service.model_rebuild()
