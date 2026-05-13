from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from intric.flows.domain.flow import Flow, FlowTemplateAsset, FlowVersion
from intric.flows.enums import FlowOutputMode, FlowOutputType, FlowTemplateAssetStatus
from intric.flows.flow_input_limits import (
    FlowInputLimits,
    effective_flow_input_limit,
    effective_runtime_max_files,
)
from intric.flows.flow_run_contract_models import (
    FlowFinalOutputContractPublic,
    FlowOutputDelivery,
    FlowReviewStepContractPublic,
    FlowRunContractPublic,
    FlowRuntimeInputContractPublic,
    FlowTemplateReadinessPublic,
    FormFieldPublic,
    default_runtime_upload_policy_public,
)
from intric.flows.published_definition import (
    PublishedFlowDefinition,
    parse_published_definition,
)
from intric.flows.runtime.models import RuntimeStep
from intric.flows.runtime_input import (
    build_runtime_input_config,
    runtime_input_accept_mimetypes,
)
from intric.main.exceptions import BadRequestException, NotFoundException

logger = logging.getLogger(__name__)


class _FlowServiceProtocol(Protocol):
    async def get_flow(self, flow_id: UUID) -> Flow: ...


class _SettingsServiceProtocol(Protocol):
    async def get_flow_input_limits_resolved(self) -> FlowInputLimits: ...


class _FlowVersionRepositoryProtocol(Protocol):
    async def get(
        self, flow_id: UUID, version: int, tenant_id: UUID
    ) -> FlowVersion: ...


class _FlowTemplateAssetRepositoryProtocol(Protocol):
    async def get(self, *, asset_id: UUID, tenant_id: UUID) -> FlowTemplateAsset: ...

    async def get_by_flow_file(
        self,
        *,
        flow_id: UUID,
        file_id: UUID,
        tenant_id: UUID,
    ) -> FlowTemplateAsset: ...


@dataclass(frozen=True)
class FlowRunContractService:
    flow_service: _FlowServiceProtocol
    settings_service: _SettingsServiceProtocol
    flow_version_repo: _FlowVersionRepositoryProtocol
    template_asset_repo: _FlowTemplateAssetRepositoryProtocol

    async def get_run_contract(self, *, flow_id: UUID) -> FlowRunContractPublic:
        flow = await self.flow_service.get_flow(flow_id)
        persisted_flow_id = _require_flow_id(flow)
        if flow.published_version is None:
            raise BadRequestException(
                "Flow must be published before a run contract can be created.",
                code="flow_not_published",
            )

        version = await self.flow_version_repo.get(
            flow_id=persisted_flow_id,
            version=flow.published_version,
            tenant_id=flow.tenant_id,
        )
        published_definition = parse_published_definition(version.definition_json)
        steps = published_definition.runtime_steps()
        limits = await self.settings_service.get_flow_input_limits_resolved()

        return FlowRunContractPublic(
            flow_id=persisted_flow_id,
            published_flow_version=flow.published_version,
            final_output=_build_final_output(steps),
            form_fields=_published_form_fields(published_definition),
            steps_requiring_input=_runtime_input_contracts(steps, limits),
            runtime_upload_policy=default_runtime_upload_policy_public(),
            steps_requiring_review=_review_step_contracts(steps),
            aggregate_max_files=_aggregate_max_files(steps, limits),
            template_readiness=await self._template_readiness(
                flow=flow,
                flow_id=persisted_flow_id,
                published_version=flow.published_version,
                steps=steps,
            ),
        )

    async def _template_readiness(
        self,
        *,
        flow: Flow,
        flow_id: UUID,
        published_version: int,
        steps: list[RuntimeStep],
    ) -> list[FlowTemplateReadinessPublic]:
        items: list[FlowTemplateReadinessPublic] = []
        for step in steps:
            if step.output_mode != FlowOutputMode.TEMPLATE_FILL.value or not isinstance(
                step.output_config, dict
            ):
                continue
            items.append(
                await self._template_readiness_for_step(
                    flow=flow,
                    flow_id=flow_id,
                    published_version=published_version,
                    step=step,
                )
            )
        return items

    async def _template_readiness_for_step(
        self,
        *,
        flow: Flow,
        flow_id: UUID,
        published_version: int,
        step: RuntimeStep,
    ) -> FlowTemplateReadinessPublic:
        output_config = step.output_config or {}
        asset_id_raw = output_config.get("template_asset_id")
        template_name = _string_or_none(output_config.get("template_name"))
        template_file_id = _uuid_or_none(output_config.get("template_file_id"))
        checksum = _string_or_none(output_config.get("template_checksum"))
        asset_id: UUID | None = None
        asset_status = FlowTemplateAssetStatus.UNAVAILABLE

        if asset_id_raw is not None:
            asset_id = _uuid_or_none(asset_id_raw)
            if asset_id is not None:
                try:
                    asset = await self.template_asset_repo.get(
                        asset_id=asset_id,
                        tenant_id=flow.tenant_id,
                    )
                    asset_status = FlowTemplateAssetStatus.READY
                    template_name = asset.name
                    template_file_id = asset.file_id
                    checksum = asset.checksum
                except NotFoundException:
                    logger.info(
                        "Published flow template asset is not accessible.",
                        extra={
                            "flow_id": str(flow_id),
                            "step_id": str(step.step_id),
                            "template_asset_id": str(asset_id_raw),
                        },
                    )
        elif template_file_id is not None:
            try:
                asset = await self.template_asset_repo.get_by_flow_file(
                    flow_id=flow_id,
                    file_id=template_file_id,
                    tenant_id=flow.tenant_id,
                )
                asset_id = asset.id
                asset_status = FlowTemplateAssetStatus.READY
                template_name = asset.name
                template_file_id = asset.file_id
                checksum = asset.checksum
            except NotFoundException:
                logger.info(
                    "Published flow template file is not accessible.",
                    extra={
                        "flow_id": str(flow_id),
                        "step_id": str(step.step_id),
                        "template_file_id": str(template_file_id),
                    },
                )

        return FlowTemplateReadinessPublic(
            step_id=step.step_id,
            template_asset_id=asset_id,
            template_file_id=template_file_id,
            template_name=template_name,
            checksum=checksum,
            published_flow_version=published_version,
            status=asset_status,
            can_edit=False,
            can_download=asset_id is not None,
            message_code=(
                None
                if asset_status is FlowTemplateAssetStatus.READY
                else "flow_template_not_accessible"
            ),
        )


