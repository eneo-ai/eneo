from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, cast
from uuid import UUID

from intric.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from intric.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from intric.flow_packages.domain.flow_package_errors import (
    FlowPackageExportError,
    FlowPackageExportErrorCode,
)
from intric.flow_packages.domain.flow_package_limits import MAX_FLOW_PACKAGE_BYTES
from intric.flow_packages.domain.flow_package_manifest import (
    FlowPackageManifestMetadata,
    flow_package_filename,
)
from intric.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageKnowledgeRequirement,
    FlowPackageModelKind,
    FlowPackageModelRequirement,
    FlowPackageRequirementEntry,
    FlowPackageRequirementSet,
)
from intric.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
    AssistantAuthoringSnapshots,
)
from intric.flows.domain.flow import Flow, FlowStep, JsonObject
from intric.flows.enums import FlowOutputMode
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.flow_metadata import (
    FlowFormSchemaParseMode,
    parse_flow_form_schema,
)
from intric.flows.flow_resource_bindings import (
    FlowResourceBindingResolutionError,
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotAllocator,
    ResourceSlotKind,
    index_local_resource_bindings,
    is_uuid_shaped_resource_ref,
    local_resource_kinds_for_slot_kind,
)
from intric.flows.flow_validators_template import has_template_fill_resource_reference
from intric.flows.flow_variable_definitions import PRIMARY_FLOW_INPUT_KEYS
from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)
from intric.main.exceptions import BadRequestException

_MAX_JSON_SCAN_DEPTH = 32
# Package bytes are materialized before response; this cap bounds the response payload.
MAX_PACKAGE_EXPORT_BYTES = MAX_FLOW_PACKAGE_BYTES

FlowPackageWriter = Callable[[FlowPackageEnvelope], bytes]
FlowPackageClock = Callable[[], datetime]


class FlowPackageExportFlowService(Protocol):
    async def get_flow_assistant_snapshots(
        self,
        flow: Flow,
    ) -> AssistantAuthoringSnapshots: ...

    async def list_resource_bindings(
        self,
        *,
        flow_id: UUID,
    ) -> tuple[LocalResourceBinding, ...]: ...


@dataclass(frozen=True, slots=True)
class FlowPackageExportResult:
    package_bytes: bytes
    envelope: FlowPackageEnvelope
    filename: str


class FlowPackageExportService:
    """Portable export invariants: no source-local provenance ids, capped bytes."""

    def __init__(
        self,
        *,
        flow_service: FlowPackageExportFlowService,
        package_writer: FlowPackageWriter,
        clock: FlowPackageClock | None = None,
    ) -> None:
        self._flow_service = flow_service
        self._package_writer = package_writer
        self._clock = clock or _utc_now

    async def export_to_bytes(
        self,
        *,
        flow_id: UUID,
        flow: Flow,
        manifest_metadata: FlowPackageManifestMetadata,
    ) -> FlowPackageExportResult:
        assistant_snapshots = await self._flow_service.get_flow_assistant_snapshots(
            flow
        )
        resource_bindings = await self._flow_service.list_resource_bindings(
            flow_id=flow_id
        )
        envelope = build_flow_package_export_envelope(
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            resource_bindings=resource_bindings,
            manifest_metadata=manifest_metadata,
            provenance=FlowPackageProvenance.for_portable_export(
                exported_at=self._clock()
            ),
        )
        package_bytes = self._package_writer(envelope)
        if len(package_bytes) > MAX_PACKAGE_EXPORT_BYTES:
            raise FlowPackageExportError(
                code=FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE,
                message="Flow package export exceeds the allowed size.",
                context={
                    "package_size_bytes": len(package_bytes),
                    "max_package_export_bytes": MAX_PACKAGE_EXPORT_BYTES,
                },
            )
        return FlowPackageExportResult(
            package_bytes=package_bytes,
            envelope=envelope,
            filename=flow_package_filename(envelope.manifest),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class _StepUsage:
    step_ref: str
    step_order: int


@dataclass(slots=True)
class _RequirementDraft:
    slot_ref_kind: ResourceSlotKind
    binding: LocalResourceBinding
    used_by_steps: dict[str, _StepUsage] = field(
        default_factory=lambda: dict[str, _StepUsage]()
    )

    def add_usage(self, usage: _StepUsage) -> None:
        self.used_by_steps.setdefault(usage.step_ref, usage)


def build_flow_package_export_envelope(
    *,
    flow: Flow,
    assistant_snapshots: AssistantAuthoringSnapshots,
    resource_bindings: tuple[LocalResourceBinding, ...],
    manifest_metadata: FlowPackageManifestMetadata,
    provenance: FlowPackageProvenance,
) -> FlowPackageEnvelope:
    try:
        index_local_resource_bindings(resource_bindings)
    except FlowResourceBindingResolutionError as exc:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.DUPLICATE_RESOURCE_BINDING,
            message="Flow package export found multiple local resources for one package slot.",
            context=exc.context(),
        ) from exc

    slot_allocator = ResourceSlotAllocator(prior_bindings=resource_bindings)
    requirement_drafts: dict[str, _RequirementDraft] = {}
    form_fields = _form_fields_from_metadata(flow.metadata_json)
    ordered_steps = sorted(flow.steps, key=lambda item: item.step_order)
    step_refs_by_order = {step.step_order: _step_ref(step) for step in ordered_steps}
    form_field_names = {field.name for field in form_fields}

    steps: list[StepSpec] = []
    for step in ordered_steps:
        usage = _StepUsage(step_ref=_step_ref(step), step_order=step.step_order)
        snapshot = assistant_snapshots.get(step.assistant_id)
        if snapshot is None:
            raise FlowPackageExportError(
                code=FlowPackageExportErrorCode.MISSING_ASSISTANT_SNAPSHOT,
                message="Flow package export requires assistant authoring snapshots.",
                context={"step_order": step.step_order},
            )
        step_spec = _step_spec(
            step=step,
            snapshot=snapshot,
            slot_allocator=slot_allocator,
            requirement_drafts=requirement_drafts,
            usage=usage,
        )
        _validate_step_template_references(
            step_spec=step_spec,
            current_step_order=step.step_order,
            step_refs_by_order=step_refs_by_order,
            form_field_names=form_field_names,
        )
        steps.append(step_spec)

    draft = FlowPackageFlowDraft(
        schema_version=1,
        spec=FlowDraftSpecCore(
            flow_name=flow.name,
            flow_description=flow.description or "",
            steps=steps,
            form_fields=form_fields or None,
        ),
    )
    return FlowPackageEnvelope.build_for_export(
        manifest_metadata=manifest_metadata,
        draft=draft,
        requirements=FlowPackageRequirementSet(
            schema_version=1,
            requirements=_requirements_from_drafts(requirement_drafts.values()),
        ),
        provenance=provenance,
    )


