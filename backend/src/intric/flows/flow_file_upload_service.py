from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import magic
from fastapi import UploadFile

from intric.files.file_models import File
from intric.files.file_service import FileService
from intric.files.mime_support import canonicalize_mime
from intric.flows.domain.flow import Flow, FlowVersion
from intric.flows.enums import FlowRuntimeInputFormat
from intric.flows.flow_input_limits import FlowInputLimits
from intric.flows.flow_run_step_inputs import (
    RuntimeStepInputSpec,
    build_runtime_step_input_specs,
    first_flow_input_runtime_spec,
)
from intric.flows.published_definition import parse_published_runtime_steps
from intric.flows.runtime.models import RuntimeStep
from intric.main.exceptions import (
    BadRequestException,
    FileNotSupportedException,
    FileTooLargeException,
)

logger = logging.getLogger(__name__)

_SNIFF_BYTES = 8192
_UNKNOWN_SNIFFED_TYPES = {"application/octet-stream"}


def _sniff_mimetype(upload_file: UploadFile) -> str | None:
    file_obj = getattr(upload_file, "file", None)
    if file_obj is None:
        return None

    start_position: int | None = None
    if hasattr(file_obj, "tell"):
        try:
            start_position = int(file_obj.tell())
        except Exception:
            start_position = None

    try:
        chunk = file_obj.read(_SNIFF_BYTES)
    except Exception:
        return None
    finally:
        if start_position is not None and hasattr(file_obj, "seek"):
            try:
                file_obj.seek(start_position)
            except Exception:
                logger.debug(
                    "Failed to reset file pointer after MIME sniffing.", exc_info=True
                )

    if not chunk:
        return None
    if isinstance(chunk, str):
        chunk = chunk.encode("utf-8", errors="ignore")

    try:
        return canonicalize_mime(magic.from_buffer(chunk, mime=True))
    except Exception:
        logger.debug("Failed to sniff file MIME type from content.", exc_info=True)
        return None


def _is_empty_upload_file(upload_file: UploadFile) -> bool:
    file_obj = getattr(upload_file, "file", None)
    if file_obj is None:
        return False

    start_position: int | None = None
    if hasattr(file_obj, "tell"):
        try:
            start_position = int(file_obj.tell())
        except Exception:
            start_position = None

    try:
        chunk = file_obj.read(1)
    except Exception:
        return False
    finally:
        if start_position is not None and hasattr(file_obj, "seek"):
            try:
                file_obj.seek(start_position)
            except Exception:
                logger.debug(
                    "Failed to reset file pointer after empty-file check.",
                    exc_info=True,
                )

    if isinstance(chunk, str):
        chunk = chunk.encode("utf-8", errors="ignore")
    return isinstance(chunk, bytes) and len(chunk) == 0


async def _sniff_mimetype_async(upload_file: UploadFile) -> str | None:
    return await asyncio.to_thread(_sniff_mimetype, upload_file)


async def _is_empty_upload_file_async(upload_file: UploadFile) -> bool:
    return await asyncio.to_thread(_is_empty_upload_file, upload_file)


class _FlowServiceProtocol(Protocol):
    async def get_flow(self, flow_id: UUID) -> Flow: ...


class _SettingsServiceProtocol(Protocol):
    async def get_flow_input_limits_resolved(self) -> FlowInputLimits: ...


class _FlowVersionRepositoryProtocol(Protocol):
    async def get(
        self, flow_id: UUID, version: int, tenant_id: UUID
    ) -> FlowVersion: ...


@dataclass(frozen=True)
class FlowFileInputPolicy:
    flow_id: UUID
    input_type: FlowRuntimeInputFormat
    accepted_mimetypes: list[str]
    max_file_size_bytes: int
    max_files_per_run: int | None


def _require_flow_id(flow: Flow) -> UUID:
    if flow.id is None:
        raise BadRequestException(
            "Flow id is missing.",
            code="flow_id_missing",
        )
    return flow.id


def _policy_from_runtime_spec(
    *,
    flow_id: UUID,
    spec: RuntimeStepInputSpec,
) -> FlowFileInputPolicy:
    return FlowFileInputPolicy(
        flow_id=flow_id,
        input_type=spec.runtime_input.input_format,
        accepted_mimetypes=spec.accepted_mimetypes,
        max_file_size_bytes=spec.max_file_size_bytes,
        max_files_per_run=spec.max_files,
    )


