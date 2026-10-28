from __future__ import annotations

from enum import Enum
from typing import Literal, Mapping, TypeGuard, cast

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.domain.flow import FlowPersistedJsonObject, clone_json_object
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_variable_definitions import (
    is_form_field_namespace_head,
    is_reserved_form_field_input_key,
    is_step_alias_variable,
)
from eneo.main.exceptions import BadRequestException


class FlowFormSchemaParseMode(str, Enum):
    WRITE = "write"
    PERSISTED_READ = "persisted_read"


class FlowMetadataParseMode(str, Enum):
    WRITE = "write"
    PERSISTED_READ = "persisted_read"


class FlowFormFieldType(str, Enum):
    TEXT = "text"
    MULTISELECT = "multiselect"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    LIST = "list"


# What a field's value is to the run besides an input: its name (a text field) or its day (a date field).
FlowFormFieldRole = Literal["run_label", "run_date"]
_ROLE_FIELD_TYPES: dict[str, FlowFormFieldType] = {
    "run_label": FlowFormFieldType.TEXT,
    "run_date": FlowFormFieldType.DATE,
}

CareDataApprovalMode = Literal["single_reviewer_outside_flow"]
CareDataPreApprovalVisibility = Literal["uploader_and_reviewers"]
SUPPORTED_CARE_DATA_APPROVAL_MODES = frozenset({"single_reviewer_outside_flow"})
SUPPORTED_CARE_DATA_PRE_APPROVAL_VISIBILITY = frozenset({"uploader_and_reviewers"})

_LEGACY_FORM_FIELD_TYPE_NORMALIZATION = {
    "string": FlowFormFieldType.TEXT,
    "email": FlowFormFieldType.TEXT,
    "textarea": FlowFormFieldType.TEXT,
}
_FORM_FIELD_TYPES_BY_VALUE = {
    field_type.value: field_type for field_type in FlowFormFieldType
}
# A persisted read drops any other key: flows the retired AI Builder made may
# still carry `ai_builder`. A write refuses one.
_FLOW_METADATA_TOP_LEVEL_KEYS = frozenset(
    {"form_schema", "care_data_policy", "evidence_policy", "wizard"}
)