def _form_fields_from_metadata(metadata_json: JsonObject | None) -> list[FormFieldSpec]:
    try:
        form_schema = parse_flow_form_schema(
            metadata_json,
            mode=FlowFormSchemaParseMode.WRITE,
        )
    except BadRequestException as exc:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.FORM_SCHEMA_INVALID,
            message="Flow package export requires a valid form schema.",
        ) from exc
    if form_schema is None:
        return []
    return [
        FormFieldSpec(
            name=field.name,
            type=field.type.value,
            label=field.label or field.name,
            required=field.required,
            options=field.options,
        )
        for field in form_schema.fields
    ]


def _step_spec(
    *,
    step: FlowStep,
    snapshot: AssistantAuthoringSnapshot,
    slot_allocator: ResourceSlotAllocator,
    requirement_drafts: dict[str, _RequirementDraft],
    usage: _StepUsage,
) -> StepSpec:
    has_template_resource = has_template_fill_resource_reference(step.output_config)
    if step.output_mode == FlowOutputMode.TEMPLATE_FILL or has_template_resource:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED,
            message="Flow package export does not support template asset payloads yet.",
            context={"step_order": step.step_order},
        )

    try:
        mcp_policy = MCPPolicy(step.mcp_policy.value)
        input_source = InputSource(step.input_source.value)
        input_type = InputType(step.input_type.value)
        output_mode = OutputMode(step.output_mode.value)
        output_type = OutputType(step.output_type.value)
    except ValueError as exc:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.UNSUPPORTED_STEP_IO,
            message="Flow step uses IO that is not portable in flow packages.",
            context={"step_order": step.step_order},
        ) from exc

    assistant_spec = _assistant_spec(
        snapshot=snapshot,
        slot_allocator=slot_allocator,
        requirement_drafts=requirement_drafts,
        usage=usage,
    )
    return StepSpec(
        plan_step_ref=usage.step_ref,
        name=step.user_description or usage.step_ref,
        assistant_spec=assistant_spec,
        mcp_policy=mcp_policy,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=step.input_bindings,
        input_contract=step.input_contract,
        output_contract=step.output_contract,
        input_config=step.input_config,
        output_config=step.output_config,
        review_policy=step.review_policy,
    )


