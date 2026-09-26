from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from eneo.flows.api.flow_live_transcription_models import (
    FlowLiveTranscriptionAvailabilityPublic,
)
from eneo.flows.api.flow_run_contract_models import (
    FlowFinalOutputContractPublic,
    FlowMaxSpeakersOptionPublic,
    FlowReviewStepContractPublic,
    FlowRunContractPublic,
    FlowRuntimeInputContractPublic,
    FlowSecurityClassificationPublic,
    FlowSpeakerLabelsOptionPublic,
    FlowTemplateReadinessPublic,
    FlowTextProcessingStepPublic,
    FlowTranscriptionContractPublic,
    FormFieldPublic,
    default_runtime_upload_policy_public,
)
from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowTemplateAsset
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.speaker_mapping_config import (
    speaker_mapping_participants_field,
    speaker_mapping_speaker_count_field,
)
from eneo.flows.domain.step_mapped_execution import single_mapped_array_key
from eneo.flows.domain.text_processing import text_processing_config
from eneo.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRuntimeInputFormat,
    FlowTemplateAssetStatus,
    final_output_delivery,
    final_step_output_type,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowValidationException
from eneo.flows.flow_input_limits import flow_audio_decode_limits
from eneo.flows.flow_metadata import form_field_display_position
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
    FlowRuntimeSettingsSource,
    FlowRuntimeVersionSource,
    PublishedRuntimeInputs,
    load_published_runtime_inputs,
)
from eneo.flows.runtime.live_transcription.admission import resolve_live_transcription
from eneo.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import NOT_PROVIDED, NotProvided

if TYPE_CHECKING:
    from eneo.main.config import Settings
    from eneo.spaces.space import Space

logger = logging.getLogger(__name__)


class _FlowTemplateAssetRepositoryProtocol(Protocol):
    async def get(self, *, asset_id: UUID, tenant_id: UUID) -> FlowTemplateAsset: ...