def _require_flow_id(flow: Flow) -> UUID:
    if flow.id is None:
        raise BadRequestException(
            "Flow id is missing.",
            code="flow_id_missing",
        )
    return flow.id


def _build_final_output(
    steps: list[RuntimeStep],
) -> FlowFinalOutputContractPublic | None:
    final_step = steps[-1] if steps else None
    if final_step is None:
        return None
    output_type = FlowOutputType(final_step.output_type)
    output_mode = FlowOutputMode(final_step.output_mode)
    return FlowFinalOutputContractPublic(
        step_id=final_step.step_id,
        step_order=final_step.step_order,
        label=final_step.user_description,
        output_type=output_type,
        output_mode=output_mode,
        delivery=_output_delivery(output_type=output_type, output_mode=output_mode),
        output_contract=final_step.output_contract,
    )


def _output_delivery(
    *,
    output_type: FlowOutputType,
    output_mode: FlowOutputMode,
) -> FlowOutputDelivery:
    if output_mode is FlowOutputMode.HTTP_POST:
        return FlowOutputDelivery.OUTBOUND_HTTP
    if output_type in {FlowOutputType.PDF, FlowOutputType.DOCX}:
        return FlowOutputDelivery.ARTIFACT
    return FlowOutputDelivery.PAYLOAD


def _published_form_fields(
    published_definition: PublishedFlowDefinition,
) -> list[FormFieldPublic]:
    form_schema = published_definition.metadata().form_schema
    if form_schema is None:
        return []
    fields = [
        FormFieldPublic(
            name=field.name,
            type=field.type.value,
            label=field.label,
            required=field.required,
            options=field.options,
            order=field.order,
        )
        for field in form_schema.fields
    ]
    return sorted(fields, key=lambda field: field.order or 0)


def _runtime_input_contracts(
    steps: list[RuntimeStep],
    limits: FlowInputLimits,
) -> list[FlowRuntimeInputContractPublic]:
    contracts: list[FlowRuntimeInputContractPublic] = []
    for step in steps:
        runtime_input = build_runtime_input_config(step.input_config)
        if not runtime_input.enabled:
            continue
        max_files = effective_runtime_max_files(
            input_type=runtime_input.input_format,
            step_max_files=runtime_input.max_files,
            limits=limits,
        )
        contracts.append(
            FlowRuntimeInputContractPublic(
                step_id=step.step_id,
                step_order=step.step_order,
                label=runtime_input.label,
                description=runtime_input.description,
                required=runtime_input.required,
                input_format=runtime_input.input_format,
                max_files=max_files,
                max_file_size_bytes=effective_flow_input_limit(
                    input_type=runtime_input.input_format,
                    limits=limits,
                ),
                accepted_mimetypes=runtime_input_accept_mimetypes(runtime_input),
            )
        )
    return contracts


def _review_step_contracts(
    steps: list[RuntimeStep],
) -> list[FlowReviewStepContractPublic]:
    return [
        FlowReviewStepContractPublic(
            step_id=step.step_id,
            step_order=step.step_order,
            label=step.user_description,
            review_mode=step.review_policy.mode,
            output_type=FlowOutputType(step.output_type),
            output_contract=step.output_contract,
        )
        for step in steps
        if step.review_policy is not None
    ]


def _aggregate_max_files(
    steps: list[RuntimeStep],
    limits: FlowInputLimits,
) -> int | None:
    aggregate: int | None = 0
    for step in steps:
        runtime_input = build_runtime_input_config(step.input_config)
        if not runtime_input.enabled:
            continue
        max_files = effective_runtime_max_files(
            input_type=runtime_input.input_format,
            step_max_files=runtime_input.max_files,
            limits=limits,
        )
        if max_files is None:
            return None
        aggregate = (aggregate or 0) + max_files
    return aggregate


def _uuid_or_none(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
