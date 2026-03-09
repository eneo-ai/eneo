from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Protocol
from uuid import UUID

from fastapi import UploadFile
import magic

from intric.files.audio import AudioMimeTypes
from intric.files.file_models import File
from intric.files.file_service import FileService
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.flows.flow import Flow, FlowStep
from intric.flows.flow_input_limits import FlowInputLimits, effective_flow_input_limit, effective_max_files_per_run
from intric.flows.runtime.step_definition_parser import parse_runtime_steps
from intric.flows.runtime_input import build_runtime_input_config, runtime_input_accept_mimetypes
from intric.main.exceptions import BadRequestException, FileNotSupportedException, FileTooLargeException

logger = logging.getLogger(__name__)

_FILE_UPLOAD_INPUT_TYPES = {"audio", "document", "image", "file"}
_SNIFF_BYTES = 8192
_UNKNOWN_SNIFFED_TYPES = {"application/octet-stream"}
_MIMETYPE_CANONICAL_ALIASES = {
    "audio/mp3": "audio/mpeg",
    "audio/x-m4a": "audio/mp4",
    "video/mp4": "audio/mp4",
    "video/webm": "audio/webm",
}


def _normalize_mimetype(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _canonicalize_mimetype(value: str | None) -> str:
    normalized = _normalize_mimetype(value)
    if not normalized:
        return ""
    return _MIMETYPE_CANONICAL_ALIASES.get(normalized, normalized)


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
                logger.debug("Failed to reset file pointer after MIME sniffing.", exc_info=True)

    if not chunk:
        return None
    if isinstance(chunk, str):
        chunk = chunk.encode("utf-8", errors="ignore")

    try:
        return _normalize_mimetype(magic.from_buffer(chunk, mime=True))
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
                logger.debug("Failed to reset file pointer after empty-file check.", exc_info=True)

    if isinstance(chunk, str):
        chunk = chunk.encode("utf-8", errors="ignore")
    return isinstance(chunk, bytes) and len(chunk) == 0


class _FlowServiceProtocol(Protocol):
    async def get_flow(self, flow_id: UUID) -> Flow: ...


class _SettingsServiceProtocol(Protocol):
    async def get_flow_input_limits_resolved(self) -> FlowInputLimits: ...


class _FlowVersionRepositoryProtocol(Protocol):
    async def get(self, flow_id: UUID, version: int, tenant_id: UUID): ...


class _FlowTemplateAssetRepositoryProtocol(Protocol):
    async def get(self, *, asset_id: UUID, tenant_id: UUID): ...


@dataclass(frozen=True)
class FlowFileInputPolicy:
    flow_id: UUID
    input_type: str | None
    input_source: str | None
    accepts_file_upload: bool
    accepted_mimetypes: list[str]
    max_file_size_bytes: int | None
    max_files_per_run: int | None
    recommended_run_payload: dict[str, object] | None


def _first_flow_input_step(flow: Flow) -> FlowStep | None:
    flow_input_steps = [step for step in flow.steps if step.input_source == "flow_input"]
    if not flow_input_steps:
        return None

    flow_input_steps.sort(key=lambda step: (step.step_order, str(step.id or "")))
    return flow_input_steps[0]


def _accepted_mimetypes_for_input_type(input_type: str) -> list[str]:
    if input_type == "audio":
        return AudioMimeTypes.values()
    if input_type == "image":
        return ImageMimeTypes.values()
    if input_type in {"document", "file"}:
        return TextMimeTypes.values()
    return []


def _recommended_run_payload_for_input_type(
    *,
    input_type: str,
    accepts_file_upload: bool,
) -> dict[str, object]:
    if accepts_file_upload:
        base: dict[str, object] = {"file_ids": ["<file-id-uuid>"]}
        if input_type == "audio":
            base["input_payload_json"] = {
                "text": "optional context for later prompt steps",
            }
        return base

    if input_type == "json":
        return {"input_payload_json": {"data": {"key": "value"}}}

    return {"input_payload_json": {"text": "<text-input>"}}


def _build_policy(flow: Flow, limits: FlowInputLimits) -> FlowFileInputPolicy:
    if flow.id is None:
        raise BadRequestException(
            "Flow id is missing.",
            code="flow_id_missing",
        )

    step = _first_flow_input_step(flow)
    if step is None:
        return FlowFileInputPolicy(
            flow_id=flow.id,
            input_type=None,
            input_source=None,
            accepts_file_upload=False,
            accepted_mimetypes=[],
            max_file_size_bytes=None,
            max_files_per_run=None,
            recommended_run_payload=None,
        )

    input_type = str(step.input_type)
    accepts_file_upload = input_type in _FILE_UPLOAD_INPUT_TYPES
    accepted_mimetypes = _accepted_mimetypes_for_input_type(input_type)
    max_file_size_bytes = None
    max_files_per_run = None
    if accepts_file_upload:
        max_file_size_bytes = effective_flow_input_limit(
            input_type=input_type,
            limits=limits,
        )
        max_files_per_run = effective_max_files_per_run(
            input_type=input_type,
            limits=limits,
        )

    return FlowFileInputPolicy(
        flow_id=flow.id,
        input_type=input_type,
        input_source=step.input_source,
        accepts_file_upload=accepts_file_upload,
        accepted_mimetypes=accepted_mimetypes,
        max_file_size_bytes=max_file_size_bytes,
        max_files_per_run=max_files_per_run,
        recommended_run_payload=_recommended_run_payload_for_input_type(
            input_type=input_type,
            accepts_file_upload=accepts_file_upload,
        ),
    )


class FlowFileUploadService:
    def __init__(
        self,
        *,
        flow_service: _FlowServiceProtocol,
        file_service: FileService,
        settings_service: _SettingsServiceProtocol,
        flow_version_repo: _FlowVersionRepositoryProtocol | None = None,
        template_asset_repo: _FlowTemplateAssetRepositoryProtocol | None = None,
    ):
        self.flow_service = flow_service
        self.file_service = file_service
        self.settings_service = settings_service
        self.flow_version_repo = flow_version_repo
        self.template_asset_repo = template_asset_repo

    async def get_input_policy(self, *, flow_id: UUID) -> FlowFileInputPolicy:
        flow = await self.flow_service.get_flow(flow_id)
        limits = await self.settings_service.get_flow_input_limits_resolved()
        return _build_policy(flow, limits)

    async def upload_file_for_flow(self, *, flow_id: UUID, upload_file: UploadFile) -> File:
        policy = await self.get_input_policy(flow_id=flow_id)

        if not policy.accepts_file_upload:
            raise BadRequestException(
                "Flow does not accept file uploads for flow_input. "
                "Use text/json payload for this flow.",
                code="flow_input_upload_not_supported",
                context={"flow_id": str(flow_id), "input_type": policy.input_type},
            )

        if _is_empty_upload_file(upload_file):
            raise BadRequestException(
                "Uploaded file is empty.",
                code="flow_input_file_empty",
                context={"flow_id": str(flow_id)},
            )

        declared_type = _normalize_mimetype(upload_file.content_type)
        declared_canonical = _canonicalize_mimetype(declared_type)
        allowed_canonical_types = {
            _canonicalize_mimetype(mimetype) for mimetype in policy.accepted_mimetypes
        }
        sniffed_type = _sniff_mimetype(upload_file)
        sniffed_canonical = _canonicalize_mimetype(sniffed_type) if sniffed_type else ""

        if sniffed_type in _UNKNOWN_SNIFFED_TYPES:
            sniffed_type = None
            sniffed_canonical = ""

        if sniffed_canonical and sniffed_canonical not in allowed_canonical_types:
            allowed_types = ", ".join(policy.accepted_mimetypes)
            raise FileNotSupportedException(
                f"Detected file type '{sniffed_type}' is not allowed for flow input "
                f"type '{policy.input_type}'. Allowed types: {allowed_types}.",
                code="unsupported_media_type",
                context={
                    "flow_id": str(flow_id),
                    "input_type": policy.input_type,
                    "received_type": declared_type or "missing",
                    "detected_type": sniffed_type,
                },
            )

        if not declared_canonical or declared_canonical not in allowed_canonical_types:
            received_type = upload_file.content_type or "missing"
            allowed_types = ", ".join(policy.accepted_mimetypes)
            raise FileNotSupportedException(
                f"Unsupported file type '{received_type}' for flow input type '{policy.input_type}'. "
                f"Allowed types: {allowed_types}.",
                code="unsupported_media_type",
                context={
                    "flow_id": str(flow_id),
                    "input_type": policy.input_type,
                    "received_type": received_type,
                },
            )

        max_size = policy.max_file_size_bytes
        if max_size is None:
            raise BadRequestException(
                "Flow input policy is missing a max file size.",
                code="flow_input_policy_missing_limit",
                context={"flow_id": str(flow_id)},
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
            ) from exc

    async def get_run_contract(self, *, flow_id: UUID) -> dict[str, object]:
        if self.flow_version_repo is None or self.template_asset_repo is None:
            raise BadRequestException(
                "Published flow runtime contract dependencies are unavailable.",
                code="flow_runtime_contract_unavailable",
            )
        flow = await self.flow_service.get_flow(flow_id)
        if flow.published_version is None:
            raise BadRequestException(
                "Flow must be published before a run contract can be created.",
                code="flow_not_published",
            )

        version = await self.flow_version_repo.get(
            flow_id=flow.id,
            version=flow.published_version,
            tenant_id=flow.tenant_id,
        )
        limits = await self.settings_service.get_flow_input_limits_resolved()
        steps = parse_runtime_steps(version.definition_json)
        steps_requiring_input: list[dict[str, object]] = []
        aggregate_max_files: int | None = 0

        for step in steps:
            runtime_input = build_runtime_input_config(step.input_config)
            if not runtime_input.enabled:
                continue

            max_files = runtime_input.max_files
            if aggregate_max_files is not None:
                if max_files is None:
                    aggregate_max_files = None
                else:
                    aggregate_max_files += max_files

            steps_requiring_input.append(
                {
                    "step_id": step.step_id,
                    "step_order": step.step_order,
                    "label": runtime_input.label,
                    "description": runtime_input.description,
                    "required": runtime_input.required,
                    "input_format": runtime_input.input_format,
                    "max_files": runtime_input.max_files,
                    "max_file_size_bytes": effective_flow_input_limit(
                        input_type=runtime_input.input_format,
                        limits=limits,
                    ),
                    "accepted_mimetypes": runtime_input_accept_mimetypes(runtime_input),
                }
            )

        template_readiness = []
        for step in steps:
            if step.output_mode != "template_fill" or not isinstance(step.output_config, dict):
                continue
            asset_id_raw = step.output_config.get("template_asset_id")
            asset_status = "unavailable"
            template_name = step.output_config.get("template_name")
            template_file_id = step.output_config.get("template_file_id")
            checksum = step.output_config.get("template_checksum")
            asset_id = None
            if asset_id_raw is not None:
                try:
                    asset_id = UUID(str(asset_id_raw))
                    asset = await self.template_asset_repo.get(
                        asset_id=asset_id,
                        tenant_id=flow.tenant_id,
                    )
                    asset_status = "ready"
                    template_name = asset.name
                    template_file_id = asset.file_id
                    checksum = asset.checksum
                except Exception:
                    asset_status = "unavailable"
            elif template_file_id is not None:
                try:
                    legacy_file_id = UUID(str(template_file_id))
                    asset = await self.template_asset_repo.get_by_flow_file(
                        flow_id=flow.id,
                        file_id=legacy_file_id,
                        tenant_id=flow.tenant_id,
                    )
                    asset_id = asset.id
                    asset_status = "ready"
                    template_name = asset.name
                    template_file_id = asset.file_id
                    checksum = asset.checksum
                except Exception:
                    asset_status = "unavailable"
            template_readiness.append(
                {
                    "step_id": step.step_id,
                    "template_asset_id": asset_id,
                    "template_file_id": template_file_id,
                    "template_name": template_name,
                    "checksum": checksum,
                    "published_flow_version": flow.published_version,
                    "status": asset_status,
                    "can_edit": False,
                    "can_download": asset_id is not None,
                    "message_code": None if asset_status == "ready" else "flow_template_not_accessible",
                }
            )

        form_fields = []
        form_schema = (flow.metadata_json or {}).get("form_schema") if isinstance(flow.metadata_json, dict) else None
        if isinstance(form_schema, dict) and isinstance(form_schema.get("fields"), list):
            form_fields = list(form_schema["fields"])

        return {
            "flow_id": flow.id,
            "published_flow_version": flow.published_version,
            "form_fields": form_fields,
            "steps_requiring_input": steps_requiring_input,
            "aggregate_max_files": aggregate_max_files,
            "template_readiness": template_readiness,
        }

    async def upload_runtime_file_for_step(
        self,
        *,
        flow_id: UUID,
        step_id: UUID,
        upload_file: UploadFile,
    ) -> File:
        if self.flow_version_repo is None:
            raise BadRequestException(
                "Published flow runtime upload dependencies are unavailable.",
                code="flow_runtime_contract_unavailable",
            )
        flow = await self.flow_service.get_flow(flow_id)
        if flow.published_version is None:
            raise BadRequestException(
                "Flow must be published before runtime files can be uploaded.",
                code="flow_not_published",
            )
        version = await self.flow_version_repo.get(
            flow_id=flow.id,
            version=flow.published_version,
            tenant_id=flow.tenant_id,
        )
        steps = parse_runtime_steps(version.definition_json)
        runtime_step = next((step for step in steps if step.step_id == step_id), None)
        if runtime_step is None:
            raise BadRequestException("Unknown runtime step id.", code="flow_run_unknown_step_input")

        runtime_input = build_runtime_input_config(runtime_step.input_config)
        if not runtime_input.enabled:
            raise BadRequestException(
                "Runtime input is not enabled for this step.",
                code="flow_run_runtime_input_disabled",
            )

        limits = await self.settings_service.get_flow_input_limits_resolved()
        max_size = effective_flow_input_limit(
            input_type=runtime_input.input_format,
            limits=limits,
        )
        policy = FlowFileInputPolicy(
            flow_id=flow.id,
            input_type=runtime_input.input_format,
            input_source=runtime_step.input_source,
            accepts_file_upload=True,
            accepted_mimetypes=runtime_input_accept_mimetypes(runtime_input),
            max_file_size_bytes=max_size,
            max_files_per_run=runtime_input.max_files
            or effective_max_files_per_run(
                input_type=runtime_input.input_format,
                limits=limits,
            ),
            recommended_run_payload=None,
        )
        return await self._upload_with_policy(
            flow_id=flow.id,
            upload_file=upload_file,
            policy=policy,
        )

    async def _upload_with_policy(
        self,
        *,
        flow_id: UUID,
        upload_file: UploadFile,
        policy: FlowFileInputPolicy,
    ) -> File:
        if not policy.accepts_file_upload:
            raise BadRequestException(
                "Flow does not accept file uploads for flow_input. Use text/json payload for this flow.",
                code="flow_input_upload_not_supported",
                context={"flow_id": str(flow_id), "input_type": policy.input_type},
            )

        if _is_empty_upload_file(upload_file):
            raise BadRequestException(
                "Uploaded file is empty.",
                code="flow_input_file_empty",
                context={"flow_id": str(flow_id)},
            )

        declared_type = _normalize_mimetype(upload_file.content_type)
        declared_canonical = _canonicalize_mimetype(declared_type)
        allowed_canonical_types = {
            _canonicalize_mimetype(mimetype) for mimetype in policy.accepted_mimetypes
        }
        sniffed_type = _sniff_mimetype(upload_file)
        sniffed_canonical = _canonicalize_mimetype(sniffed_type) if sniffed_type else ""

        if sniffed_type in _UNKNOWN_SNIFFED_TYPES:
            sniffed_type = None
            sniffed_canonical = ""

        if sniffed_canonical and sniffed_canonical not in allowed_canonical_types:
            allowed_types = ", ".join(policy.accepted_mimetypes)
            raise FileNotSupportedException(
                f"Detected file type '{sniffed_type}' is not allowed for flow input type '{policy.input_type}'. Allowed types: {allowed_types}.",
                code="unsupported_media_type",
                context={
                    "flow_id": str(flow_id),
                    "input_type": policy.input_type,
                    "received_type": declared_type or "missing",
                    "detected_type": sniffed_type,
                },
            )

        if not declared_canonical or declared_canonical not in allowed_canonical_types:
            received_type = upload_file.content_type or "missing"
            allowed_types = ", ".join(policy.accepted_mimetypes)
            raise FileNotSupportedException(
                f"Unsupported file type '{received_type}' for flow input type '{policy.input_type}'. Allowed types: {allowed_types}.",
                code="unsupported_media_type",
                context={
                    "flow_id": str(flow_id),
                    "input_type": policy.input_type,
                    "received_type": received_type,
                },
            )

        max_size = policy.max_file_size_bytes
        if max_size is None:
            raise BadRequestException(
                "Flow input policy is missing a max file size.",
                code="flow_input_policy_missing_limit",
                context={"flow_id": str(flow_id)},
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
            ) from exc
