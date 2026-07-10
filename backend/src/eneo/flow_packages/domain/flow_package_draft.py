from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from eneo.flows.domain.flow import FlowRuntimeInputConfig
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore


class FlowPackageRuntimeInputConfig(FlowRuntimeInputConfig):
    model_config = ConfigDict(extra="forbid", strict=True)


class FlowPackageItemMapConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: StrictBool = True


class FlowPackageStepInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    runtime_input: FlowPackageRuntimeInputConfig | None = None
    item_map: FlowPackageItemMapConfig | None = None


class FlowPackageStepOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    citation_mode: Literal["off", "inline_inref_sidecar"] | None = None


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