@dataclass(frozen=True)
class FlowRunContractService:
    flow_service: FlowRuntimeFlowSource
    settings_service: FlowRuntimeSettingsSource
    flow_version_repo: FlowRuntimeVersionSource
    template_asset_repo: _FlowTemplateAssetRepositoryProtocol
    settings: Settings

    async def get_run_contract(
        self, *, flow_id: UUID, space: Space
    ) -> FlowRunContractPublic:
        """``space`` is the flow's space the caller was authorized in."""
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
            text_processing_steps=_text_processing_contracts(runtime_inputs.steps),
            final_output=build_final_output_contract(runtime_inputs.steps),
            form_fields=_published_form_fields(runtime_inputs.definition),
            steps_requiring_input=_runtime_input_contracts(
                runtime_inputs.input_specs,
                audio_max_duration_seconds=flow_audio_decode_limits(
                    runtime_inputs.limits, self.settings
                ).longest_audio_seconds,
            ),
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
            transcription=self._transcription(runtime_inputs, space),
            security_classification=_security_classification(space),
        )

    def _transcription(
        self, runtime_inputs: PublishedRuntimeInputs, space: Space
    ) -> FlowTranscriptionContractPublic | None:
        wizard_metadata = runtime_inputs.definition.metadata().wizard
        speaker_labels = speaker_labels_option(
            runtime_inputs.steps,
            wizard_metadata=wizard_metadata,
            service_configured=self.settings.flow_transcription_service_configured,
        )
        audio_step = _audio_input_step(runtime_inputs.steps)
        if speaker_labels is None or audio_step is None:
            return None
        live = resolve_live_transcription(
            wizard_metadata=wizard_metadata,
            space=space,
            step=audio_step,
            settings=self.settings,
        )
        return FlowTranscriptionContractPublic(
            live=FlowLiveTranscriptionAvailabilityPublic(
                available=live.available, reason=live.reason
            ),
            speaker_labels=speaker_labels,
            max_speakers=max_speakers_option(
                runtime_inputs.steps,
                speaker_labels=speaker_labels,
                service_configured=self.settings.flow_transcription_service_configured,
            ),
            # Eneo takes the parts of one recording together whatever labels them.
            single_recording=True,
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
    output_type = final_step_output_type([step.output_type for step in steps])
    if output_type is None:
        return None
    final_step = steps[-1]
    output_mode = FlowOutputMode(final_step.output_mode)
    return FlowFinalOutputContractPublic(
        step_id=final_step.step_id,
        step_order=final_step.step_order,
        label=final_step.user_description,
        output_type=output_type,
        output_mode=output_mode,
        delivery=final_output_delivery(
            output_type=output_type, output_mode=output_mode
        ),
        output_contract=final_step.output_contract,
    )


def speaker_labels_option(
    steps: Sequence[RuntimeStep],
    *,
    wizard_metadata: FlowPersistedJsonObject | None,
    service_configured: bool,
) -> FlowSpeakerLabelsOptionPublic | None:
    """The speaker-label choice a run gets; None when the flow transcribes no audio.

    Only an external transcription service labels speakers, so without one there
    is nothing to choose, and a step that maps speakers to names needs the labels.
    """
    if _audio_input_step(steps) is None:
        return None
    try:
        config = parse_transcription_config({"wizard": wizard_metadata})
    except FlowTranscriptionConfigError:
        return None
    if not config.enabled:
        return None
    required = any(
        step.output_mode == FlowOutputMode.SPEAKER_MAPPING.value for step in steps
    )
    return FlowSpeakerLabelsOptionPublic(
        selectable=service_configured and not required,
        required=required,
        default=config.diarization,
    )


def max_speakers_option(
    steps: Sequence[RuntimeStep],
    *,
    speaker_labels: FlowSpeakerLabelsOptionPublic | None,
    service_configured: bool,
) -> FlowMaxSpeakersOptionPublic | None:
    """Whether a run may bound the speaker count: whenever a transcription
    service labels speakers for the flow, whether the run chooses the labels or
    a speaker-mapping step requires them."""
    if speaker_labels is None or not service_configured:
        return None
    mapping_config = _speaker_mapping_config(steps)
    return FlowMaxSpeakersOptionPublic(
        form_field=speaker_mapping_speaker_count_field(mapping_config),
        participants_field=speaker_mapping_participants_field(mapping_config),
    )


def settle_max_speakers(
    choice: int | None | NotProvided,
    *,
    steps: Sequence[RuntimeStep],
    wizard_metadata: FlowPersistedJsonObject | None,
    speaker_labels: bool | None,
    service_configured: bool,
    form_input: FlowPersistedJsonObject | None,
) -> int | None | NotProvided:
    """The run's upper bound on speakers, settled once at admission.

    The run's own choice wins, null meaning automatic; else the value of the
    form's speaker-count field; else automatic (None). NOT_PROVIDED when the
    run labels no speakers. Never derived from the participant names: a bound
    below the real count would merge unlisted voices into one person.
    """
    option = speaker_labels_option(
        steps, wizard_metadata=wizard_metadata, service_configured=service_configured
    )
    labels = (
        option is not None
        and service_configured
        and (
            option.required
            or (option.default if speaker_labels is None else speaker_labels)
        )
    )
    if not labels:
        if isinstance(choice, int):
            raise FlowValidationException(
                "This run labels no speakers, so it cannot bound their count. "
                "Read transcription.max_speakers in the run contract.",
                code=FlowApiErrorCode.RUN_MAX_SPEAKERS_NOT_AVAILABLE,
            )
        return NOT_PROVIDED
    if not isinstance(choice, NotProvided):
        return choice
    field = speaker_mapping_speaker_count_field(_speaker_mapping_config(steps))
    value = (form_input or {}).get(field) if field is not None else None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BadRequestException(
            f"Field '{field}' must be a whole number of at least 1.",
            code=FlowApiErrorCode.INPUT_INVALID_NUMBER.value,
            context={"field_name": field, "field_type": "number"},
        )
    return value


def _speaker_mapping_config(steps: Sequence[RuntimeStep]) -> object:
    """The first speaker-mapping step's output config, if any."""
    for step in sorted(steps, key=lambda item: item.step_order):
        if step.output_mode == FlowOutputMode.SPEAKER_MAPPING.value:
            return step.output_config
    return None


def _audio_input_step(steps: Sequence[RuntimeStep]) -> RuntimeStep | None:
    for step in sorted(steps, key=lambda item: item.step_order):
        runtime_input = build_runtime_input_config(step.input_config)
        if (
            runtime_input.enabled
            and runtime_input.input_format is FlowRuntimeInputFormat.AUDIO
        ):
            return step
    return None


def _security_classification(space: Space) -> FlowSecurityClassificationPublic | None:
    # The space settings' rule: a classification shows only while the
    # organization has security classifications turned on.
    classification = space.security_classification
    if classification is None or not classification.security_enabled:
        return None
    return FlowSecurityClassificationPublic(
        name=classification.name,
        description=classification.description,
        security_level=classification.security_level,
    )


def _published_form_fields(
    published_definition: PublishedFlowDefinition,
) -> list[FormFieldPublic]:
    form_schema = published_definition.metadata().form_schema
    if form_schema is None:
        return []
    shown = sorted(
        enumerate(form_schema.fields),
        key=lambda item: form_field_display_position(item[1].order, item[0]),
    )
    # `order` is published as the display position, so a client that sorts by it
    # again shows the same sequence.
    return [
        FormFieldPublic(
            name=field.name,
            type=field.type,
            label=field.label,
            required=field.required,
            options=field.options,
            order=position,
        )
        for position, (_, field) in enumerate(shown, start=1)
    ]


def _runtime_input_contracts(
    specs: Mapping[UUID, RuntimeStepInputSpec],
    *,
    audio_max_duration_seconds: int,
) -> list[FlowRuntimeInputContractPublic]:
    return [
        _runtime_input_contract(spec, audio_max_duration_seconds)
        for spec in sorted(
            specs.values(),
            key=lambda item: (item.step.step_order, str(item.step.step_id)),
        )
    ]


def _runtime_input_contract(
    spec: RuntimeStepInputSpec, audio_max_duration_seconds: int
) -> FlowRuntimeInputContractPublic:
    audio = spec.runtime_input.input_format is FlowRuntimeInputFormat.AUDIO
    # One limit per file and for a recording's parts together: the decoder
    # refuses longer audio either way.
    longest = audio_max_duration_seconds if audio else None
    return FlowRuntimeInputContractPublic(
        step_id=spec.step.step_id,
        step_order=spec.step.step_order,
        label=spec.runtime_input.label,
        description=spec.runtime_input.description,
        required=spec.runtime_input.required,
        input_format=spec.runtime_input.input_format,
        max_files=spec.max_files,
        max_file_size_bytes=spec.max_file_size_bytes,
        max_duration_seconds=longest,
        max_recording_seconds=longest,
        # Parts that spread the recording over every file slot.
        recording_part_seconds=(
            -(-longest // spec.max_files) if longest and spec.max_files else longest
        ),
        accepted_mimetypes=spec.accepted_mimetypes,
    )


def _text_processing_contracts(
    steps: Sequence[RuntimeStep],
) -> list[FlowTextProcessingStepPublic]:
    result: list[FlowTextProcessingStepPublic] = []
    for step in sorted(steps, key=lambda item: item.step_order):
        processing = text_processing_config(step.input_config)
        if processing is None:
            continue
        array_key = single_mapped_array_key(step.output_contract)
        if array_key is None or step.output_contract is None:
            raise ValueError(
                "Published section processing step lacks an array contract."
            )
        result.append(
            FlowTextProcessingStepPublic(
                step_id=step.step_id,
                step_order=step.step_order,
                mode=processing.mode,
                output_array_key=array_key,
                item_schema=step.output_contract["properties"][array_key]["items"],
            )
        )
    return result


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
