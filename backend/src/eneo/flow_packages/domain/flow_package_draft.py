from __future__ import annotations

import json
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

from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowRuntimeInputConfig
from eneo.flows.domain.text_processing import TextProcessingMode
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, StepSpec


class FlowPackageRuntimeInputConfig(FlowRuntimeInputConfig):
    model_config = ConfigDict(extra="forbid", strict=True)


class FlowPackageItemMapConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: StrictBool = True
    # An enabled item map must carry its fan-out ceiling: flow validation
    # rejects one without it, on export and again on import.
    max_items: Annotated[StrictInt, Field(gt=0)] | None = None


class FlowPackageTextProcessingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: TextProcessingMode


class FlowPackageStepInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    runtime_input: FlowPackageRuntimeInputConfig | None = None
    item_map: FlowPackageItemMapConfig | None = None
    text_processing: FlowPackageTextProcessingConfig | None = None

    @field_validator("runtime_input", "item_map", "text_processing", mode="before")
    @classmethod
    def normalize_disabled_literal(cls, value: object) -> object:
        return None if value is False else value


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


def normalize_flow_package_spec(spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
    steps: list[StepSpec] = []
    for step in spec.steps:
        configs: dict[str, FlowPersistedJsonObject | None] = {}
        for field, raw_config, model in (
            ("input_config", step.input_config, FlowPackageStepInputConfig),
            ("output_config", step.output_config, FlowPackageStepOutputConfig),
        ):
            if raw_config is None:
                configs[field] = None
                continue
            try:
                parsed = model.model_validate_json(json.dumps(raw_config))
            except (TypeError, ValueError) as exc:
                raise FlowPackageValidationError(
                    code=FlowPackageErrorCode.FLOW_DRAFT_INVALID,
                    message="Flow package step configuration is not portable.",
                    context={
                        "plan_step_ref": step.plan_step_ref,
                        "config_field": field,
                    },
                ) from exc
            configs[field] = (
                parsed.model_dump(
                    mode="json",
                    exclude_unset=True,
                    exclude_none=True,
                )
                or None
            )
        steps.append(step.model_copy(update=configs))
    return spec.model_copy(update={"steps": steps})
