from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import re
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.tenant_table import Tenants
from intric.flows.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowStepResult,
    FlowVersion,
    JsonObject,
)
from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_run_repo import FlowRunRepository, PreseedStep
from intric.flows.flow_version_repo import FlowVersionRepository
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.users.user import UserInDB

_REDACTED_VALUE = "[REDACTED]"
_DEBUG_EXPORT_SCHEMA_VERSION = "eneo.flow.debug-export.v1"
_SENSITIVE_FIELD_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "session",
    "credential",
    "bearer",
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-~+/]+=*")
logger = get_logger(__name__)
_RUN_FIELD_TYPE_LEGACY_NORMALIZATION = {
    "string": "text",
    "email": "text",
    "textarea": "text",
}


def _is_sensitive_key(key: str | None) -> bool:
    if key is None:
        return False
    key_lower = key.lower().replace("-", "_").replace(".", "_")
    return any(fragment in key_lower for fragment in _SENSITIVE_FIELD_FRAGMENTS)


def _redact_url_secrets(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{host}{port}"

    if not parse_qsl(parsed.query, keep_blank_values=True):
        if parsed.username is None and parsed.password is None:
            return value
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    redacted_query = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_sensitive_key(key):
            redacted_query.append((key, _REDACTED_VALUE))
        else:
            redacted_query.append((key, item_value))

    return urlunsplit(
        (
            parsed.scheme,
            netloc if parsed.username or parsed.password else parsed.netloc,
            parsed.path,
            urlencode(redacted_query, doseq=True),
            parsed.fragment,
        )
    )


def _redact_string(value: str, *, key: str | None) -> str:
    if _is_sensitive_key(key):
        return _REDACTED_VALUE
    if "://" in value:
        value = _redact_url_secrets(value)
    return _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", value)


def _redact_payload(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {item_key: _redact_payload(item_value, key=item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item, key=key) for item in value]
    if isinstance(value, str):
        return _redact_string(value, key=key)
    return value


class FlowRunService:
    """Tenant-scoped flow run lifecycle service."""

    _TERMINAL_STATUSES = {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }

    def __init__(
        self,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        flow_version_repo: FlowVersionRepository,
        execution_backend: FlowExecutionBackend | None = None,
        max_concurrent_runs: int | None = None,
        queued_redispatch_after_seconds: int | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_version_repo = flow_version_repo
        self.execution_backend = execution_backend
        self.max_concurrent_runs = (
            max_concurrent_runs
            if max_concurrent_runs is not None
            else get_settings().flow_max_concurrent_runs_per_tenant
        )
        self.queued_redispatch_after_seconds = (
            queued_redispatch_after_seconds
            if queued_redispatch_after_seconds is not None
            else 30
        )

    async def create_run(
        self,
        *,
        flow_id: UUID,
        input_payload_json: dict[str, Any] | None,
        file_ids: list[UUID] | None = None,
    ) -> FlowRun:
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=self.user.tenant_id)
        if flow.published_version is None:
            raise BadRequestException("Flow must be published before a run can be created.")

        if file_ids:
            effective_payload = dict(input_payload_json or {})
            effective_payload["file_ids"] = [str(fid) for fid in file_ids]
            input_payload_json = effective_payload

        input_payload_json = self._normalize_and_validate_run_input_payload(
            flow=flow,
            payload=input_payload_json,
        )

        if input_payload_json is not None:
            payload_size = len(
                json.dumps(
                    input_payload_json,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if payload_size > get_settings().flow_max_inline_text_bytes:
                raise BadRequestException("Flow run input payload exceeds allowed size limit.")

        # Serialize run creation per tenant to prevent concurrency-limit race conditions.
        await self.flow_repo.session.execute(
            sa.select(Tenants.id)
            .where(Tenants.id == self.user.tenant_id)
            .with_for_update()
        )
        active_runs = await self.flow_run_repo.count_active_runs(tenant_id=self.user.tenant_id)
        if active_runs >= self.max_concurrent_runs:
            raise BadRequestException(
                "Concurrent flow run limit reached for this tenant."
            )
        if flow.id is None:
            raise BadRequestException("Flow id missing for run creation.")
        version = await self.flow_version_repo.get(
            flow_id=flow.id,
            version=flow.published_version,
            tenant_id=self.user.tenant_id,
        )

        created = await self.flow_run_repo.create(
            flow_id=flow.id,
            flow_version=flow.published_version,
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            input_payload_json=input_payload_json,
            preseed_steps=self._build_preseed_steps(
                definition_json=version.definition_json,
                fallback_steps=flow.steps,
            ),
        )
        if self.execution_backend is None:
            return created

        try:
            await self.execution_backend.dispatch(
                run_id=created.id,
                flow_id=flow.id,
                tenant_id=self.user.tenant_id,
                user_id=self.user.id,
            )
        except Exception:
            # If dispatch fails here, request-level transaction handling decides
            # whether run creation is committed or rolled back as one unit.
            raise
        return created

    def _normalize_and_validate_run_input_payload(
        self,
        *,
        flow: Flow,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        metadata = flow.metadata_json if isinstance(flow.metadata_json, dict) else None
        form_schema = metadata.get("form_schema") if metadata else None
        fields = form_schema.get("fields") if isinstance(form_schema, dict) else None
        if not isinstance(fields, list) or len(fields) == 0:
            return payload

        normalized_payload = dict(payload or {})

        ordered_fields: list[dict[str, Any]] = []
        for index, raw in enumerate(fields):
            if not isinstance(raw, dict):
                continue
            field = cast(dict[str, Any], raw)
            order = field.get("order")
            if not isinstance(order, int):
                order = index + 1
            ordered_fields.append({"index": index, "order": order, "field": field})
        ordered_fields.sort(key=lambda item: (item["order"], item["index"]))

        for item in ordered_fields:
            index = cast(int, item["index"])
            field = cast(dict[str, Any], item["field"])
            field_name = field.get("name")
            if not isinstance(field_name, str) or not field_name.strip():
                continue
            key = field_name.strip()
            required = bool(field.get("required"))
            raw_type = field.get("type")
            field_type = (
                raw_type.strip().casefold()
                if isinstance(raw_type, str) and raw_type.strip()
                else "text"
            )
            field_type = _RUN_FIELD_TYPE_LEGACY_NORMALIZATION.get(field_type, field_type)
            options_raw = field.get("options")
            options = (
                [option.strip() for option in options_raw if isinstance(option, str) and option.strip()]
                if isinstance(options_raw, list)
                else []
            )

            if key not in normalized_payload:
                if required:
                    raise BadRequestException(f"Missing required input field '{key}'.")
                continue

            value = normalized_payload.get(key)
            if value is None:
                if required:
                    raise BadRequestException(f"Missing required input field '{key}'.")
                continue

            if field_type == "number":
                normalized_payload[key] = self._coerce_number_field(
                    field_name=key,
                    value=value,
                    required=required,
                )
                continue

            if field_type == "date":
                normalized_payload[key] = self._coerce_date_field(
                    field_name=key,
                    value=value,
                    required=required,
                )
                continue

            if field_type == "select":
                normalized_payload[key] = self._coerce_select_field(
                    field_name=key,
                    value=value,
                    options=options,
                    required=required,
                )
                continue

            if field_type == "multiselect":
                normalized_payload[key] = self._coerce_multiselect_field(
                    field_name=key,
                    value=value,
                    options=options,
                    required=required,
                )
                continue

            normalized_payload[key] = self._coerce_text_field(
                field_name=key,
                value=value,
                required=required,
            )

        return normalized_payload

    @staticmethod
    def _coerce_text_field(*, field_name: str, value: Any, required: bool) -> str:
        if isinstance(value, str):
            text_value = value
        elif isinstance(value, (int, float, bool)):
            text_value = str(value)
        else:
            raise BadRequestException(f"Field '{field_name}' must be a string.")
        if required and text_value.strip() == "":
            raise BadRequestException(f"Field '{field_name}' cannot be empty.")
        return text_value

    @staticmethod
    def _coerce_number_field(*, field_name: str, value: Any, required: bool) -> int | float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number_value: int | float = value
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                if required:
                    raise BadRequestException(f"Field '{field_name}' cannot be empty.")
                return None
            try:
                number_value = float(stripped) if "." in stripped else int(stripped)
            except ValueError as exc:
                raise BadRequestException(f"Field '{field_name}' must be a valid number.") from exc
        else:
            raise BadRequestException(f"Field '{field_name}' must be a valid number.")
        return number_value

    @staticmethod
    def _coerce_date_field(*, field_name: str, value: Any, required: bool) -> str | None:
        if isinstance(value, date):
            date_value = value.isoformat()
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                if required:
                    raise BadRequestException(f"Field '{field_name}' cannot be empty.")
                return None
            try:
                date.fromisoformat(stripped)
            except ValueError as exc:
                raise BadRequestException(
                    f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD)."
                ) from exc
            date_value = stripped
        else:
            raise BadRequestException(f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).")
        return date_value

    @staticmethod
    def _coerce_select_field(
        *,
        field_name: str,
        value: Any,
        options: list[str],
        required: bool,
    ) -> str | None:
        if not isinstance(value, str):
            raise BadRequestException(f"Field '{field_name}' must be a string.")
        selected = value.strip()
        if selected == "":
            if required:
                raise BadRequestException(f"Field '{field_name}' cannot be empty.")
            return None
        if options and selected not in options:
            raise BadRequestException(
                f"Field '{field_name}' must be one of the configured options."
            )
        return selected

    @staticmethod
    def _coerce_multiselect_field(
        *,
        field_name: str,
        value: Any,
        options: list[str],
        required: bool,
    ) -> list[str]:
        raw_values: list[str]
        if isinstance(value, list):
            raw_values = []
            for item in value:
                if not isinstance(item, str):
                    raise BadRequestException(
                        f"Field '{field_name}' must contain only string options."
                    )
                stripped_item = item.strip()
                if stripped_item:
                    raw_values.append(stripped_item)
        elif isinstance(value, str):
            raw_values = [item.strip() for item in value.split(",") if item.strip()]
        else:
            raise BadRequestException(f"Field '{field_name}' must be an array of strings.")

        if required and len(raw_values) == 0:
            raise BadRequestException(f"Field '{field_name}' must contain at least one value.")
        if options:
            invalid = [item for item in raw_values if item not in options]
            if invalid:
                raise BadRequestException(
                    f"Field '{field_name}' contains invalid option values."
                )
        return raw_values

    async def get_run(self, *, run_id: UUID, flow_id: UUID | None = None) -> FlowRun:
        return await self.flow_run_repo.get(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )

    async def list_runs(
        self,
        *,
        flow_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRun]:
        return await self.flow_run_repo.list_runs(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            limit=limit,
            offset=offset,
        )

    async def redispatch_stale_queued_runs(
        self,
        *,
        flow_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 25,
        execution_backend: FlowExecutionBackend | None = None,
    ) -> int:
        backend = execution_backend or self.execution_backend
        if backend is None:
            return 0

        stale_before = datetime.now(timezone.utc) - timedelta(
            seconds=max(1, self.queued_redispatch_after_seconds)
        )
        stale_runs = await self.flow_run_repo.list_stale_queued_runs(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            run_id=run_id,
            stale_before=stale_before,
            limit=limit,
        )
        redispatched = 0
        for run in stale_runs:
            claimed_run = await self.flow_run_repo.claim_stale_queued_run_for_redispatch(
                run_id=run.id,
                tenant_id=self.user.tenant_id,
                stale_before=stale_before,
                flow_id=flow_id,
            )
            if claimed_run is None or claimed_run.user_id is None:
                continue
            try:
                await backend.dispatch(
                    run_id=claimed_run.id,
                    flow_id=claimed_run.flow_id,
                    tenant_id=claimed_run.tenant_id,
                    user_id=claimed_run.user_id,
                )
                redispatched += 1
            except Exception:
                logger.exception(
                    "Failed to redispatch stale queued flow run",
                    extra={
                        "run_id": str(claimed_run.id),
                        "flow_id": str(claimed_run.flow_id),
                        "tenant_id": str(claimed_run.tenant_id),
                    },
                )
                if run_id is not None:
                    raise
        return redispatched

    async def cancel_run(self, *, run_id: UUID) -> FlowRun:
        run = await self.get_run(run_id=run_id)
        if run.status in self._TERMINAL_STATUSES:
            return run
        await self.flow_run_repo.mark_pending_steps_cancelled(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            error_message="Run cancelled by user.",
        )
        return await self.flow_run_repo.cancel(run_id=run_id, tenant_id=self.user.tenant_id)

    async def complete_run(
        self,
        *,
        run_id: UUID,
        output_payload_json: dict[str, Any] | None = None,
    ) -> FlowRun:
        return await self.flow_run_repo.update_status(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            status=FlowRunStatus.COMPLETED,
            output_payload_json=output_payload_json,
        )

    async def fail_run(self, *, run_id: UUID, error_message: str) -> FlowRun:
        return await self.flow_run_repo.update_status(
            run_id=run_id,
            tenant_id=self.user.tenant_id,
            status=FlowRunStatus.FAILED,
            error_message=error_message,
        )

    async def get_evidence(self, *, run_id: UUID) -> dict[str, Any]:
        run = await self.get_run(run_id=run_id)
        version = await self.flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=self.user.tenant_id,
        )
        step_results = await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        step_attempts = await self.flow_run_repo.list_step_attempts(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
        )
        debug_export = self._build_debug_export(
            run=run,
            version=version,
            step_results=step_results,
        )
        return {
            "run": cast(dict[str, Any], _redact_payload(run.model_dump(mode="json"))),
            "definition_snapshot": cast(dict[str, Any], _redact_payload(version.definition_json)),
            "step_results": [
                cast(dict[str, Any], _redact_payload(item.model_dump(mode="json")))
                for item in step_results
            ],
            "step_attempts": [
                cast(dict[str, Any], _redact_payload(item.model_dump(mode="json")))
                for item in step_attempts
            ],
            "debug_export": cast(dict[str, Any], _redact_payload(debug_export)),
        }

    def _build_debug_export(
        self,
        *,
        run: FlowRun,
        version: FlowVersion,
        step_results: list[FlowStepResult] | None = None,
    ) -> dict[str, Any]:
        definition_snapshot = (
            version.definition_json
            if isinstance(version.definition_json, dict)
            else {}
        )
        rag_by_step_order: dict[int, dict[str, Any]] = {}
        for result in step_results or []:
            input_payload = getattr(result, "input_payload_json", None)
            step_order = getattr(result, "step_order", None)
            if not isinstance(input_payload, dict):
                model_dump = getattr(result, "model_dump", None)
                if callable(model_dump):
                    dumped = model_dump(mode="json")
                    if isinstance(dumped, dict):
                        if step_order is None:
                            step_order = dumped.get("step_order")
                        input_payload = dumped.get("input_payload_json")
            if not isinstance(input_payload, dict):
                continue
            rag_metadata = input_payload.get("rag")
            if not isinstance(rag_metadata, dict):
                continue
            try:
                rag_by_step_order[int(step_order)] = rag_metadata
            except (TypeError, ValueError):
                continue

        raw_steps = definition_snapshot.get("steps")
        normalized_steps = []
        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                if isinstance(raw_step, dict):
                    try:
                        step_order = int(raw_step.get("step_order", 0))
                    except (TypeError, ValueError):
                        step_order = 0
                    normalized_steps.append(
                        self._normalize_debug_step(
                            raw_step,
                            rag_metadata=rag_by_step_order.get(step_order),
                        )
                    )

        return {
            "schema_version": _DEBUG_EXPORT_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "flow_version": run.flow_version,
                "status": run.status.value,
            },
            "definition": {
                "flow_id": str(version.flow_id),
                "version": version.version,
                "checksum": version.definition_checksum,
                "steps_count": len(normalized_steps),
            },
            "definition_snapshot": definition_snapshot,
            "steps": normalized_steps,
            "security": {
                "redaction_applied": True,
                "classification_field": "output_classification_override",
                "mcp_policy_field": "mcp_policy",
            },
        }

    @staticmethod
    def _normalize_debug_step(
        step: dict[str, Any],
        *,
        rag_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_allowlist = step.get("mcp_tool_allowlist")
        tool_allowlist = raw_allowlist if isinstance(raw_allowlist, list) else []
        input_type = step.get("input_type")
        output_type = step.get("output_type")
        return {
            "step_id": step.get("step_id"),
            "step_order": step.get("step_order"),
            "assistant_id": step.get("assistant_id"),
            "io_types": {
                "input": input_type,
                "output": output_type,
            },
            "input": {
                "source": step.get("input_source"),
                "type": input_type,
                "contract": step.get("input_contract"),
                "bindings": step.get("input_bindings"),
                "config": step.get("input_config"),
            },
            "output": {
                "mode": step.get("output_mode"),
                "type": output_type,
                "contract": step.get("output_contract"),
                "classification": step.get("output_classification_override"),
                "config": step.get("output_config"),
            },
            "mcp": {
                "policy": step.get("mcp_policy"),
                "tool_allowlist": tool_allowlist,
            },
            "rag": rag_metadata if isinstance(rag_metadata, dict) else None,
        }

    def _build_preseed_steps(
        self,
        *,
        definition_json: JsonObject,
        fallback_steps: list[FlowStep],
    ) -> list[PreseedStep]:
        raw_steps = definition_json.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise BadRequestException("Published flow version does not contain executable steps.")

        by_step_order: dict[int, FlowStep] = {}
        for step in fallback_steps:
            if getattr(step, "id", None) is None:
                continue
            by_step_order[int(step.step_order)] = step

        preseed: list[PreseedStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                raise BadRequestException("Invalid flow version step definition.")
            step_order = int(raw_step.get("step_order", 0))
            if step_order <= 0:
                raise BadRequestException("Invalid flow version step order.")

            step_id_raw = raw_step.get("step_id")
            assistant_id_raw = raw_step.get("assistant_id")
            if step_id_raw is None or assistant_id_raw is None:
                fallback = by_step_order.get(step_order)
                if fallback is None:
                    raise BadRequestException(
                        f"Flow version step {step_order} is missing stable step identifiers."
                    )
                step_id_raw = fallback.id
                assistant_id_raw = fallback.assistant_id

            preseed.append(
                {
                    "step_id": UUID(str(step_id_raw)),
                    "assistant_id": UUID(str(assistant_id_raw)),
                    "step_order": step_order,
                }
            )
        return preseed