class FlowFileUploadService:
    def __init__(
        self,
        *,
        flow_service: _FlowServiceProtocol,
        file_service: FileService,
        settings_service: _SettingsServiceProtocol,
        flow_version_repo: _FlowVersionRepositoryProtocol | None = None,
    ):
        self.flow_service = flow_service
        self.file_service = file_service
        self.settings_service = settings_service
        self.flow_version_repo = flow_version_repo

    async def upload_file_for_flow(
        self, *, flow_id: UUID, upload_file: UploadFile
    ) -> File:
        policy = await self._get_published_flow_upload_policy(flow_id=flow_id)
        return await self._upload_with_policy(
            flow_id=flow_id,
            upload_file=upload_file,
            policy=policy,
        )

    async def upload_runtime_file_for_step(
        self,
        *,
        flow_id: UUID,
        step_id: UUID,
        upload_file: UploadFile,
    ) -> File:
        persisted_flow_id, steps, limits = await self._get_published_runtime_inputs(
            flow_id=flow_id
        )
        runtime_step = next((step for step in steps if step.step_id == step_id), None)
        if runtime_step is None:
            raise BadRequestException(
                "Unknown runtime step id.", code="flow_run_unknown_step_input"
            )

        specs = build_runtime_step_input_specs(steps=steps, limits=limits)
        spec = specs.get(step_id)
        if spec is None:
            raise BadRequestException(
                "Runtime input is not enabled for this step.",
                code="flow_run_runtime_input_disabled",
            )

        policy = _policy_from_runtime_spec(flow_id=persisted_flow_id, spec=spec)
        return await self._upload_with_policy(
            flow_id=persisted_flow_id,
            upload_file=upload_file,
            policy=policy,
        )

    async def _get_published_flow_upload_policy(
        self, *, flow_id: UUID
    ) -> FlowFileInputPolicy:
        persisted_flow_id, steps, limits = await self._get_published_runtime_inputs(
            flow_id=flow_id
        )
        specs = build_runtime_step_input_specs(steps=steps, limits=limits)
        spec = first_flow_input_runtime_spec(specs)
        if spec is None:
            raise BadRequestException(
                "Flow does not accept file uploads for flow_input. Use step-specific runtime uploads from the run contract.",
                code="flow_input_upload_not_supported",
                context={"flow_id": str(persisted_flow_id), "input_type": None},
            )
        return _policy_from_runtime_spec(flow_id=persisted_flow_id, spec=spec)

    async def _get_published_runtime_inputs(
        self, *, flow_id: UUID
    ) -> tuple[UUID, list[RuntimeStep], FlowInputLimits]:
        if self.flow_version_repo is None:
            raise BadRequestException(
                "Published flow runtime upload dependencies are unavailable.",
                code="flow_runtime_contract_unavailable",
            )
        flow = await self.flow_service.get_flow(flow_id)
        persisted_flow_id = _require_flow_id(flow)
        if flow.published_version is None:
            raise BadRequestException(
                "Flow must be published before runtime files can be uploaded.",
                code="flow_not_published",
            )
        version = await self.flow_version_repo.get(
            flow_id=persisted_flow_id,
            version=flow.published_version,
            tenant_id=flow.tenant_id,
        )
        steps = parse_published_runtime_steps(version.definition_json)
        limits = await self.settings_service.get_flow_input_limits_resolved()
        return persisted_flow_id, steps, limits

    async def _upload_with_policy(
        self,
        *,
        flow_id: UUID,
        upload_file: UploadFile,
        policy: FlowFileInputPolicy,
    ) -> File:
        max_size = await self._validate_upload_with_policy(
            flow_id=flow_id,
            upload_file=upload_file,
            policy=policy,
        )

        try:
            return await self.file_service.save_file(upload_file, max_size=max_size)
        except FileTooLargeException as exc:
            raise FileTooLargeException(
                f"Uploaded file exceeds effective flow limit of {max_size} bytes.",
                code="file_too_large",
                context={
                    "flow_id": str(flow_id),
                    "max_file_size_bytes": max_size,
                },
                max_size=max_size,
            ) from exc

    async def _validate_upload_with_policy(
        self,
        *,
        flow_id: UUID,
        upload_file: UploadFile,
        policy: FlowFileInputPolicy,
    ) -> int:
        if await _is_empty_upload_file_async(upload_file):
            raise BadRequestException(
                "Uploaded file is empty.",
                code="flow_input_file_empty",
                context={"flow_id": str(flow_id)},
            )

        declared_type = canonicalize_mime(upload_file.content_type)
        declared_canonical = declared_type
        allowed_canonical_types = {
            canonicalize_mime(mimetype) for mimetype in policy.accepted_mimetypes
        }
        sniffed_type = await _sniff_mimetype_async(upload_file)
        sniffed_canonical = canonicalize_mime(sniffed_type) if sniffed_type else ""

        if sniffed_type in _UNKNOWN_SNIFFED_TYPES:
            sniffed_type = None
            sniffed_canonical = ""

        if sniffed_canonical and sniffed_canonical not in allowed_canonical_types:
            allowed_types = ", ".join(policy.accepted_mimetypes)
            raise FileNotSupportedException(
                f"Detected file type '{sniffed_type}' is not allowed for flow input type '{policy.input_type.value}'. Allowed types: {allowed_types}.",
                code="unsupported_media_type",
                context={
                    "flow_id": str(flow_id),
                    "input_type": policy.input_type.value,
                    "received_type": declared_type or "missing",
                    "detected_type": sniffed_type,
                },
            )

        if not declared_canonical or declared_canonical not in allowed_canonical_types:
            received_type = upload_file.content_type or "missing"
            allowed_types = ", ".join(policy.accepted_mimetypes)
            raise FileNotSupportedException(
                f"Unsupported file type '{received_type}' for flow input type '{policy.input_type.value}'. Allowed types: {allowed_types}.",
                code="unsupported_media_type",
                context={
                    "flow_id": str(flow_id),
                    "input_type": policy.input_type.value,
                    "received_type": received_type,
                },
            )

        return policy.max_file_size_bytes
