from __future__ import annotations

import hashlib
import json
import re
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa

from intric.assistants.assistant import Assistant, AssistantOrigin
from intric.assistants.assistant_service import AssistantService
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.spaces_table import Spaces
from intric.flows.flow import Flow, FlowSparse, FlowStep, JsonObject
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_version_repo import FlowVersionRepository
from intric.flows.step_config_secrets import encrypt_step_headers_for_storage
from intric.flows.step_chain_rules import find_first_step_chain_violation
from intric.flows.variable_resolver import iter_template_expressions
from intric.flows.output_processing import validate_schema_syntax
from intric.flows.type_policies import INPUT_TYPE_POLICIES
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, NotFoundException, TypedIOValidationException
from intric.main.models import NOT_PROVIDED, NotProvided, ResourcePermission
from intric.settings.encryption_service import EncryptionService
from intric.users.user import UserInDB

_STEP_REFERENCE_PATTERN = re.compile(r"^step_(\d+)$")

_ALLOWED_FORM_FIELD_TYPES = {"text", "multiselect", "number", "date", "select"}
_LEGACY_FORM_FIELD_TYPE_NORMALIZATION = {
    "string": "text",
    "email": "text",
    "textarea": "text",
}
_RESERVED_VARIABLE_ALIASES = {
    "flow",
    "flow_input",
    "transkribering",
    "föregående_steg",
    "indata_text",
    "indata_json",
    "indata_filer",
}
_RESERVED_VARIABLE_ALIASES_NORMALIZED = {
    alias.casefold() for alias in _RESERVED_VARIABLE_ALIASES
}
_STEP_ALIAS_PATTERN = re.compile(r"^step_\d+($|[._])")