def _assistant_spec(
    *,
    snapshot: AssistantAuthoringSnapshot,
    slot_allocator: ResourceSlotAllocator,
    requirement_drafts: dict[str, _RequirementDraft],
    usage: _StepUsage,
) -> AssistantSpec:
    if snapshot.mcp_server_refs or snapshot.mcp_tool_refs:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.MCP_EXPORT_UNSUPPORTED,
            message=(
                "Flow package export does not support portable MCP resources. "
                "Remove MCP bindings from the shared package and document any required "
                "MCP setup in marketplace or forum guidance."
            ),
            context={"step_order": usage.step_order},
        )

    model_ref = None
    if snapshot.model is not None:
        model_binding = _binding_for_ref(
            snapshot.model,
            slot_kind=ResourceSlotKind.MODEL,
            slot_allocator=slot_allocator,
        )
        model_ref = model_binding.slot_ref.ref
        _record_requirement(requirement_drafts, model_binding, usage)

    knowledge_refs: list[str] = []
    for resource_ref in snapshot.knowledge_refs:
        binding = _binding_for_ref(
            resource_ref,
            slot_kind=ResourceSlotKind.KNOWLEDGE,
            slot_allocator=slot_allocator,
        )
        knowledge_refs.append(binding.slot_ref.ref)
        _record_requirement(requirement_drafts, binding, usage)

    return AssistantSpec(
        instructions=snapshot.instructions,
        model_ref=model_ref,
        knowledge_refs=knowledge_refs,
    )


def _binding_for_ref(
    resource_ref: AssistantAuthoringResourceRef,
    *,
    slot_kind: ResourceSlotKind,
    slot_allocator: ResourceSlotAllocator,
) -> LocalResourceBinding:
    _validate_resource_uuid(resource_ref.local_ref)
    local_kind = _resource_local_kind(resource_ref, slot_kind=slot_kind)
    _, binding = slot_allocator.allocate(
        slot_kind=slot_kind,
        local_kind=local_kind,
        local_ref=resource_ref.local_ref,
        display_name=resource_ref.label or "",
    )
    if binding is None:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF,
            message="Flow package export requires UUID-backed local resource refs.",
            context={
                "resource_ref": resource_ref.local_ref,
                "slot_kind": slot_kind.value,
            },
        )
    return binding


def _resource_local_kind(
    resource_ref: AssistantAuthoringResourceRef,
    *,
    slot_kind: ResourceSlotKind,
) -> LocalResourceKind:
    if resource_ref.local_kind is None:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF,
            message=(
                "Flow package export requires typed local resource refs before "
                "they can be converted to portable package slots."
            ),
            context={
                "resource_ref": resource_ref.local_ref,
                "slot_kind": slot_kind.value,
            },
        )

    allowed_local_kinds = local_resource_kinds_for_slot_kind(slot_kind)
    if resource_ref.local_kind not in allowed_local_kinds:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF,
            message=(
                "Flow package export found a local resource kind that cannot "
                "satisfy the requested package slot kind."
            ),
            context={
                "resource_ref": resource_ref.local_ref,
                "slot_kind": slot_kind.value,
                "local_kind": resource_ref.local_kind.value,
            },
        )
    return resource_ref.local_kind


def _validate_resource_uuid(resource_ref: str) -> None:
    if not is_uuid_shaped_resource_ref(resource_ref):
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF,
            message="Flow package export requires UUID-backed local resource refs.",
            context={"resource_ref": resource_ref},
        )


def _record_requirement(
    requirement_drafts: dict[str, _RequirementDraft],
    binding: LocalResourceBinding,
    usage: _StepUsage,
) -> None:
    draft = requirement_drafts.setdefault(
        binding.slot_ref.ref,
        _RequirementDraft(slot_ref_kind=binding.slot_ref.kind, binding=binding),
    )
    draft.add_usage(usage)


def _requirements_from_drafts(
    drafts: Iterable[_RequirementDraft],
) -> list[FlowPackageRequirementEntry]:
    return [
        _requirement_from_draft(draft)
        for draft in sorted(drafts, key=lambda item: item.binding.slot_ref.ref)
    ]


