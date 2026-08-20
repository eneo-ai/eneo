"""Active proposal tool schema."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

import jsonschema
from jsonschema.validators import validator_for

from eneo.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    RESULT_KEYS_ARGUMENT,
    ProposalObligationProjection,
    build_create_flow_tool_schema,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    extract_assumptions,
    extract_plan_rationale,
)

if TYPE_CHECKING:
    from eneo.flows.domain.flow import FlowStep


class ProposalToolFunction(TypedDict):
    name: str
    parameters: dict[str, Any]
    strict: NotRequired[bool]


class ProposalToolSchema(TypedDict):
    type: Literal["function"]
    function: ProposalToolFunction


def build_propose_flow_tool_schema(
    *,
    resource_catalog: AIBuilderResourceCatalog,
    current_steps: list["FlowStep"] | None = None,
    is_pure_audio_transcription: bool = False,
    confirmed_runtime_inputs: tuple[ConfirmedRuntimeInputRequirement, ...] = (),
    obligation_projection: ProposalObligationProjection | None = None,
) -> ProposalToolSchema:
    if current_steps is None:
        return cast(
            ProposalToolSchema,
            build_create_flow_tool_schema(
                resource_catalog=resource_catalog,
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                is_pure_audio_transcription=is_pure_audio_transcription,
                confirmed_runtime_inputs=confirmed_runtime_inputs,
                obligation_projection=obligation_projection,
            ),
        )
    return cast(
        ProposalToolSchema,
        build_edit_flow_tool_schema(
            current_steps,
            resource_catalog=resource_catalog,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        ),
    )


class ProposalToolArgumentsError(ValueError):
    """The provider returned arguments outside the prepared proposal schema."""

    def __init__(self, message: str, *, validator: str) -> None:
        super().__init__(message)
        self.validator = validator


class NativeStrictSchemaError(ValueError):
    """The schema is outside the subset providers accept as strict tools."""


def build_native_strict_tool_schema(
    tool_schema: ProposalToolSchema,
) -> ProposalToolSchema:
    """Project a semantic tool schema into the native-strict transport subset.

    The semantic schema remains the server admission contract. Strict-capable
    routes receive a derived copy where every object property is required and
    provider-unsupported annotations are removed; nullable types preserve the
    optional values themselves.
    """

    function = tool_schema["function"]
    parameters = _native_strict_schema_node(function["parameters"])
    validate_native_strict_schema(parameters)
    return {
        **tool_schema,
        "function": {
            **function,
            "parameters": parameters,
            "strict": True,
        },
    }


def _native_strict_schema_node(node: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(node)
    projected.pop("default", None)
    projected.pop("uniqueItems", None)

    properties = projected.get("properties")
    schema_type = projected.get("type")
    schema_types = (
        cast(list[object], schema_type)
        if isinstance(schema_type, list)
        else [schema_type]
    )
    if "object" in schema_types and isinstance(properties, dict):
        typed_properties = cast(dict[str, Any], properties)
        projected["required"] = list(typed_properties)
        projected["properties"] = {
            name: _native_strict_schema_node(value)
            for name, value in typed_properties.items()
        }

    items = projected.get("items")
    if isinstance(items, dict):
        projected["items"] = _native_strict_schema_node(cast(dict[str, Any], items))
    for keyword in ("anyOf", "prefixItems"):
        branches = projected.get(keyword)
        if isinstance(branches, list):
            projected[keyword] = [
                _native_strict_schema_node(cast(dict[str, Any], branch))
                if isinstance(branch, dict)
                else deepcopy(branch)
                for branch in cast(list[object], branches)
            ]
    definitions = projected.get("$defs")
    if isinstance(definitions, dict):
        typed_definitions = cast(dict[str, Any], definitions)
        projected["$defs"] = {
            name: _native_strict_schema_node(value)
            for name, value in typed_definitions.items()
        }
    return projected


# Keywords providers reject in a native strict tool schema.
_UNSUPPORTED_NATIVE_STRICT_KEYWORDS = frozenset(
    {
        "allOf",
        "contains",
        "dependentRequired",
        "dependentSchemas",
        "else",
        "if",
        "maxContains",
        "maxProperties",
        "minContains",
        "minProperties",
        "not",
        "oneOf",
        "patternProperties",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
        "uniqueItems",
    }
)
_NATIVE_STRICT_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)


def validate_native_strict_schema(parameters: dict[str, Any]) -> None:
    """Confirm one parameter schema is valid and native-strict compatible.

    Providers accept a narrow JSON Schema subset when a tool is marked strict:
    closed objects, a `required` list naming every property, no unsupported
    keywords. A schema outside it is rejected before the request, so a provider
    rejection means the provider, not the schema.
    """
    validator_class = validator_for(parameters)
    try:
        validator_class.check_schema(parameters)
    except jsonschema.SchemaError as error:
        raise NativeStrictSchemaError(
            f"invalid JSON Schema: {error.message}"
        ) from error
    if parameters.get("type") != "object":
        raise NativeStrictSchemaError("tool parameters must be an object schema")
    _check_native_strict_node(parameters, path="$")


def _check_native_strict_node(node: object, *, path: str) -> None:
    """Check one schema node, then only the places schemas actually live.

    Walking every nested dictionary would treat a property map as a schema, so
    a property named `type` or `required` would be read as a keyword.
    """
    if not isinstance(node, dict):
        return

    schema = cast(dict[str, object], node)
    schema_type = schema.get("type")
    schema_types: list[object] = (
        cast(list[object], schema_type)
        if isinstance(schema_type, list)
        else [schema_type]
    )
    if schema_type is not None and not set(
        value for value in schema_types if isinstance(value, str)
    ) == set(schema_types):
        raise NativeStrictSchemaError(f"{path}: schema type must be a string")
    if schema_type is not None and not set(schema_types) <= _NATIVE_STRICT_TYPES:
        raise NativeStrictSchemaError(f"{path}: unsupported schema type")

    properties = schema.get("properties")
    if "object" in schema_types:
        required = schema.get("required")
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise NativeStrictSchemaError(
                f"{path}: object needs properties and required"
            )
        if set(cast(list[object], required)) != set(
            cast(dict[str, object], properties)
        ):
            raise NativeStrictSchemaError(f"{path}: required must name every property")
        if schema.get("additionalProperties") is not False:
            raise NativeStrictSchemaError(f"{path}: object must be closed")

    branches = schema.get("anyOf")
    if branches is not None and (
        not isinstance(branches, list) or len(cast(list[object], branches)) < 2
    ):
        raise NativeStrictSchemaError(f"{path}: anyOf needs at least two branches")

    unsupported = _UNSUPPORTED_NATIVE_STRICT_KEYWORDS & schema.keys()
    if unsupported:
        raise NativeStrictSchemaError(
            f"{path}: unsupported keyword {sorted(unsupported)[0]}"
        )

    if isinstance(properties, dict):
        for name, value in cast(dict[str, object], properties).items():
            _check_native_strict_node(value, path=f"{path}.properties.{name}")
    for keyword in ("items", "additionalProperties", "not"):
        _check_native_strict_node(schema.get(keyword), path=f"{path}.{keyword}")
    for keyword in ("anyOf", "prefixItems"):
        nested = schema.get(keyword)
        if isinstance(nested, list):
            for index, branch in enumerate(cast(list[object], nested)):
                _check_native_strict_node(branch, path=f"{path}.{keyword}[{index}]")
    definitions = schema.get("$defs")
    if isinstance(definitions, dict):
        for name, value in cast(dict[str, object], definitions).items():
            _check_native_strict_node(value, path=f"{path}.$defs.{name}")


def validate_propose_flow_tool_arguments(
    *,
    arguments: dict[str, Any],
    tool_schema: ProposalToolSchema,
) -> None:
    parameters = tool_schema["function"]["parameters"]
    validator_class = validator_for(parameters)
    validator_class.check_schema(parameters)
    error = next(validator_class(parameters).iter_errors(arguments), None)
    if error is None:
        return

    actionable_error = _actionable_validation_error(error)
    path = ".".join(str(part) for part in actionable_error.absolute_path) or "root"
    raise ProposalToolArgumentsError(
        f"{path}: {actionable_error.message} ({actionable_error.validator})",
        validator=str(actionable_error.validator),
    ) from error


def admit_propose_flow_tool_arguments(
    *,
    arguments: dict[str, Any],
    tool_schema: ProposalToolSchema,
) -> dict[str, Any]:
    """Admit one proposal payload after deterministic schema-guided normalization.

    Some non-strict tool implementations occasionally close the adjacent
    ``steps`` and ``output_fields`` arrays at the wrong boundary. The prepared
    create schema makes those cases unambiguous: each complete object matches
    exactly one of the two shapes. Models can also copy ``output_fields``
    children into the flat, server-owned ``result_keys`` projection. Rehome the
    unambiguous array entries and discard only that non-authoritative nested
    copy, then apply the unchanged proposal schema to the full payload.
    """

    admitted = _rehome_misplaced_create_children(
        arguments=arguments,
        tool_schema=tool_schema,
    )
    admitted = _discard_server_owned_result_key_children(
        arguments=admitted,
        tool_schema=tool_schema,
    )
    admitted = _discard_primitive_field_boolean_children(
        arguments=admitted,
        tool_schema=tool_schema,
    )
    validate_propose_flow_tool_arguments(
        arguments=admitted,
        tool_schema=tool_schema,
    )
    return admitted


def _discard_server_owned_result_key_children(
    *,
    arguments: dict[str, Any],
    tool_schema: ProposalToolSchema,
) -> dict[str, Any]:
    """Discard nested shape guesses the prepared result-key schema does not own."""

    raw_root_properties = tool_schema["function"]["parameters"].get("properties")
    if not isinstance(raw_root_properties, dict):
        return arguments
    result_keys_schema = cast(dict[str, object], raw_root_properties).get(
        RESULT_KEYS_ARGUMENT
    )
    if not isinstance(result_keys_schema, dict):
        return arguments
    raw_record_schemas = cast(dict[str, object], result_keys_schema).get("properties")
    if not isinstance(raw_record_schemas, dict):
        return arguments

    raw_result_keys = arguments.get(RESULT_KEYS_ARGUMENT)
    if not isinstance(raw_result_keys, dict):
        return arguments

    admitted_result_keys = cast(dict[str, object], raw_result_keys)
    updated_result_keys: dict[str, object] | None = None
    for name, raw_record in admitted_result_keys.items():
        record_schema = cast(dict[str, object], raw_record_schemas).get(name)
        if not isinstance(raw_record, dict) or not isinstance(record_schema, dict):
            continue
        raw_allowed_properties = cast(dict[str, object], record_schema).get(
            "properties"
        )
        if (
            not isinstance(raw_allowed_properties, dict)
            or "children" in raw_allowed_properties
            or "children" not in raw_record
        ):
            continue
        if updated_result_keys is None:
            updated_result_keys = dict(admitted_result_keys)
        updated_result_keys[name] = {
            key: value
            for key, value in cast(dict[str, object], raw_record).items()
            if key != "children"
        }

    if updated_result_keys is None:
        return arguments
    return {**arguments, RESULT_KEYS_ARGUMENT: updated_result_keys}


def _discard_primitive_field_boolean_children(
    *,
    arguments: dict[str, Any],
    tool_schema: ProposalToolSchema,
) -> dict[str, Any]:
    """Discard a non-structural boolean copied onto a primitive field.

    A boolean cannot describe nested fields, and primitive fields cannot own
    them. Nested field records remain untouched so a contradictory primitive
    type still fails admission instead of silently losing authored content.
    """

    parameters = tool_schema["function"]["parameters"]
    raw_properties = parameters.get("properties")
    if not isinstance(raw_properties, dict) or "steps" not in raw_properties:
        return arguments

    raw_steps = arguments.get("steps")
    if not isinstance(raw_steps, list):
        return arguments

    admitted_steps: list[object] = []
    changed = False
    for raw_step in cast(list[object], raw_steps):
        if not isinstance(raw_step, dict):
            admitted_steps.append(raw_step)
            continue
        step = cast(dict[str, object], raw_step)
        raw_fields = step.get("output_fields")
        if not isinstance(raw_fields, list):
            admitted_steps.append(step)
            continue
        admitted_fields, fields_changed = _discard_boolean_primitive_children(
            cast(list[object], raw_fields)
        )
        if not fields_changed:
            admitted_steps.append(step)
            continue
        changed = True
        admitted_steps.append({**step, "output_fields": admitted_fields})

    if not changed:
        return arguments
    return {**arguments, "steps": admitted_steps}


def _discard_boolean_primitive_children(
    fields: list[object],
) -> tuple[list[object], bool]:
    admitted_fields: list[object] = []
    changed = False
    for raw_field in fields:
        if not isinstance(raw_field, dict):
            admitted_fields.append(raw_field)
            continue
        field = cast(dict[str, object], raw_field)
        admitted_field = field
        children = field.get("children")
        if field.get("field_type") in {"string", "number", "boolean"} and isinstance(
            children, bool
        ):
            admitted_field = {
                key: value for key, value in field.items() if key != "children"
            }
            changed = True
        elif isinstance(children, list):
            admitted_children, children_changed = _discard_boolean_primitive_children(
                cast(list[object], children)
            )
            if children_changed:
                admitted_field = {**field, "children": admitted_children}
                changed = True
        admitted_fields.append(admitted_field)
    return admitted_fields, changed


def _rehome_misplaced_create_children(
    *,
    arguments: dict[str, Any],
    tool_schema: ProposalToolSchema,
) -> dict[str, Any]:
    parameters = tool_schema["function"]["parameters"]
    raw_properties = parameters.get("properties")
    if not isinstance(raw_properties, dict):
        return arguments
    properties = cast(dict[str, object], raw_properties)
    steps_schema = properties.get("steps")
    if not isinstance(steps_schema, dict):
        return arguments
    step_schema = cast(dict[str, object], steps_schema).get("items")
    if not isinstance(step_schema, dict):
        return arguments
    step_schema_map = cast(dict[str, object], step_schema)
    step_properties = step_schema_map.get("properties")
    raw_required_step_keys = step_schema_map.get("required")
    if not isinstance(step_properties, dict) or not isinstance(
        raw_required_step_keys, list
    ):
        return arguments
    step_properties_map = cast(dict[str, object], step_properties)
    allowed_step_keys = frozenset(step_properties_map)
    required_step_keys = frozenset(
        value
        for value in cast(list[object], raw_required_step_keys)
        if isinstance(value, str)
    )
    output_fields_schema = step_properties_map.get("output_fields")
    if not isinstance(output_fields_schema, dict):
        return arguments
    field_schema = cast(dict[str, object], output_fields_schema).get("items")
    if not isinstance(field_schema, dict):
        return arguments
    field_schema_map = cast(dict[str, object], field_schema)
    raw_field_properties = field_schema_map.get("properties")
    raw_required_field_keys = field_schema_map.get("required")
    if not isinstance(raw_field_properties, dict) or not isinstance(
        raw_required_field_keys, list
    ):
        return arguments
    allowed_field_keys = frozenset(cast(dict[str, object], raw_field_properties).keys())
    required_field_keys = frozenset(
        value
        for value in cast(list[object], raw_required_field_keys)
        if isinstance(value, str)
    )

    raw_steps = arguments.get("steps")
    if not isinstance(raw_steps, list):
        return arguments
    pending = deque(cast(list[object], raw_steps))
    admitted_steps: list[object] = []
    changed = False
    while pending:
        candidate = pending.popleft()
        previous = admitted_steps[-1] if admitted_steps else None
        candidate_map = (
            cast(dict[str, object], candidate) if isinstance(candidate, dict) else None
        )
        previous_map = (
            cast(dict[str, object], previous) if isinstance(previous, dict) else None
        )
        if (
            candidate_map is not None
            and "instructions" not in candidate_map
            and required_field_keys.issubset(candidate_map)
            and candidate_map.keys() <= allowed_field_keys
            and previous_map is not None
            and isinstance(previous_map.get("instructions"), str)
        ):
            existing_fields = previous_map.get("output_fields")
            if existing_fields is None or isinstance(existing_fields, list):
                admitted_steps[-1] = {
                    **previous_map,
                    "output_fields": [
                        *cast(list[object], existing_fields or []),
                        candidate_map,
                    ],
                }
                changed = True
                continue

        nested_steps: list[object] = []
        if (
            candidate_map is not None
            and required_step_keys.issubset(candidate_map)
            and candidate_map.keys() <= allowed_step_keys
        ):
            raw_output_fields = candidate_map.get("output_fields")
            if isinstance(raw_output_fields, list):
                admitted_fields: list[object] = []
                for output_field in cast(list[object], raw_output_fields):
                    output_field_map = (
                        cast(dict[str, object], output_field)
                        if isinstance(output_field, dict)
                        else None
                    )
                    if (
                        output_field_map is not None
                        and required_step_keys.issubset(output_field_map)
                        and output_field_map.keys() <= allowed_step_keys
                    ):
                        nested_steps.append(output_field_map)
                        changed = True
                    else:
                        admitted_fields.append(cast(object, output_field))
                if nested_steps:
                    candidate_map = {**candidate_map}
                    if admitted_fields:
                        candidate_map["output_fields"] = admitted_fields
                    else:
                        candidate_map.pop("output_fields", None)

        admitted_steps.append(candidate_map or cast(object, candidate))
        pending.extendleft(reversed(nested_steps))

    admitted = {**arguments, "steps": admitted_steps} if changed else arguments

    # A non-strict tool implementation can also close the final step object
    # before its optional tail. Rehome only keys that the prepared schema says
    # are optional step properties and never valid at the root. An identical
    # duplicate is redundant and can be discarded; conflicting values stay
    # invalid rather than guessing which value should win.
    root_keys = frozenset(properties)
    step_tail_keys = allowed_step_keys - root_keys - required_step_keys
    misplaced_tail = step_tail_keys.intersection(admitted)
    admitted_tail_steps = admitted.get("steps")
    if not misplaced_tail or not isinstance(admitted_tail_steps, list):
        return admitted
    tail_steps = list(cast(list[object], admitted_tail_steps))
    if not tail_steps or not isinstance(tail_steps[-1], dict):
        return admitted
    final_step = cast(dict[str, object], tail_steps[-1])
    movable_tail = tuple(key for key in misplaced_tail if key not in final_step)
    redundant_tail = tuple(
        key
        for key in misplaced_tail
        if key in final_step and admitted[key] == final_step[key]
    )
    removable_tail = (*movable_tail, *redundant_tail)
    if not removable_tail:
        return admitted
    updated = {
        key: value for key, value in admitted.items() if key not in removable_tail
    }
    if movable_tail:
        tail_steps[-1] = {
            **final_step,
            **{key: admitted[key] for key in movable_tail},
        }
    updated["steps"] = tail_steps
    return updated


def _actionable_validation_error(
    error: jsonschema.ValidationError,
) -> jsonschema.ValidationError:
    if error.validator != "oneOf" or not error.context:
        return error

    branch_index = _matching_discriminator_branch_index(error)
    branch_errors = [
        candidate
        for candidate in error.context
        if branch_index is not None
        and candidate.relative_schema_path
        and candidate.relative_schema_path[0] == branch_index
    ]
    candidates: list[jsonschema.ValidationError] = branch_errors or list(error.context)
    selected = next(
        (candidate for candidate in candidates if candidate.validator == "required"),
        None,
    ) or max(
        candidates,
        key=lambda candidate: len(tuple(candidate.absolute_path)),
        default=None,
    )
    return _actionable_validation_error(selected) if selected is not None else error


def _matching_discriminator_branch_index(
    error: jsonschema.ValidationError,
) -> int | None:
    instance_object: object = error.instance
    schema_object: object = error.schema
    if not isinstance(instance_object, dict) or not isinstance(schema_object, dict):
        return None
    instance = cast(dict[str, object], instance_object)
    schema = cast(dict[str, object], schema_object)
    raw_branches = schema.get("oneOf")
    if not isinstance(raw_branches, list):
        return None
    branches = cast(list[object], raw_branches)

    for discriminator in ("kind", "type"):
        value = instance.get(discriminator)
        if not isinstance(value, str):
            continue
        matches: list[int] = []
        for index, branch in enumerate(branches):
            if not isinstance(branch, dict):
                continue
            branch_map = cast(dict[str, object], branch)
            raw_properties = branch_map.get("properties")
            if not isinstance(raw_properties, dict):
                continue
            properties = cast(dict[str, object], raw_properties)
            raw_discriminator_schema = properties.get(discriminator)
            if not isinstance(raw_discriminator_schema, dict):
                continue
            discriminator_schema = cast(dict[str, object], raw_discriminator_schema)
            raw_values = discriminator_schema.get("enum")
            if isinstance(raw_values, list) and value in raw_values:
                matches.append(index)
        if len(matches) == 1:
            return matches[0]
    return None


__all__ = [
    "admit_propose_flow_tool_arguments",
    "build_propose_flow_tool_schema",
    "ProposalToolArgumentsError",
    "ProposalToolSchema",
    "extract_assumptions",
    "extract_plan_rationale",
    "parse_create_flow_intent_arguments",
    "validate_propose_flow_tool_arguments",
]
