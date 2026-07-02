from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, assert_never
from uuid import UUID

from eneo.flows.domain.flow import Flow, FlowVersion
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_input_limits import (
    FlowInputLimits,
    FlowInputLimitsSource,
    resolve_flow_input_limits_from_source,
)
from eneo.flows.flow_run_step_inputs import (
    RuntimeStepInputSpec,
    build_runtime_step_input_specs,
)
from eneo.flows.published_definition import (
    PublishedFlowDefinition,
    parse_published_definition,
)
from eneo.flows.runtime.models import RuntimeStep


class FlowRuntimeFlowSource(Protocol):
    async def get_flow(self, flow_id: UUID) -> Flow: ...


class FlowRuntimeVersionSource(Protocol):
    async def get(
        self, flow_id: UUID, version: int, tenant_id: UUID
    ) -> FlowVersion: ...


class FlowRuntimePublicationIntent(Enum):
    RUN_CONTRACT = "run_contract"
    RUNTIME_UPLOAD = "runtime_upload"
    RUNTIME_DELETE = "runtime_delete"

    @property
    def unpublished_message(self) -> str:
        match self:
            case FlowRuntimePublicationIntent.RUN_CONTRACT:
                return "Flow must be published before a run contract can be created."
            case FlowRuntimePublicationIntent.RUNTIME_UPLOAD:
                return "Flow must be published before runtime files can be uploaded."
            case FlowRuntimePublicationIntent.RUNTIME_DELETE:
                return "Flow must be published before runtime files can be deleted."
        assert_never(self)


@dataclass(frozen=True)
class PublishedFlowRuntime:
    flow: Flow
    flow_id: UUID
    published_version: int


@dataclass(frozen=True)
class PublishedRuntimeInputs:
    published: PublishedFlowRuntime
    definition: PublishedFlowDefinition
    steps: tuple[RuntimeStep, ...]
    limits: FlowInputLimits
    input_specs: dict[UUID, RuntimeStepInputSpec]


async def load_published_flow_runtime(
    *,
    flow_service: FlowRuntimeFlowSource,
    flow_id: UUID,
    intent: FlowRuntimePublicationIntent,
) -> PublishedFlowRuntime:
    flow = await flow_service.get_flow(flow_id)
    persisted_flow_id = flow.require_persisted_id()
    published_version = flow.published_version
    if published_version is None:
        raise FlowBadRequestException(
            intent.unpublished_message,
            code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
        )
    return PublishedFlowRuntime(
        flow=flow,
        flow_id=persisted_flow_id,
        published_version=published_version,
    )


async def load_published_runtime_inputs(
    *,
    flow_service: FlowRuntimeFlowSource,
    flow_version_repo: FlowRuntimeVersionSource,
    settings_source: FlowInputLimitsSource,
    flow_id: UUID,
    intent: FlowRuntimePublicationIntent,
) -> PublishedRuntimeInputs:
    published = await load_published_flow_runtime(
        flow_service=flow_service,
        flow_id=flow_id,
        intent=intent,
    )
    version = await flow_version_repo.get(
        flow_id=published.flow_id,
        version=published.published_version,
        tenant_id=published.flow.tenant_id,
    )
    definition = parse_published_definition(
        version.definition_json,
        flow_version=version.version,
    )
    steps = tuple(definition.runtime_steps())
    limits = await resolve_flow_input_limits_from_source(settings_source)
    input_specs = build_runtime_step_input_specs(steps=steps, limits=limits)
    return PublishedRuntimeInputs(
        published=published,
        definition=definition,
        steps=steps,
        limits=limits,
        input_specs=input_specs,
    )
