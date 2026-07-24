from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

import magic
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError

from eneo.database.database import AsyncSession
from eneo.files.file_models import File
from eneo.files.file_service import FileService
from eneo.files.mime_support import canonicalize_mime
from eneo.flows.enums import FlowRuntimeInputFormat
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_run_step_inputs import (
    RuntimeStepInputSpec,
)
from eneo.flows.flow_runtime_file_integrity import (
    is_runtime_file_attachment_integrity_error,
)
from eneo.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.published_runtime import (
    FlowRuntimeFlowSource,
    FlowRuntimePublicationIntent,
    FlowRuntimeSettingsSource,
    FlowRuntimeVersionSource,
    load_published_flow_runtime,
    load_published_runtime_inputs,
)
from eneo.main.exceptions import (
    ConflictException,
    FileNotSupportedException,
    FileTooLargeException,
    NotFoundException,
)
from eneo.users.user import UserInDB

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


@dataclass(frozen=True)
class FlowFileInputPolicy:
    flow_id: UUID
    input_type: FlowRuntimeInputFormat
    accepted_mimetypes: list[str]
    max_file_size_bytes: int
    max_files_per_run: int | None


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


def _ensure_shared_write_session(
    *,
    session: AsyncSession,
    file_service: FileService,
    runtime_upload_repo: FlowRuntimeUploadRepository,
) -> None:
    if file_service.repo.session is session and runtime_upload_repo.session is session:
        return

    raise RuntimeError(
        "FlowRuntimeFileService requires file and runtime-upload writes to share "
        "the injected AsyncSession."
    )


class FlowRuntimeFileService:
    def __init__(
        self,
        *,
        user: UserInDB,
        session: AsyncSession,
        flow_service: FlowRuntimeFlowSource,
        file_service: FileService,
        runtime_upload_repo: FlowRuntimeUploadRepository,
        settings_service: FlowRuntimeSettingsSource,
        flow_version_repo: FlowRuntimeVersionSource,
    ):
        _ensure_shared_write_session(
            session=session,
            file_service=file_service,
            runtime_upload_repo=runtime_upload_repo,
        )
        self.user = user
        self.session = session
        self.flow_service = flow_service
        self.file_service = file_service
        self.runtime_upload_repo = runtime_upload_repo
        self.settings_service = settings_service
        self.flow_version_repo = flow_version_repo

    @asynccontextmanager
    async def _write_transaction(self) -> AsyncGenerator[None, None]:
        if self.session.in_transaction():
            # Outer callers own commit; upload writes only join the active unit.
            yield
            return

        async with self.session.begin():
            yield

    def _principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    async def upload_runtime_file_for_step(
        self,
        *,
        flow_id: UUID,
        step_id: UUID,
        upload_file: UploadFile,
    ) -> File:
        runtime_inputs = await load_published_runtime_inputs(
            flow_service=self.flow_service,
            flow_version_repo=self.flow_version_repo,
            settings_source=self.settings_service,
            flow_id=flow_id,
            intent=FlowRuntimePublicationIntent.RUNTIME_UPLOAD,
        )
        runtime_step = next(
            (step for step in runtime_inputs.steps if step.step_id == step_id), None
        )
        if runtime_step is None:
            raise FlowBadRequestException(
                "Unknown runtime step id.",
                code=FlowApiErrorCode.RUN_UNKNOWN_STEP_INPUT,
                context={"step_id": str(step_id)},
            )

        spec = runtime_inputs.input_specs.get(step_id)
        if spec is None:
            raise FlowBadRequestException(
                "Runtime input is not enabled for this step.",
                code=FlowApiErrorCode.RUN_RUNTIME_INPUT_DISABLED,
            )

        policy = _policy_from_runtime_spec(
            flow_id=runtime_inputs.published.flow_id, spec=spec
        )
        return await self._upload_with_policy(
            flow_id=runtime_inputs.published.flow_id,
            step_id=step_id,
            upload_file=upload_file,
            policy=policy,
        )

    async def delete_runtime_file(self, *, flow_id: UUID, file_id: UUID) -> File:
        published = await load_published_flow_runtime(
            flow_service=self.flow_service,
            flow_id=flow_id,
            intent=FlowRuntimePublicationIntent.RUNTIME_DELETE,
        )
        exists = await self.runtime_upload_repo.exists_for_owner(
            file_id=file_id,
            flow_id=published.flow_id,
            tenant_id=self.user.tenant_id,
            principal=self._principal(),
        )
        if not exists:
            raise NotFoundException(code="not_found")

        try:
            return await self.file_service.delete_file(file_id)
        except NotFoundException as exc:
            raise NotFoundException(code="not_found") from exc
        except IntegrityError as exc:
            if not is_runtime_file_attachment_integrity_error(exc):
                raise
            raise ConflictException(
                "Runtime file is already attached to a flow run.",
                code=FlowApiErrorCode.RUNTIME_FILE_ATTACHED.value,
                context={
                    "flow_id": str(published.flow_id),
                    "file_id": str(file_id),
                },
            ) from exc

    async def _upload_with_policy(
        self,
        *,
        flow_id: UUID,
        step_id: UUID,
        upload_file: UploadFile,
        policy: FlowFileInputPolicy,
    ) -> File:
        max_size = await self._validate_upload_with_policy(
            flow_id=flow_id,
            upload_file=upload_file,
            policy=policy,
        )

        try:
            async with self._write_transaction():
                file = await self.file_service.save_file(upload_file, max_size=max_size)
                await self.runtime_upload_repo.create(
                    file_id=file.id,
                    flow_id=flow_id,
                    tenant_id=self.user.tenant_id,
                    uploaded_for_step_id=step_id,
                    principal=self._principal(),
                )
                return file
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
            raise FlowBadRequestException(
                "Uploaded file is empty.",
                code=FlowApiErrorCode.RUNTIME_FILE_EMPTY,
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