class FlowFormField(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    type: FlowFormFieldType
    label: str | None = None
    required: bool = False
    options: list[str] | None = None
    order: int | None = None
    role: FlowFormFieldRole | None = None


class FlowFormSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    fields: list[FlowFormField]


class FlowCareDataPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sensitive: bool = False
    approval_mode: CareDataApprovalMode | None = None
    pre_approval_visibility: CareDataPreApprovalVisibility | None = None


class FlowEvidencePolicyMetadata(BaseModel):
    """The flow's own evidence choices. Export of a run's evidence is off until
    the flow allows it; the run access policy enforces it for every caller its
    other rules let through."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_export: bool = False


class FlowMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_schema: FlowFormSchema | None = None
    care_data_policy: FlowCareDataPolicy = Field(default_factory=FlowCareDataPolicy)
    evidence_policy: FlowEvidencePolicyMetadata = Field(
        default_factory=FlowEvidencePolicyMetadata
    )
    wizard: FlowPersistedJsonObject | None = None


def is_form_field_order(value: object) -> TypeGuard[int]:
    """A writable `order`: a whole number from 1."""

    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def form_field_display_position(order: object, index: int) -> int:
    """Where the editor and the run form show a field: at its `order`, or at its
    position when it has no writable one."""

    return order if is_form_field_order(order) else index + 1


def form_fields_in_display_order(
    fields: list[FlowPersistedJsonObject],
) -> list[FlowPersistedJsonObject]:
    return [
        field
        for _, field in sorted(
            enumerate(fields),
            key=lambda item: form_field_display_position(item[1].get("order"), item[0]),
        )
    ]


def form_field_name_error(
    *,
    message: str,
    code: FlowApiErrorCode,
    index: int,
    field_name: str | None = None,
) -> FlowBadRequestException:
    context: dict[str, object] = {"field_index": index}
    if field_name is not None:
        context["field_name"] = field_name
    return FlowBadRequestException(message, code=code, context=context)


def validate_form_field_runtime_name(index: int, field_name: str) -> None:
    if is_form_field_namespace_head(field_name):
        raise form_field_name_error(
            message=(
                f"Form field {index + 1} is named '{field_name}'. That name is used "
                "as an Eneo variable namespace. Use a field name that describes the "
                "value, for example 'kundnamn' or 'mötesdatum'."
            ),
            code=FlowApiErrorCode.FORM_FIELD_NAME_NAMESPACE_HEAD,
            index=index,
            field_name=field_name,
        )
    if is_reserved_form_field_input_key(field_name):
        raise form_field_name_error(
            message=(
                f"Form field {index + 1} is named '{field_name}'. That name is used "
                "inside Eneo's runtime input payload. Use a more specific field name, "
                "for example 'kundtext' or 'mötesdatum'."
            ),
            code=FlowApiErrorCode.FORM_FIELD_NAME_PRIMARY_INPUT_KEY,
            index=index,
            field_name=field_name,
        )
    if is_step_alias_variable(field_name):
        raise form_field_name_error(
            message=(
                f"Form field {index + 1} is named '{field_name}'. Names like step_1 "
                "are reserved for Flow step aliases. Use a descriptive field name "
                "instead."
            ),
            code=FlowApiErrorCode.FORM_FIELD_NAME_STEP_ALIAS,
            index=index,
            field_name=field_name,
        )


def parse_flow_form_schema(
    metadata_json: FlowPersistedJsonObject | Mapping[str, object] | None,
    *,
    mode: FlowFormSchemaParseMode,
) -> FlowFormSchema | None:
    if metadata_json is None:
        return None

    form_schema = metadata_json.get("form_schema")
    if form_schema is None:
        return None
    if not isinstance(form_schema, Mapping):
        if mode is FlowFormSchemaParseMode.PERSISTED_READ:
            return None
        raise BadRequestException("metadata_json.form_schema must be an object.")
    form_schema_mapping = cast(Mapping[str, object], form_schema)

    fields = form_schema_mapping.get("fields")
    if not isinstance(fields, list):
        if mode is FlowFormSchemaParseMode.PERSISTED_READ:
            return None
        raise BadRequestException("metadata_json.form_schema.fields must be a list.")
    field_values = cast(list[object], fields)

    parsed_fields: list[FlowFormField] = []
    seen_names: set[str] = set()
    seen_orders: set[int] = set()
    seen_roles: set[str] = set()
    for index, field in enumerate(field_values):
        if not isinstance(field, Mapping):
            if mode is FlowFormSchemaParseMode.PERSISTED_READ:
                continue
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}] must be an object."
            )
        field_mapping = cast(Mapping[str, object], field)
        parsed_fields.append(
            _parse_form_field(
                field_mapping,
                index=index,
                mode=mode,
                seen_names=seen_names,
                seen_orders=seen_orders,
                seen_roles=seen_roles,
            )
        )

    schema_payload: dict[str, object] = dict(form_schema_mapping)
    schema_payload["fields"] = parsed_fields
    return FlowFormSchema.model_validate(schema_payload)


def parse_flow_metadata(
    metadata_json: FlowPersistedJsonObject | Mapping[str, object] | None,
    *,
    mode: FlowMetadataParseMode,
) -> FlowMetadata:
    if metadata_json is None:
        return FlowMetadata()

    payload = _top_level_metadata_payload(metadata_json, mode=mode)
    form_schema = parse_flow_form_schema(
        payload,
        mode=_form_schema_mode_for_metadata_mode(mode),
    )
    if form_schema is None:
        payload.pop("form_schema", None)
    else:
        payload["form_schema"] = form_schema

    care_data_policy = _parse_care_data_policy(payload, mode=mode)
    if "care_data_policy" in payload:
        payload["care_data_policy"] = care_data_policy

    evidence_policy = _parse_evidence_policy(payload, mode=mode)
    if "evidence_policy" in payload:
        payload["evidence_policy"] = evidence_policy

    _parse_wizard_metadata(payload, mode=mode)

    return FlowMetadata.model_validate(payload)


def serialize_flow_metadata(metadata: FlowMetadata) -> FlowPersistedJsonObject:
    return metadata.model_dump(mode="json", exclude_unset=True)


def normalize_flow_metadata_for_write(
    metadata_json: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject | None:
    if metadata_json is None:
        return None
    return serialize_flow_metadata(
        parse_flow_metadata(metadata_json, mode=FlowMetadataParseMode.WRITE)
    )


def normalize_persisted_flow_metadata(
    metadata_json: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject | None:
    if metadata_json is None:
        return None
    return serialize_flow_metadata(
        parse_flow_metadata(metadata_json, mode=FlowMetadataParseMode.PERSISTED_READ)
    )


def _form_schema_mode_for_metadata_mode(
    mode: FlowMetadataParseMode,
) -> FlowFormSchemaParseMode:
    if mode is FlowMetadataParseMode.WRITE:
        return FlowFormSchemaParseMode.WRITE
    return FlowFormSchemaParseMode.PERSISTED_READ


def _top_level_metadata_payload(
    metadata_json: Mapping[str, object],
    *,
    mode: FlowMetadataParseMode,
) -> dict[str, object]:
    payload: dict[str, object] = dict(metadata_json)
    unknown_keys = set(payload) - _FLOW_METADATA_TOP_LEVEL_KEYS
    if unknown_keys and mode is FlowMetadataParseMode.WRITE:
        unknown = ", ".join(sorted(unknown_keys))
        raise BadRequestException(
            f"metadata_json contains unknown top-level fields: {unknown}"
        )
    if mode is FlowMetadataParseMode.PERSISTED_READ:
        return {
            key: value
            for key, value in payload.items()
            if key in _FLOW_METADATA_TOP_LEVEL_KEYS
        }
    return payload


def _parse_wizard_metadata(
    payload: dict[str, object],
    *,
    mode: FlowMetadataParseMode,
) -> None:
    if "wizard" not in payload:
        return
    wizard = clone_json_object(payload["wizard"])
    if wizard is None:
        if mode is FlowMetadataParseMode.PERSISTED_READ:
            payload.pop("wizard", None)
            return
        raise BadRequestException("metadata_json.wizard must be an object.")
    payload["wizard"] = wizard


def _parse_evidence_policy(
    metadata_json: Mapping[str, object],
    *,
    mode: FlowMetadataParseMode,
) -> FlowEvidencePolicyMetadata:
    evidence_policy = metadata_json.get("evidence_policy")
    if evidence_policy is None:
        return FlowEvidencePolicyMetadata()
    if not isinstance(evidence_policy, Mapping):
        if mode is FlowMetadataParseMode.PERSISTED_READ:
            return FlowEvidencePolicyMetadata()
        raise BadRequestException("metadata_json.evidence_policy must be an object.")

    policy = cast(Mapping[str, object], evidence_policy)
    allow_export = policy.get("allow_export")
    if mode is FlowMetadataParseMode.PERSISTED_READ:
        # Only a stored boolean counts, so nothing but `true` allows export.
        if isinstance(allow_export, bool):
            return FlowEvidencePolicyMetadata(allow_export=allow_export)
        return FlowEvidencePolicyMetadata()

    unknown_fields = set(policy) - {"allow_export"}
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise BadRequestException(
            f"metadata_json.evidence_policy contains unknown fields: {unknown}"
        )
    if allow_export is None:
        return FlowEvidencePolicyMetadata()
    if not isinstance(allow_export, bool):
        raise BadRequestException(
            "metadata_json.evidence_policy.allow_export must be a boolean."
        )
    return FlowEvidencePolicyMetadata(allow_export=allow_export)


def _parse_care_data_policy(
    metadata_json: Mapping[str, object],
    *,
    mode: FlowMetadataParseMode,
) -> FlowCareDataPolicy:
    care_data_policy = metadata_json.get("care_data_policy")
    if care_data_policy is None:
        return FlowCareDataPolicy()
    if not isinstance(care_data_policy, Mapping):
        if mode is FlowMetadataParseMode.PERSISTED_READ:
            return FlowCareDataPolicy()
        raise BadRequestException("metadata_json.care_data_policy must be an object.")

    policy = cast(Mapping[str, object], care_data_policy)
    if mode is FlowMetadataParseMode.WRITE:
        return _parse_care_data_policy_for_write(policy)
    return _parse_care_data_policy_for_persisted_read(policy)


def _parse_care_data_policy_for_write(
    policy: Mapping[str, object],
) -> FlowCareDataPolicy:
    allowed_fields = {"sensitive", "approval_mode", "pre_approval_visibility"}
    unknown_fields = set(policy) - allowed_fields
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise BadRequestException(
            f"metadata_json.care_data_policy contains unknown fields: {unknown}"
        )

    sensitive = policy.get("sensitive")
    if sensitive is not None and not isinstance(sensitive, bool):
        raise BadRequestException(
            "metadata_json.care_data_policy.sensitive must be a boolean."
        )

    approval_mode = _parse_care_data_approval_mode(policy.get("approval_mode"))
    if policy.get("approval_mode") is not None and approval_mode is None:
        raise BadRequestException(
            "metadata_json.care_data_policy.approval_mode must be 'single_reviewer_outside_flow' when provided."
        )

    pre_approval_visibility = _parse_care_data_pre_approval_visibility(
        policy.get("pre_approval_visibility")
    )
    if (
        policy.get("pre_approval_visibility") is not None
        and pre_approval_visibility is None
    ):
        raise BadRequestException(
            "metadata_json.care_data_policy.pre_approval_visibility must be 'uploader_and_reviewers' when provided."
        )

    policy_payload: dict[str, object] = {}
    if isinstance(sensitive, bool):
        policy_payload["sensitive"] = sensitive
    if approval_mode is not None:
        policy_payload["approval_mode"] = approval_mode
    if pre_approval_visibility is not None:
        policy_payload["pre_approval_visibility"] = pre_approval_visibility
    return FlowCareDataPolicy.model_validate(policy_payload)


def _parse_care_data_policy_for_persisted_read(
    policy: Mapping[str, object],
) -> FlowCareDataPolicy:
    sensitive_value = policy.get("sensitive", False)
    policy_payload: dict[str, object] = {
        # Fail closed for legacy truthy values that predate strict authoring
        # validation; writes must still pass parse_flow_metadata(WRITE).
        "sensitive": bool(sensitive_value),
    }
    approval_mode = _parse_care_data_approval_mode(policy.get("approval_mode"))
    if approval_mode is not None:
        policy_payload["approval_mode"] = approval_mode
    pre_approval_visibility = _parse_care_data_pre_approval_visibility(
        policy.get("pre_approval_visibility")
    )
    if pre_approval_visibility is not None:
        policy_payload["pre_approval_visibility"] = pre_approval_visibility
    return FlowCareDataPolicy.model_validate(policy_payload)


def _parse_care_data_approval_mode(value: object) -> CareDataApprovalMode | None:
    # Only text can be one of the modes; a list or object cannot even be looked up.
    if isinstance(value, str) and value in SUPPORTED_CARE_DATA_APPROVAL_MODES:
        return "single_reviewer_outside_flow"
    return None


def _parse_care_data_pre_approval_visibility(
    value: object,
) -> CareDataPreApprovalVisibility | None:
    if isinstance(value, str) and value in SUPPORTED_CARE_DATA_PRE_APPROVAL_VISIBILITY:
        return "uploader_and_reviewers"
    return None


def _parse_form_field(
    field: Mapping[str, object],
    *,
    index: int,
    mode: FlowFormSchemaParseMode,
    seen_names: set[str],
    seen_orders: set[int],
    seen_roles: set[str],
) -> FlowFormField:
    field_name = _parse_field_name(field, index=index, mode=mode, seen_names=seen_names)
    field_type = parse_saved_form_field_type(field, index=index)
    required = _parse_required(field, index=index, mode=mode)
    order = _parse_order(field, index=index, mode=mode, seen_orders=seen_orders)
    options = _parse_options(field, index=index, field_type=field_type, mode=mode)
    role = _parse_role(
        field, index=index, field_type=field_type, mode=mode, seen_roles=seen_roles
    )

    payload = dict(field)
    payload["name"] = field_name
    payload["type"] = field_type
    _require_text_label(field, index=index)
    if "required" in field or required:
        payload["required"] = required
    if "order" in field or order is not None:
        payload["order"] = order
    if "options" in field or options is not None:
        payload["options"] = options
    if role is None:
        payload.pop("role", None)
    else:
        payload["role"] = role
    return FlowFormField.model_validate(payload)


def _parse_field_name(
    field: Mapping[str, object],
    *,
    index: int,
    mode: FlowFormSchemaParseMode,
    seen_names: set[str],
) -> str:
    field_name = field.get("name")
    if not isinstance(field_name, str) or not field_name.strip():
        raise form_field_name_error(
            message=f"Form field {index + 1} needs a name before the flow can be saved.",
            code=FlowApiErrorCode.FORM_FIELD_NAME_EMPTY,
            index=index,
        )
    stripped_field_name = field_name.strip()
    normalized_name = stripped_field_name.casefold()
    if mode is FlowFormSchemaParseMode.WRITE:
        if normalized_name in seen_names:
            raise form_field_name_error(
                message=(
                    f"Form field {index + 1} uses the name '{stripped_field_name}', "
                    "but another form field already uses that name. Use a unique field name."
                ),
                code=FlowApiErrorCode.FORM_FIELD_NAME_DUPLICATE,
                index=index,
                field_name=stripped_field_name,
            )
        if "." in field_name:
            raise form_field_name_error(
                message=(
                    f"Form field {index + 1} is named '{stripped_field_name}'. Field names "
                    "cannot contain dots because dots are used to read nested variables. "
                    "Use underscores instead, for example 'kund_namn'."
                ),
                code=FlowApiErrorCode.FORM_FIELD_NAME_DOT,
                index=index,
                field_name=stripped_field_name,
            )
        if "{{" in field_name or "}}" in field_name:
            raise form_field_name_error(
                message=(
                    f"Form field {index + 1} is named '{stripped_field_name}'. Field names "
                    "should be plain names without {{ }}. Name the field first, then use "
                    "that field as a variable inside prompts, for example {{flow_input.kundnamn}}."
                ),
                code=FlowApiErrorCode.FORM_FIELD_NAME_TEMPLATE_DELIMITERS,
                index=index,
                field_name=stripped_field_name,
            )
        validate_form_field_runtime_name(index, stripped_field_name)
    seen_names.add(normalized_name)
    return stripped_field_name


class UnsupportedFlowFormFieldTypeError(ValueError):
    def __init__(self, raw_type: str) -> None:
        self.raw_type = raw_type
        super().__init__(
            f"Form field type {raw_type!r} is not supported; it must be one of "
            f"{sorted(_FORM_FIELD_TYPES_BY_VALUE)}."
        )


def parse_flow_form_field_type(raw_type: str) -> FlowFormFieldType:
    """The one rule for which form field types exist, for every writer."""

    normalized_type = raw_type.strip().casefold()
    parsed_type = _LEGACY_FORM_FIELD_TYPE_NORMALIZATION.get(normalized_type)
    if parsed_type is None:
        parsed_type = _FORM_FIELD_TYPES_BY_VALUE.get(normalized_type)
    if parsed_type is None:
        raise UnsupportedFlowFormFieldTypeError(raw_type)
    return parsed_type


def parse_saved_form_field_type(
    field: Mapping[str, object], *, index: int
) -> FlowFormFieldType:
    field_type = field.get("type")
    if not isinstance(field_type, str) or not field_type.strip():
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].type must be a non-empty string."
        )
    try:
        return parse_flow_form_field_type(field_type)
    except UnsupportedFlowFormFieldTypeError:
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].type must be one of "
            f"{sorted(_FORM_FIELD_TYPES_BY_VALUE)}."
        ) from None


def _require_text_label(field: Mapping[str, object], *, index: int) -> None:
    """A caption that is no text is refused with its path, like an unusable
    type or options list: on write, and when a stored schema is read (the
    reader of published definitions names that a corrupt form schema)."""

    label = field.get("label")
    if label is not None and not isinstance(label, str):
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].label must be a string."
        )


def _parse_required(
    field: Mapping[str, object],
    *,
    index: int,
    mode: FlowFormSchemaParseMode,
) -> bool:
    if "required" not in field:
        return False
    required = field["required"]
    if isinstance(required, bool):
        return required
    if mode is FlowFormSchemaParseMode.PERSISTED_READ:
        return False
    raise BadRequestException(
        f"metadata_json.form_schema.fields[{index}].required must be a boolean."
    )


def _parse_order(
    field: Mapping[str, object],
    *,
    index: int,
    mode: FlowFormSchemaParseMode,
    seen_orders: set[int],
) -> int | None:
    if "order" not in field:
        return None
    order = field["order"]
    if not isinstance(order, int) or isinstance(order, bool):
        if mode is FlowFormSchemaParseMode.PERSISTED_READ:
            return None
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].order must be an integer."
        )
    if order < 1:
        if mode is FlowFormSchemaParseMode.PERSISTED_READ:
            return None
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].order must be >= 1."
        )
    if mode is FlowFormSchemaParseMode.WRITE:
        if order in seen_orders:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].order must be unique."
            )
        seen_orders.add(order)
    return order


def _parse_options(
    field: Mapping[str, object],
    *,
    index: int,
    field_type: FlowFormFieldType,
    mode: FlowFormSchemaParseMode,
) -> list[str] | None:
    options = field.get("options")
    if field_type is FlowFormFieldType.MULTISELECT:
        if options is None or not isinstance(options, list):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options must be a list for multiselect."
            )
        parsed = parse_form_field_options(cast(list[object], options), index=index)
        if mode is FlowFormSchemaParseMode.WRITE and not parsed:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options must contain at "
                "least one option for multiselect. Use type 'list' for free entry."
            )
        return parsed
    if field_type is FlowFormFieldType.SELECT:
        if options is not None and not isinstance(options, list):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options must be a list for select."
            )
        if isinstance(options, list):
            parsed = parse_form_field_options(cast(list[object], options), index=index)
            if mode is FlowFormSchemaParseMode.WRITE and not parsed:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].options must contain "
                    "at least one option for select."
                )
            return parsed
        return None
    if options is not None:
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].options is only valid for "
            "select or multiselect."
        )
    return None


def _parse_role(
    field: Mapping[str, object],
    *,
    index: int,
    field_type: FlowFormFieldType,
    mode: FlowFormSchemaParseMode,
    seen_roles: set[str],
) -> FlowFormFieldRole | None:
    """The field's role, which one field of its type at most holds. A stored
    role that cannot hold is dropped; the field stays."""
    role = field.get("role")
    if role is None:
        return None
    path = f"metadata_json.form_schema.fields[{index}].role"
    if not isinstance(role, str) or role not in _ROLE_FIELD_TYPES:
        problem = f"{path} must be 'run_label' or 'run_date'."
    elif _ROLE_FIELD_TYPES[role] is not field_type:
        problem = (
            f"{path} '{role}' is only valid for a "
            f"{_ROLE_FIELD_TYPES[role].value} field."
        )
    elif role in seen_roles:
        problem = f"{path} '{role}' is already on another field."
    else:
        seen_roles.add(role)
        return cast(FlowFormFieldRole, role)
    if mode is FlowFormSchemaParseMode.PERSISTED_READ:
        return None
    raise BadRequestException(problem)


def parse_form_field_options(options: list[object], *, index: int) -> list[str]:
    """The options of the form field at ``index``, each stripped; raises for a
    blank one or one that repeats another in any case."""
    parsed_options: list[str] = []
    normalized_options: set[str] = set()
    for option_index, option in enumerate(options):
        if not isinstance(option, str) or not option.strip():
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                "must be a non-empty string."
            )
        stripped_option = option.strip()
        option_key = stripped_option.casefold()
        if option_key in normalized_options:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                "must be unique."
            )
        normalized_options.add(option_key)
        parsed_options.append(stripped_option)
    return parsed_options
