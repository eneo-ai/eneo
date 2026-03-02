from __future__ import annotations

import json
import re
from typing import Any, TypedDict, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.tenant_table import Tenants
from intric.flows.flow import FlowRun, FlowRunStatus, FlowStep, JsonObject
from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_run_repo import FlowRunRepository
from intric.flows.flow_version_repo import FlowVersionRepository
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.users.user import UserInDB

_REDACTED_VALUE = "[REDACTED]"
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


def _is_sensitive_key(key: str | None) -> bool:
    if key is None:
        return False
    key_lower = key.lower()
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
        }

    def _build_preseed_steps(
        self,
        *,
        definition_json: JsonObject,
        fallback_steps: list[FlowStep],
    ) -> list["PreseedStep"]:
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


class PreseedStep(TypedDict):
    step_id: UUID
    assistant_id: UUID
    step_order: int
