from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.tenant_table import Tenants
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowStepResult,
    FlowVersion,
    JsonObject,
)
from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
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
            raise BadRequestException(
                "Flow must be published before a run can be created.",
                code="flow_not_published",
                context={"flow_id": str(flow_id)},
            )

        if file_ids:
            effective_payload = dict(input_payload_json or {})
            effective_payload["file_ids"] = [str(fid) for fid in file_ids]
            input_payload_json = effective_payload

        input_payload_json = normalize_and_validate_flow_run_payload(
            metadata_json=flow.metadata_json if isinstance(flow.metadata_json, dict) else None,
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
                raise BadRequestException(
                    "Flow run input payload exceeds allowed size limit.",
                    code="flow_run_input_payload_too_large",
                    context={
                        "flow_id": str(flow_id),
                        "max_inline_text_bytes": get_settings().flow_max_inline_text_bytes,
                    },
                )

        # Serialize run creation per tenant to prevent concurrency-limit race conditions.
        await self.flow_repo.session.execute(
            sa.select(Tenants.id)
            .where(Tenants.id == self.user.tenant_id)
            .with_for_update()
        )
        active_runs = await self.flow_run_repo.count_active_runs(tenant_id=self.user.tenant_id)
        if active_runs >= self.max_concurrent_runs:
            raise BadRequestException(
                "Concurrent flow run limit reached for this tenant.",
                code="flow_run_concurrency_limit_reached",
                context={"max_concurrent_runs": self.max_concurrent_runs},
            )
        if flow.id is None:
            raise BadRequestException(
                "Flow id missing for run creation.",
                code="flow_id_missing",
            )
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
            logger.exception(
                "Failed to dispatch newly created flow run",
                extra={
                    "run_id": str(created.id),
                    "flow_id": str(flow.id),
                    "tenant_id": str(self.user.tenant_id),
                },
            )
            # If dispatch fails here, request-level transaction handling decides
            # whether run creation is committed or rolled back as one unit.
            raise
        return created

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

    async def list_step_results(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
    ) -> list[FlowStepResult]:
        run = await self.get_run(run_id=run_id, flow_id=flow_id)
        return await self.flow_run_repo.list_step_results(
            run_id=run.id,
            tenant_id=self.user.tenant_id,
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
            normalized_step_order = self._parse_step_order(step_order)
            if normalized_step_order is None:
                continue
            rag_by_step_order[normalized_step_order] = rag_metadata

        raw_steps = definition_snapshot.get("steps")
        normalized_steps = []
        if isinstance(raw_steps, list):
            for raw_step in raw_steps:
                if isinstance(raw_step, dict):
                    parsed_step_order = self._parse_step_order(raw_step.get("step_order"), default=0)
                    step_order = parsed_step_order if parsed_step_order is not None else 0
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
    def _parse_step_order(value: Any, *, default: int | None = None) -> int | None:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                return default
            try:
                return int(stripped)
            except ValueError:
                return default
        return default

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
            raise BadRequestException(
                "Published flow version does not contain executable steps.",
                code="flow_version_no_executable_steps",
            )

        by_step_order: dict[int, FlowStep] = {}
        for step in fallback_steps:
            if getattr(step, "id", None) is None:
                continue
            by_step_order[int(step.step_order)] = step

        preseed: list[PreseedStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                raise BadRequestException(
                    "Invalid flow version step definition.",
                    code="flow_version_invalid_step_definition",
                )
            step_order_raw = raw_step.get("step_order", 0)
            if isinstance(step_order_raw, bool):
                raise BadRequestException(
                    "Invalid flow version step order.",
                    code="flow_version_invalid_step_order",
                    context={"step_order": step_order_raw},
                )
            try:
                step_order = int(step_order_raw)
            except (TypeError, ValueError) as exc:
                raise BadRequestException(
                    "Invalid flow version step order.",
                    code="flow_version_invalid_step_order",
                    context={"step_order": step_order_raw},
                ) from exc
            if step_order <= 0:
                raise BadRequestException(
                    "Invalid flow version step order.",
                    code="flow_version_invalid_step_order",
                    context={"step_order": step_order},
                )

            step_id_raw = raw_step.get("step_id")
            assistant_id_raw = raw_step.get("assistant_id")
            if step_id_raw is None or assistant_id_raw is None:
                fallback = by_step_order.get(step_order)
                if fallback is None:
                    raise BadRequestException(
                        f"Flow version step {step_order} is missing stable step identifiers.",
                        code="flow_version_missing_step_identifiers",
                        context={"step_order": step_order},
                    )
                step_id_raw = fallback.id
                assistant_id_raw = fallback.assistant_id

            try:
                step_id = UUID(str(step_id_raw))
            except (TypeError, ValueError, AttributeError) as exc:
                raise BadRequestException(
                    "Invalid flow version step identifier.",
                    code="flow_version_invalid_step_identifier",
                    context={
                        "step_order": step_order,
                        "field": "step_id",
                        "value": step_id_raw,
                    },
                ) from exc

            try:
                assistant_id = UUID(str(assistant_id_raw))
            except (TypeError, ValueError, AttributeError) as exc:
                raise BadRequestException(
                    "Invalid flow version step identifier.",
                    code="flow_version_invalid_step_identifier",
                    context={
                        "step_order": step_order,
                        "field": "assistant_id",
                        "value": assistant_id_raw,
                    },
                ) from exc

            preseed.append(
                {
                    "step_id": step_id,
                    "assistant_id": assistant_id,
                    "step_order": step_order,
                }
            )
        return preseed
