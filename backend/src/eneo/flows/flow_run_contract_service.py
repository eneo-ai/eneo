from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from eneo.flows.api.flow_run_contract_models import (
    FlowFinalOutputContractPublic,
    FlowOutputDelivery,
    FlowReviewStepContractPublic,
    FlowRunContractPublic,
    FlowRuntimeInputContractPublic,
    FlowTemplateReadinessPublic,
    FormFieldPublic,
    default_runtime_upload_policy_public,
)
from eneo.flows.domain.flow import Flow, FlowTemplateAsset
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.enums import FlowOutputMode, FlowOutputType, FlowTemplateAssetStatus
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_input_limits import FlowInputLimitsSource
from eneo.flows.flow_review_expiry_policy import FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS
from eneo.flows.flow_run_step_inputs import (
    RuntimeStepInputSpec,
    aggregate_runtime_file_limit,
)
from eneo.flows.published_definition import (
    PublishedFlowDefinition,
)
from eneo.flows.published_runtime import (
    FlowRuntimeFlowSource,
    FlowRuntimePublicationIntent,
    FlowRuntimeVersionSource,
    load_published_runtime_inputs,
)
from eneo.main.exceptions import NotFoundException

logger = logging.getLogger(__name__)


class _FlowTemplateAssetRepositoryProtocol(Protocol):
    async def get(self, *, asset_id: UUID, tenant_id: UUID) -> FlowTemplateAsset: ...


@dataclass(frozen=True)
class FlowRunContractService:
    flow_service: FlowRuntimeFlowSource
    settings_service: FlowInputLimitsSource
    flow_version_repo: FlowRuntimeVersionSource
    template_asset_repo: _FlowTemplateAssetRepositoryProtocol

    async def get_run_contract(self, *, flow_id: UUID) -> FlowRunContractPublic:
        runtime_inputs = await load_published_runtime_inputs(
            flow_service=self.flow_service,
            flow_version_repo=self.flow_version_repo,
            settings_source=self.settings_service,
            flow_id=flow_id,
            intent=FlowRuntimePublicationIntent.RUN_CONTRACT,
        )
        published = runtime_inputs.published

        return FlowRunContractPublic(
            flow_id=published.flow_id,
            published_flow_version=published.published_version,
            final_output=build_final_output_contract(runtime_inputs.steps),
            form_fields=_published_form_fields(runtime_inputs.definition),
            steps_requiring_input=_runtime_input_contracts(runtime_inputs.input_specs),
            runtime_upload_policy=default_runtime_upload_policy_public(),
            steps_requiring_review=_review_step_contracts(runtime_inputs.steps),
            aggregate_max_files=aggregate_runtime_file_limit(
                specs=runtime_inputs.input_specs
            ),
            template_readiness=await self._template_readiness(
                flow=published.flow,
                flow_id=published.flow_id,
                published_version=published.published_version,
                steps=runtime_inputs.steps,
            ),
        )

    async def _template_readiness(
        self,
        *,
        flow: Flow,
        flow_id: UUID,
        published_version: int,
        steps: Sequence[RuntimeStep],
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
        template_file_id: UUID | None = None
        checksum = _string_or_none(output_config.get("template_checksum"))
        published_checksum = checksum if checksum else None
        asset_id: UUID | None = None
        asset_status = FlowTemplateAssetStatus.UNAVAILABLE
        message_code: str | None = None

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

        if (
            asset_status is FlowTemplateAssetStatus.READY
            and published_checksum is not None
            and checksum != published_checksum
        ):
            asset_status = FlowTemplateAssetStatus.NEEDS_ACTION
            message_code = FlowApiErrorCode.TYPED_IO_TEMPLATE_CHECKSUM_MISMATCH.value
        if message_code is None and asset_status is not FlowTemplateAssetStatus.READY:
            message_code = FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE.value

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
            message_code=message_code,
        )


def build_final_output_contract(
    steps: Sequence[RuntimeStep],
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
            type=field.type,
            label=field.label,
            required=field.required,
            options=field.options,
            order=field.order,
        )
        for field in form_schema.fields
    ]
    return sorted(fields, key=lambda field: field.order or 0)


def _runtime_input_contracts(
    specs: Mapping[UUID, RuntimeStepInputSpec],
) -> list[FlowRuntimeInputContractPublic]:
    return [
        FlowRuntimeInputContractPublic(
            step_id=spec.step.step_id,
            step_order=spec.step.step_order,
            label=spec.runtime_input.label,
            description=spec.runtime_input.description,
            required=spec.runtime_input.required,
            input_format=spec.runtime_input.input_format,
            max_files=spec.max_files,
            max_file_size_bytes=spec.max_file_size_bytes,
            accepted_mimetypes=spec.accepted_mimetypes,
        )
        for spec in sorted(
            specs.values(),
            key=lambda item: (item.step.step_order, str(item.step.step_id)),
        )
    ]


def _review_step_contracts(
    steps: Sequence[RuntimeStep],
) -> list[FlowReviewStepContractPublic]:
    return [
        FlowReviewStepContractPublic(
            step_id=step.step_id,
            step_order=step.step_order,
            label=step.user_description,
            review_mode=step.review_policy.mode,
            output_type=FlowOutputType(step.output_type),
            expires_after_seconds=(
                step.review_policy.expires_after_seconds
                if step.review_policy.expires_after_seconds is not None
                else FLOW_REVIEW_EXPIRY_DEFAULT_SECONDS
            ),
            output_contract=step.output_contract,
        )
        for step in steps
        if step.review_policy is not None
    ]


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
