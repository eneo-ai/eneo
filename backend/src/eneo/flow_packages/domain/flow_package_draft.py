from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

from eneo.flows.domain.flow import FlowRuntimeInputConfig
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore


class FlowPackageRuntimeInputConfig(FlowRuntimeInputConfig):
    model_config = ConfigDict(extra="forbid", strict=True)


class FlowPackageItemMapConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: StrictBool = True
    # An enabled item map must carry its fan-out ceiling: flow validation
    # rejects one without it, on export and again on import.
    max_items: Annotated[StrictInt, Field(gt=0)] | None = None


class FlowPackageStepInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    runtime_input: FlowPackageRuntimeInputConfig | None = None
    item_map: FlowPackageItemMapConfig | None = None


class FlowPackageSpeakerMappingConfig(BaseModel):
    """The speaker-mapping block: form field names and a name-inference flag.

    Every value describes the flow's own form, so the block travels as-is;
    the importing flow's validation checks the fields exist there.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    participants_field: Annotated[StrictStr, Field(min_length=1)] | None = None
    speaker_count_field: Annotated[StrictStr, Field(min_length=1)] | None = None
    infer_names: StrictBool | None = None


class FlowPackageStepOutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    citation_mode: Literal["off", "inline_inref_sidecar"] | None = None
    speaker_mapping: FlowPackageSpeakerMappingConfig | None = None


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