class FlowService:
    """Tenant-scoped business service for flow lifecycle operations."""

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_version_repo: FlowVersionRepository,
        assistant_service: AssistantService,
        encryption_service: EncryptionService | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_version_repo = flow_version_repo
        self.assistant_service = assistant_service
        self.encryption_service = encryption_service

    async def create_flow(
        self,
        *,
        space_id: UUID,
        name: str,
        steps: list[FlowStep],
        description: str | None = None,
        metadata_json: JsonObject | None = None,
        data_retention_days: int | None = None,
        owner_user_id: UUID | None = None,
    ) -> Flow:
        normalized_metadata = self._normalize_legacy_form_schema(metadata_json)
        self._validate_form_schema(normalized_metadata)
        self._validate_steps(steps)
        self._validate_variable_alias_collisions(
            steps=steps,
            metadata_json=normalized_metadata,
        )
        await self._validate_assistant_scope_for_steps(
            space_id=space_id,
            steps=steps,
        )

        normalized_steps = self._normalize_steps_for_tenant(steps)
        persisted_steps = self._prepare_steps_for_persist(normalized_steps)
        flow = Flow(
            id=None,
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            name=name,
            description=description,
            created_by_user_id=self.user.id,
            owner_user_id=owner_user_id or self.user.id,
            published_version=None,
            metadata_json=normalized_metadata,
            data_retention_days=data_retention_days,
            created_at=None,
            updated_at=None,
            steps=persisted_steps,
        )
        return await self.flow_repo.create(flow=flow, tenant_id=self.user.tenant_id)

    async def get_flow(self, flow_id: UUID) -> Flow:
        return await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)

    async def list_flows(
        self,
        *,
        space_id: UUID,
        sparse: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowSparse] | list[Flow]:
        if sparse:
            return await self.flow_repo.get_sparse_by_space(
                space_id=space_id,
                tenant_id=self.user.tenant_id,
                limit=limit,
                offset=offset,
            )
        return await self.flow_repo.get_by_space(
            space_id=space_id,
            tenant_id=self.user.tenant_id,
            limit=limit,
            offset=offset,
        )

    async def update_flow(
        self,
        *,
        flow_id: UUID,
        name: str | NotProvided = NOT_PROVIDED,
        description: str | None | NotProvided = NOT_PROVIDED,
        steps: list[FlowStep] | None = None,
        metadata_json: JsonObject | None | NotProvided = NOT_PROVIDED,
        data_retention_days: int | None | NotProvided = NOT_PROVIDED,
    ) -> Flow:
        existing = await self.get_flow(flow_id)
        if existing.published_version is not None:
            raise BadRequestException("Cannot mutate a published flow. Unpublish first.")

        next_steps = steps if steps is not None else existing.steps
        self._validate_steps(next_steps)
        await self._validate_assistant_scope_for_steps(
            space_id=existing.space_id,
            steps=next_steps,
            owning_flow_id=existing.id,
        )

        next_metadata = self._normalize_legacy_form_schema(existing.metadata_json)
        if metadata_json is not NOT_PROVIDED:
            next_metadata = self._normalize_legacy_form_schema(cast(JsonObject | None, metadata_json))
        self._validate_form_schema(next_metadata)
        self._validate_variable_alias_collisions(
            steps=next_steps,
            metadata_json=next_metadata,
        )

        next_retention = existing.data_retention_days
        if data_retention_days is not NOT_PROVIDED:
            next_retention = data_retention_days

        normalized_steps = self._normalize_steps_for_tenant(next_steps)
        persisted_steps = self._prepare_steps_for_persist(normalized_steps)
        updated = existing.model_copy(
            deep=True,
            update={
                "name": existing.name if name is NOT_PROVIDED else name,
                "description": (
                    existing.description
                    if description is NOT_PROVIDED
                    else description
                ),
                "steps": persisted_steps,
                "metadata_json": next_metadata,
                "data_retention_days": next_retention,
            },
        )
        return await self.flow_repo.update(flow=updated, tenant_id=self.user.tenant_id)

    async def delete_flow(self, flow_id: UUID) -> None:
        await self.flow_repo.delete(flow_id=flow_id, tenant_id=self.user.tenant_id)

    async def create_flow_assistant(
        self,
        *,
        flow_id: UUID,
        name: str,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        flow = await self.get_flow(flow_id)
        self._ensure_flow_is_mutable(flow)
        return await self.assistant_service.create_assistant(
            name=name,
            space_id=flow.space_id,
            hidden=True,
            origin=AssistantOrigin.FLOW_MANAGED,
            managing_flow_id=flow.id,
        )

    async def get_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        flow = await self.get_flow(flow_id)
        assistant, permissions = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        return assistant, permissions

    async def update_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
        **changes: Any,
    ) -> tuple[Assistant, list[ResourcePermission]]:
        flow = await self.get_flow(flow_id)
        self._ensure_flow_is_mutable(flow)
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        return await self.assistant_service.update_assistant(
            assistant_id=assistant_id,
            include_hidden=True,
            **changes,
        )

    async def delete_flow_assistant(
        self,
        *,
        flow_id: UUID,
        assistant_id: UUID,
    ) -> None:
        flow = await self.get_flow(flow_id)
        self._ensure_flow_is_mutable(flow)
        assistant, _ = await self.assistant_service.get_assistant(assistant_id)
        self._assert_flow_assistant_owned_by_flow(flow=flow, assistant=assistant)
        await self.assistant_service.delete_assistant(assistant_id)

    async def unpublish_flow(self, *, flow_id: UUID) -> Flow:
        flow = await self.get_flow(flow_id)
        if flow.published_version is None:
            raise BadRequestException("Flow is not published.")
        updated = flow.model_copy(update={"published_version": None}, deep=True)
        return await self.flow_repo.update(updated, tenant_id=self.user.tenant_id)

    async def publish_flow(self, *, flow_id: UUID) -> Flow:
        flow = await self.get_flow(flow_id)
        normalized_metadata = self._normalize_legacy_form_schema(flow.metadata_json)
        self._validate_form_schema(normalized_metadata)
        self._validate_publishable(flow)
        self._validate_variable_alias_collisions(
            steps=flow.steps,
            metadata_json=normalized_metadata,
        )
        await self._validate_assistant_scope_for_steps(
            space_id=flow.space_id,
            steps=flow.steps,
            owning_flow_id=flow.id,
        )

        latest = await self.flow_version_repo.get_latest(
            flow_id=flow_id,
            tenant_id=self.user.tenant_id,
        )
        next_version = 1 if latest is None else latest.version + 1

        definition = self._build_definition(flow)
        checksum = self._definition_checksum(definition)
        await self.flow_version_repo.create(
            flow_id=flow_id,
            version=next_version,
            definition_checksum=checksum,
            definition_json=definition,
            tenant_id=self.user.tenant_id,
        )

        updated = flow.model_copy(
            update={
                "published_version": next_version,
                "metadata_json": normalized_metadata,
            },
            deep=True,
        )
        return await self.flow_repo.update(updated, tenant_id=self.user.tenant_id)

    def _validate_publishable(self, flow: Flow) -> None:
        self._validate_steps(flow.steps)
        if not flow.steps:
            raise BadRequestException("Flow must contain at least one step before publish.")

    def _validate_steps(self, steps: list[FlowStep]) -> None:
        if not steps:
            return

        sorted_steps = sorted(steps, key=lambda item: item.step_order)
        step_orders = [step.step_order for step in sorted_steps]
        if len(step_orders) != len(set(step_orders)):
            raise BadRequestException("Duplicate step_order detected.")

        expected_orders = list(range(1, len(sorted_steps) + 1))
        if step_orders != expected_orders:
            raise BadRequestException(
                "Step order must be contiguous and start at 1."
            )

        normalized_names: set[str] = set()
        for step in sorted_steps:
            if step.user_description is None:
                continue
            normalized_name = step.user_description.strip().casefold()
            if not normalized_name:
                continue
            if normalized_name in normalized_names:
                raise BadRequestException(
                    "Step names must be unique (case-insensitive) for publishable flows."
                )
            normalized_names.add(normalized_name)

        chain_violation = find_first_step_chain_violation(sorted_steps)
        if chain_violation is not None:
            raise BadRequestException(chain_violation.message)

        seen: set[int] = set()
        for step in sorted_steps:
            seen.add(step.step_order)
            if step.input_source in ("http_get", "http_post"):
                self._validate_http_input_config(step=step)
            if step.output_mode == "http_post":
                self._validate_http_output_config(step=step)
            # Typed I/O publish-time validation
            input_policy = INPUT_TYPE_POLICIES.get(step.input_type)
            if input_policy and not input_policy.supported:
                raise BadRequestException(
                    f"Step {step.step_order}: {step.input_type} is not yet supported."
                )
            if step.input_contract and input_policy and not input_policy.contract_allowed:
                raise BadRequestException(
                    f"Step {step.step_order}: input_contract is not supported for "
                    f"input_type '{step.input_type}'."
                )
            # Schema syntax validation for contracts
            if step.input_contract:
                try:
                    validate_schema_syntax(step.input_contract, label=f"Step {step.step_order} input_contract")
                except TypedIOValidationException as exc:
                    raise BadRequestException(str(exc)) from exc
            if step.output_contract:
                try:
                    validate_schema_syntax(step.output_contract, label=f"Step {step.step_order} output_contract")
                except TypedIOValidationException as exc:
                    raise BadRequestException(str(exc)) from exc

            if step.input_bindings is not None:
                self._validate_binding_references(
                    input_bindings=step.input_bindings,
                    current_step_order=step.step_order,
                    available_orders=seen,
                )

    def _validate_binding_references(
        self,
        *,
        input_bindings: JsonObject,
        current_step_order: int,
        available_orders: set[int],
    ) -> None:
        binding_payload = json.dumps(input_bindings)
        for expression in iter_template_expressions(binding_payload):
            if not expression.startswith("step_"):
                continue

            head = expression.split(".", maxsplit=1)[0]
            step_ref = _STEP_REFERENCE_PATTERN.match(head)
            if step_ref is None:
                raise BadRequestException(
                    f"Invalid step reference '{head}' in input bindings."
                )

            referenced_order = int(step_ref.group(1))
            if referenced_order >= current_step_order:
                raise BadRequestException(
                    "Input bindings may only reference outputs from earlier steps."
                )
            if referenced_order not in available_orders:
                raise BadRequestException(
                    f"Input binding references unknown step order: {referenced_order}."
                )

    def _validate_http_input_config(self, *, step: FlowStep) -> None:
        if step.input_type in {"document", "file", "image", "audio"}:
            raise BadRequestException(
                f"Step {step.step_order}: input_type '{step.input_type}' is not supported with input_source '{step.input_source}'."
            )
        self._validate_http_config_common(
            step_order=step.step_order,
            label="input_config",
            config=step.input_config,
            method=step.input_source,
        )
        if isinstance(step.input_config, dict) and step.input_source == "http_get":
            if "body_template" in step.input_config or "body_json" in step.input_config:
                raise BadRequestException(
                    f"Step {step.step_order}: input_config body fields are only allowed for input_source 'http_post'."
                )

    def _validate_http_output_config(self, *, step: FlowStep) -> None:
        self._validate_http_config_common(
            step_order=step.step_order,
            label="output_config",
            config=step.output_config,
            method="http_post",
        )

    @staticmethod
    def _validate_http_config_common(
        *,
        step_order: int,
        label: str,
        config: JsonObject | None,
        method: str,
    ) -> None:
        if not isinstance(config, dict):
            raise BadRequestException(
                f"Step {step_order}: {label} must be an object when using HTTP {method}."
            )
        url_value = config.get("url")
        if not isinstance(url_value, str) or not url_value.strip():
            raise BadRequestException(
                f"Step {step_order}: {label}.url is required for HTTP {method}."
            )
        headers = config.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise BadRequestException(
                f"Step {step_order}: {label}.headers must be an object."
            )
        timeout_value = config.get("timeout_seconds")
        if timeout_value is not None:
            if not isinstance(timeout_value, (int, float)):
                raise BadRequestException(
                    f"Step {step_order}: {label}.timeout_seconds must be a number."
                )
            if timeout_value <= 0:
                raise BadRequestException(
                    f"Step {step_order}: {label}.timeout_seconds must be greater than zero."
                )
            max_timeout = float(get_settings().flow_http_max_timeout_seconds)
            if float(timeout_value) > max_timeout:
                raise BadRequestException(
                    f"Step {step_order}: {label}.timeout_seconds cannot exceed {max_timeout:g}."
                )
        response_format = config.get("response_format")
        if response_format is not None and str(response_format) not in {"text", "json"}:
            raise BadRequestException(
                f"Step {step_order}: {label}.response_format must be 'text' or 'json'."
            )
        body_template = config.get("body_template")
        if body_template is not None and not isinstance(body_template, str):
            raise BadRequestException(
                f"Step {step_order}: {label}.body_template must be a string."
            )
        body_json = config.get("body_json")
        if body_json is not None and not isinstance(body_json, (dict, list)):
            raise BadRequestException(
                f"Step {step_order}: {label}.body_json must be an object or array."
            )
        if body_template is not None and body_json is not None:
            raise BadRequestException(
                f"Step {step_order}: {label} cannot define both body_template and body_json."
            )

    def _validate_form_schema(self, metadata_json: JsonObject | None) -> None:
        if metadata_json is None:
            return

        form_schema = metadata_json.get("form_schema")
        if form_schema is None:
            return
        if not isinstance(form_schema, dict):
            raise BadRequestException("metadata_json.form_schema must be an object.")
        form_schema_dict = cast(dict[str, Any], form_schema)

        fields = form_schema_dict.get("fields")
        if not isinstance(fields, list):
            raise BadRequestException("metadata_json.form_schema.fields must be a list.")

        seen_names: set[str] = set()
        seen_orders: set[int] = set()
        for index, field in enumerate(cast(list[object], fields)):
            if not isinstance(field, dict):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}] must be an object."
                )
            field_dict = cast(dict[str, Any], field)
            field_name = field_dict.get("name")
            if not isinstance(field_name, str) or not field_name.strip():
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name must be a non-empty string."
                )
            normalized_name = field_name.strip().casefold()
            if normalized_name in seen_names:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name must be unique."
                )
            if "." in field_name:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name cannot contain '.'."
                )
            if "{{" in field_name or "}}" in field_name:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name cannot contain template delimiters."
                )
            if normalized_name in _RESERVED_VARIABLE_ALIASES_NORMALIZED:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name uses a reserved variable alias."
                )
            if _STEP_ALIAS_PATTERN.match(normalized_name):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name cannot use reserved step alias format."
                )
            seen_names.add(normalized_name)
            field_type = field_dict.get("type")
            if not isinstance(field_type, str) or not field_type.strip():
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].type must be a non-empty string."
                )
            normalized_type = field_type.strip().casefold()
            if normalized_type not in _ALLOWED_FORM_FIELD_TYPES:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].type must be one of "
                    f"{sorted(_ALLOWED_FORM_FIELD_TYPES)}."
                )
            if "required" in field_dict and not isinstance(field_dict["required"], bool):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].required must be a boolean."
                )
            if "order" in field_dict:
                if not isinstance(field_dict["order"], int):
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].order must be an integer."
                    )
                order_value = field_dict["order"]
                if order_value < 1:
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].order must be >= 1."
                    )
                if order_value in seen_orders:
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].order must be unique."
                    )
                seen_orders.add(order_value)
            options = field_dict.get("options")
            if normalized_type == "multiselect":
                if options is None or not isinstance(options, list):
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].options must be a list for multiselect."
                    )
                normalized_options: set[str] = set()
                for option_index, option in enumerate(cast(list[object], options)):
                    if not isinstance(option, str) or not option.strip():
                        raise BadRequestException(
                            f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                            "must be a non-empty string."
                        )
                    option_key = option.strip().casefold()
                    if option_key in normalized_options:
                        raise BadRequestException(
                            f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                            "must be unique."
                        )
                    normalized_options.add(option_key)
            elif normalized_type == "select":
                if options is not None and not isinstance(options, list):
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].options must be a list for select."
                    )
                if isinstance(options, list):
                    normalized_options: set[str] = set()
                    for option_index, option in enumerate(cast(list[object], options)):
                        if not isinstance(option, str) or not option.strip():
                            raise BadRequestException(
                                f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                                "must be a non-empty string."
                            )
                        option_key = option.strip().casefold()
                        if option_key in normalized_options:
                            raise BadRequestException(
                                f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                                "must be unique."
                            )
                        normalized_options.add(option_key)
            elif options is not None:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].options is only valid for multiselect."
                )

    def _normalize_legacy_form_schema(self, metadata_json: JsonObject | None) -> JsonObject | None:
        if metadata_json is None:
            return None
        form_schema = metadata_json.get("form_schema")
        if not isinstance(form_schema, dict):
            return metadata_json
        fields = form_schema.get("fields")
        if not isinstance(fields, list):
            return metadata_json

        changed = False
        normalized_fields: list[object] = []
        for field in fields:
            if not isinstance(field, dict):
                normalized_fields.append(field)
                continue
            field_dict = cast(dict[str, Any], field)
            normalized_field = dict(field_dict)
            raw_type = normalized_field.get("type")
            if isinstance(raw_type, str):
                legacy_target = _LEGACY_FORM_FIELD_TYPE_NORMALIZATION.get(raw_type.strip().casefold())
                if legacy_target is not None and legacy_target != raw_type:
                    normalized_field["type"] = legacy_target
                    changed = True
            normalized_fields.append(normalized_field)

        if not changed:
            return metadata_json

        normalized_form_schema = dict(form_schema)
        normalized_form_schema["fields"] = normalized_fields
        normalized_metadata = dict(metadata_json)
        normalized_metadata["form_schema"] = normalized_form_schema
        return cast(JsonObject, normalized_metadata)

    def _validate_variable_alias_collisions(
        self,
        *,
        steps: list[FlowStep],
        metadata_json: JsonObject | None,
    ) -> None:
        normalized_reserved = _RESERVED_VARIABLE_ALIASES_NORMALIZED
        field_names: dict[str, str] = {}

        form_schema = metadata_json.get("form_schema") if metadata_json else None
        fields = form_schema.get("fields") if isinstance(form_schema, dict) else None
        if isinstance(fields, list):
            for index, field in enumerate(fields):
                if not isinstance(field, dict):
                    continue
                raw_name = field.get("name")
                if not isinstance(raw_name, str):
                    continue
                normalized = raw_name.strip().casefold()
                if not normalized:
                    continue
                if normalized in normalized_reserved:
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].name is reserved."
                    )
                if _STEP_ALIAS_PATTERN.match(normalized):
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].name conflicts with reserved step alias namespace."
                    )
                field_names[normalized] = raw_name.strip()

        for step in steps:
            raw_name = step.user_description
            if raw_name is None:
                continue
            normalized = raw_name.strip().casefold()
            if not normalized:
                continue
            if normalized in normalized_reserved:
                raise BadRequestException(
                    f"Step {step.step_order} name '{raw_name}' uses a reserved variable alias."
                )
            if _STEP_ALIAS_PATTERN.match(normalized):
                raise BadRequestException(
                    f"Step {step.step_order} name '{raw_name}' conflicts with reserved step alias namespace."
                )
            if normalized in field_names:
                raise BadRequestException(
                    f"Step {step.step_order} name '{raw_name}' conflicts with form field name '{field_names[normalized]}'."
                )

    async def _validate_assistant_scope_for_steps(
        self,
        *,
        space_id: UUID,
        steps: list[FlowStep],
        owning_flow_id: UUID | None = None,
    ) -> None:
        assistant_ids = {step.assistant_id for step in steps}
        if not assistant_ids:
            return

        rows = await self.flow_repo.session.execute(
            sa.select(Assistants.id, Assistants.origin, Assistants.managing_flow_id)
            .join(Spaces, Spaces.id == Assistants.space_id)
            .where(Assistants.id.in_(assistant_ids))
            .where(Assistants.space_id == space_id)
            .where(Spaces.tenant_id == self.user.tenant_id)
        )
        assistant_rows = rows.all()
        allowed_ids = {row.id for row in assistant_rows}
        missing = assistant_ids - allowed_ids
        if missing:
            raise BadRequestException(
                "One or more steps reference assistants outside the selected space or tenant."
            )

        if owning_flow_id is None:
            return

        non_owned = [
            row.id
            for row in assistant_rows
            if row.origin != AssistantOrigin.FLOW_MANAGED.value
            or row.managing_flow_id != owning_flow_id
        ]
        if non_owned:
            raise BadRequestException(
                "Flow steps must reference flow-managed assistants owned by the flow."
            )

    def _normalize_steps_for_tenant(self, steps: list[FlowStep]) -> list[FlowStep]:
        return [
            step.model_copy(
                update={
                    "flow_id": step.flow_id,
                    "tenant_id": self.user.tenant_id,
                },
                deep=True,
            )
            for step in steps
        ]

    def _prepare_steps_for_persist(self, steps: list[FlowStep]) -> list[FlowStep]:
        return [
            step.model_copy(
                update={
                    "input_config": encrypt_step_headers_for_storage(
                        config=step.input_config,
                        encryption_service=self.encryption_service,
                    ),
                    "output_config": encrypt_step_headers_for_storage(
                        config=step.output_config,
                        encryption_service=self.encryption_service,
                    ),
                },
                deep=True,
            )
            for step in steps
        ]

    def _build_definition(self, flow: Flow) -> JsonObject:
        return {
            "flow_id": str(flow.id),
            "name": flow.name,
            "description": flow.description,
            "metadata_json": flow.metadata_json,
            "steps": [
                self._step_to_definition(step)
                for step in sorted(flow.steps, key=lambda item: item.step_order)
            ],
        }

    def _step_to_definition(self, step: FlowStep) -> JsonObject:
        return {
            "step_id": str(step.id) if step.id is not None else None,
            "step_order": step.step_order,
            "assistant_id": str(step.assistant_id),
            "user_description": step.user_description,
            "input_source": step.input_source,
            "input_type": step.input_type,
            "input_contract": step.input_contract,
            "output_mode": step.output_mode,
            "output_type": step.output_type,
            "output_contract": step.output_contract,
            "input_bindings": step.input_bindings,
            "output_classification_override": step.output_classification_override,
            "mcp_policy": step.mcp_policy,
            "input_config": step.input_config,
            "output_config": step.output_config,
        }

    def _ensure_flow_is_mutable(self, flow: Flow) -> None:
        if flow.published_version is not None:
            raise BadRequestException("Cannot mutate assistant of a published flow")

    def _assert_flow_assistant_owned_by_flow(self, *, flow: Flow, assistant: Assistant) -> None:
        if assistant.origin != AssistantOrigin.FLOW_MANAGED:
            raise NotFoundException("Assistant is not flow-managed.")
        if assistant.managing_flow_id != flow.id:
            raise NotFoundException("Assistant belongs to a different flow.")

    def _definition_checksum(self, definition: JsonObject) -> str:
        serialized = json.dumps(
            definition,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
