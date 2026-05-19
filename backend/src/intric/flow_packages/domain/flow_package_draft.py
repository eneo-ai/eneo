from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from intric.flows.flow_authoring_spec import FlowDraftSpecCore


class FlowPackageFlowDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    spec: FlowDraftSpecCore

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> object:
        # `bool` is an `int` subclass; package schema versions must be literal integers.
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported schema version.")
        return value