def _requirement_from_draft(draft: _RequirementDraft) -> FlowPackageRequirementEntry:
    used_by_steps = [
        usage.step_ref
        for usage in sorted(
            draft.used_by_steps.values(),
            key=lambda item: (item.step_order, item.step_ref),
        )
    ]
    match draft.slot_ref_kind:
        case ResourceSlotKind.MODEL:
            return FlowPackageModelRequirement(
                slot_ref=draft.binding.slot_ref,
                used_by_steps=used_by_steps,
                model_kind=_model_kind_for_binding(draft.binding),
            )
        case ResourceSlotKind.KNOWLEDGE:
            return FlowPackageKnowledgeRequirement(
                slot_ref=draft.binding.slot_ref,
                used_by_steps=used_by_steps,
            )
        case ResourceSlotKind.MCP_TOOL:
            raise FlowPackageExportError(
                code=FlowPackageExportErrorCode.MCP_EXPORT_UNSUPPORTED,
                message="Flow package export does not support portable MCP resources.",
                context={"resource_ref": draft.binding.slot_ref.ref},
            )
        case ResourceSlotKind.TEMPLATE_ASSET:
            raise FlowPackageExportError(
                code=FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED,
                message="Flow package export does not support template asset payloads yet.",
                context={"resource_ref": draft.binding.slot_ref.ref},
            )
        case ResourceSlotKind.MCP_SERVER:
            raise FlowPackageExportError(
                code=FlowPackageExportErrorCode.MCP_EXPORT_UNSUPPORTED,
                message="Flow package export does not support portable MCP resources.",
                context={"resource_ref": draft.binding.slot_ref.ref},
            )


def _model_kind_for_binding(binding: LocalResourceBinding) -> FlowPackageModelKind:
    match binding.local_kind:
        case LocalResourceKind.COMPLETION_MODEL:
            return FlowPackageModelKind.COMPLETION_MODEL
        case LocalResourceKind.TRANSCRIPTION_MODEL:
            return FlowPackageModelKind.TRANSCRIPTION_MODEL
        case _:
            raise FlowPackageExportError(
                code=FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF,
                message="Flow package export found a non-model binding for a model slot.",
                context={"resource_ref": binding.slot_ref.ref},
            )


def _validate_step_template_references(
    *,
    step_spec: StepSpec,
    current_step_order: int,
    step_refs_by_order: Mapping[int, str],
    form_field_names: set[str],
) -> None:
    prior_step_refs = {
        step_ref: step_order
        for step_order, step_ref in step_refs_by_order.items()
        if step_order < current_step_order
    }
    allowed_step_refs = set(prior_step_refs)
    for template in _step_spec_template_strings(step_spec):
        references = analyze_template(
            template,
            step_refs=prior_step_refs,
            form_field_names=form_field_names,
        )
        for reference in references:
            if reference.path_error_code is not None:
                _raise_invalid_variable_reference(
                    reference.expression, current_step_order
                )
            if reference.kind is TemplateReferenceKind.UNKNOWN:
                _raise_invalid_variable_reference(
                    reference.expression, current_step_order
                )
            if (
                reference.kind is TemplateReferenceKind.FORM_FIELD
                and reference.head not in form_field_names
            ):
                _raise_invalid_variable_reference(
                    reference.expression, current_step_order
                )
            if reference.kind is TemplateReferenceKind.STEP:
                step_ref = reference.step_ref or reference.head
                if step_ref not in allowed_step_refs:
                    _raise_invalid_variable_reference(
                        reference.expression,
                        current_step_order,
                    )
            if (
                reference.kind is TemplateReferenceKind.RUNTIME
                and reference.head == "flow_input"
                and reference.tail
            ):
                flow_input_key = reference.tail.split(".", maxsplit=1)[0]
                if (
                    flow_input_key not in form_field_names
                    and flow_input_key not in PRIMARY_FLOW_INPUT_KEYS
                ):
                    _raise_invalid_variable_reference(
                        reference.expression,
                        current_step_order,
                    )


def _raise_invalid_variable_reference(expression: str, step_order: int) -> None:
    raise FlowPackageExportError(
        code=FlowPackageExportErrorCode.VARIABLE_REFERENCE_INVALID,
        message="Flow package export found an invalid variable reference.",
        context={"step_order": step_order, "expression": expression},
    )


def _step_spec_template_strings(step_spec: StepSpec) -> Iterator[str]:
    yield step_spec.assistant_spec.instructions
    yield from _string_leaves(step_spec.input_bindings)
    yield from _string_leaves(step_spec.input_contract)
    yield from _string_leaves(step_spec.output_contract)
    yield from _string_leaves(step_spec.input_config)
    yield from _string_leaves(step_spec.output_config)


def _string_leaves(value: object, *, depth: int = 0) -> Iterator[str]:
    if depth > _MAX_JSON_SCAN_DEPTH:
        raise FlowPackageExportError(
            code=FlowPackageExportErrorCode.JSON_PAYLOAD_TOO_DEEP,
            message="Flow package export cannot scan deeply nested JSON payloads.",
        )
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        for nested_value in mapping.values():
            yield from _string_leaves(nested_value, depth=depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        for nested_value in sequence:
            yield from _string_leaves(nested_value, depth=depth + 1)


def _step_ref(step: FlowStep) -> str:
    return f"step_{step.step_order}"
