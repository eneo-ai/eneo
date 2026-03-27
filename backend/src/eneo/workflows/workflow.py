from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from eneo.main.models import InDB
from eneo.services.service import Service


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
    filter: Optional[FilterInDB] = None


class WorkflowBase(BaseModel):
    name: str
    steps: list[Step]


class WorkflowInDB(InDB, WorkflowBase):
    steps: list[StepInDB]


# Rebuild models
Service.model_rebuild()
