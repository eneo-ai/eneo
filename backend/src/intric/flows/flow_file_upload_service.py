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
from intric.flows.flow_input_limits import FlowInputLimits, effective_flow_input_limit
from intric.main.exceptions import BadRequestException, FileNotSupportedException, FileTooLargeException
from intric.settings.settings import FlowInputLimitsPublic

logger = logging.getLogger(__name__)

_FILE_UPLOAD_INPUT_TYPES = {"audio", "document", "image", "file"}
DEFAULT_MAX_AUDIO_FILES_PER_RUN = 10
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


class _FlowServiceProtocol(Protocol):
    async def get_flow(self, flow_id: UUID) -> Flow: ...


class _SettingsServiceProtocol(Protocol):
    async def get_flow_input_limits(self) -> FlowInputLimitsPublic: ...


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


def _build_policy(flow: Flow, limits: FlowInputLimitsPublic) -> FlowFileInputPolicy:
    if flow.id is None:
        raise BadRequestException("Flow id is missing.")

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
            limits=FlowInputLimits(
                file_max_size_bytes=limits.file_max_size_bytes,
                audio_max_size_bytes=limits.audio_max_size_bytes,
            ),
        )
        if input_type == "audio":
            max_files_per_run = DEFAULT_MAX_AUDIO_FILES_PER_RUN

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
    ):
        self.flow_service = flow_service
        self.file_service = file_service
        self.settings_service = settings_service

    async def get_input_policy(self, *, flow_id: UUID) -> FlowFileInputPolicy:
        flow = await self.flow_service.get_flow(flow_id)
        limits = await self.settings_service.get_flow_input_limits()
        return _build_policy(flow, limits)

    async def upload_file_for_flow(self, *, flow_id: UUID, upload_file: UploadFile) -> File:
        policy = await self.get_input_policy(flow_id=flow_id)

        if not policy.accepts_file_upload:
            raise BadRequestException(
                "Flow does not accept file uploads for flow_input. "
                "Use text/json payload for this flow."
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
                f"type '{policy.input_type}'. Allowed types: {allowed_types}."
            )

        if not declared_canonical or declared_canonical not in allowed_canonical_types:
            received_type = upload_file.content_type or "missing"
            allowed_types = ", ".join(policy.accepted_mimetypes)
            raise FileNotSupportedException(
                f"Unsupported file type '{received_type}' for flow input type '{policy.input_type}'. "
                f"Allowed types: {allowed_types}."
            )

        max_size = policy.max_file_size_bytes
        if max_size is None:
            raise BadRequestException("Flow input policy is missing a max file size.")

        try:
            return await self.file_service.save_file(upload_file, max_size=max_size)
        except FileTooLargeException as exc:
            raise FileTooLargeException(
                f"Uploaded file exceeds effective flow limit of {max_size} bytes."
            ) from exc
