from __future__ import annotations

from enum import Enum
from typing import Literal, Mapping, cast

from pydantic import BaseModel, ConfigDict, Field

from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.flow_variable_definitions import (
    is_form_field_namespace_head,
    is_reserved_form_field_input_key,
    is_step_alias_variable,
)
from intric.main.exceptions import BadRequestException


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


class FlowFormField(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    type: FlowFormFieldType
    label: str | None = None
    required: bool = False
    options: list[str] | None = None
    order: int | None = None


class FlowFormSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    fields: list[FlowFormField]


class FlowCareDataPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sensitive: bool = False
    approval_mode: CareDataApprovalMode | None = None
    pre_approval_visibility: CareDataPreApprovalVisibility | None = None


class FlowMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    form_schema: FlowFormSchema | None = None
    care_data_policy: FlowCareDataPolicy = Field(default_factory=FlowCareDataPolicy)


def form_field_name_error(
    *,
    message: str,
    code: str,
    index: int,
    field_name: str | None = None,
) -> BadRequestException:
    context: dict[str, object] = {"field_index": index}
    if field_name is not None:
        context["field_name"] = field_name
    return BadRequestException(message, code=code, context=context)


def validate_form_field_runtime_name(index: int, field_name: str) -> None:
    if is_form_field_namespace_head(field_name):
        raise form_field_name_error(
            message=(
                f"Form field {index + 1} is named '{field_name}'. That name is used "
                "as an Eneo variable namespace. Use a field name that describes the "
                "value, for example 'kundnamn' or 'mötesdatum'."
            ),
            code="flow_form_field_name_namespace_head",
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
            code="flow_form_field_name_primary_input_key",
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
            )
        )

    schema_payload: dict[str, object] = dict(form_schema_mapping)
    schema_payload["fields"] = parsed_fields
    return FlowFormSchema.model_validate(schema_payload)


def serialize_flow_form_schema(schema: FlowFormSchema) -> FlowPersistedJsonObject:
    return schema.model_dump(mode="json", exclude_unset=True)


def parse_flow_metadata(
    metadata_json: FlowPersistedJsonObject | Mapping[str, object] | None,
    *,
    mode: FlowMetadataParseMode,
) -> FlowMetadata:
    if metadata_json is None:
        return FlowMetadata()

    payload = dict(metadata_json)
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
    if value in SUPPORTED_CARE_DATA_APPROVAL_MODES:
        return "single_reviewer_outside_flow"
    return None


def _parse_care_data_pre_approval_visibility(
    value: object,
) -> CareDataPreApprovalVisibility | None:
    if value in SUPPORTED_CARE_DATA_PRE_APPROVAL_VISIBILITY:
        return "uploader_and_reviewers"
    return None


def _parse_form_field(
    field: Mapping[str, object],
    *,
    index: int,
    mode: FlowFormSchemaParseMode,
    seen_names: set[str],
    seen_orders: set[int],
) -> FlowFormField:
    field_name = _parse_field_name(field, index=index, mode=mode, seen_names=seen_names)
    field_type = _parse_field_type(field, index=index)
    required = _parse_required(field, index=index, mode=mode)
    order = _parse_order(field, index=index, mode=mode, seen_orders=seen_orders)
    options = _parse_options(field, index=index, field_type=field_type, mode=mode)

    payload = dict(field)
    payload["name"] = field_name
    payload["type"] = field_type
    if "required" in field or required:
        payload["required"] = required
    if "order" in field or order is not None:
        payload["order"] = order
    if "options" in field or options is not None:
        payload["options"] = options
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
            code="flow_form_field_name_empty",
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
                code="flow_form_field_name_duplicate",
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
                code="flow_form_field_name_dot",
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
                code="flow_form_field_name_template_delimiters",
                index=index,
                field_name=stripped_field_name,
            )
        validate_form_field_runtime_name(index, stripped_field_name)
        if is_step_alias_variable(normalized_name):
            raise form_field_name_error(
                message=(
                    f"Form field {index + 1} is named '{stripped_field_name}'. Names like "
                    "step_1 are reserved for flow steps. Use a descriptive field name "
                    "such as 'ärendenummer' instead."
                ),
                code="flow_form_field_name_step_alias",
                index=index,
                field_name=stripped_field_name,
            )
    seen_names.add(normalized_name)
    return stripped_field_name


def _parse_field_type(field: Mapping[str, object], *, index: int) -> FlowFormFieldType:
    field_type = field.get("type")
    if not isinstance(field_type, str) or not field_type.strip():
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].type must be a non-empty string."
        )
    normalized_type = field_type.strip().casefold()
    parsed_type = _LEGACY_FORM_FIELD_TYPE_NORMALIZATION.get(normalized_type)
    if parsed_type is None:
        parsed_type = _FORM_FIELD_TYPES_BY_VALUE.get(normalized_type)
    if parsed_type is None:
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].type must be one of "
            f"{sorted(_FORM_FIELD_TYPES_BY_VALUE)}."
        )
    return parsed_type


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
        return _parse_option_list(cast(list[object], options), index=index)
    if field_type is FlowFormFieldType.SELECT:
        if options is not None and not isinstance(options, list):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options must be a list for select."
            )
        if isinstance(options, list):
            return _parse_option_list(cast(list[object], options), index=index)
        return None
    if options is not None:
        raise BadRequestException(
            f"metadata_json.form_schema.fields[{index}].options is only valid for select or multiselect."
        )
    return None


def _parse_option_list(options: list[object], *, index: int) -> list[str]:
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
