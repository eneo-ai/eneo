from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from eneo.files.file_models import FileContentVariant, FileInfo, FileType
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    select_binary_file_reference,
)
from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.runtime import InputFileSize
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_input_limits import effective_upload_ceiling_bytes

if TYPE_CHECKING:
    from eneo.files.file_models import File
    from eneo.files.file_service import FileService

_RuntimeFile = TypeVar("_RuntimeFile", "File", "FileInfo")


def measure_input_files(
    *, files: Sequence[FileInfo], references: list[FileContentReferenceRecord]
) -> dict[UUID, InputFileSize]:
    sizes_by_file: dict[UUID, dict[FileContentVariant, int]] = {}
    references_by_file: dict[UUID, list[FileContentReferenceRecord]] = {}
    for reference in references:
        references_by_file.setdefault(reference.file_id, []).append(reference)
        variants = sizes_by_file.setdefault(reference.file_id, {})
        variants[reference.variant] = (
            variants.get(reference.variant, 0) + reference.size_bytes
        )
    sizes: dict[UUID, InputFileSize] = {}
    for file in files:
        variants = sizes_by_file.get(file.id, {})
        original_size = variants.get(FileContentVariant.ORIGINAL, file.size)
        selected_binary = select_binary_file_reference(
            file.file_type, references_by_file.get(file.id, [])
        )
        binary_size = selected_binary.size_bytes if selected_binary else file.size
        inline_size = variants.get(
            FileContentVariant.EXTRACTED_TEXT,
            file.size if file.file_type == FileType.TEXT else 0,
        )
        mimetype = (file.mimetype or "").split(";", 1)[0].strip().lower()
        plain_text = mimetype.startswith("text/") or mimetype in {
            "application/json",
            "application/xml",
        }
        sizes[file.id] = InputFileSize(
            inline_bytes=inline_size,
            binary_bytes=0 if plain_text else binary_size,
            upload_bytes=original_size,
            audio=file.file_type == FileType.AUDIO,
        )
    return sizes


def ensure_input_file_budget(
    *,
    file_ids: Sequence[UUID],
    sizes: Mapping[UUID, InputFileSize],
    max_inline_text_bytes: int,
    file_max_size_bytes: int,
    audio_max_size_bytes: int,
    inline_payload: object = None,
) -> None:
    inline_bytes = (
        len(canonical_json_bytes(inline_payload)) if inline_payload is not None else 0
    )
    binary_bytes = 0
    audio_bytes = 0
    for file_id in file_ids:
        size = sizes[file_id]
        inline_bytes += size.inline_bytes
        if size.audio:
            audio_bytes += size.binary_bytes
        else:
            binary_bytes += size.binary_bytes
    for kind, measured, ceiling in (
        ("inline_text", inline_bytes, max_inline_text_bytes),
        ("binary", binary_bytes, effective_upload_ceiling_bytes(file_max_size_bytes)),
        ("binary", audio_bytes, effective_upload_ceiling_bytes(audio_max_size_bytes)),
    ):
        if measured > ceiling:
            raise FlowBadRequestException(
                "The aggregate run input exceeds the input byte ceiling.",
                code=FlowApiErrorCode.RUN_INPUT_EXCEEDS_LIMIT,
                context={"kind": kind, "measured": measured, "ceiling": ceiling},
            )


async def load_files_by_requested_ids(
    *,
    file_service: FileService,
    requested_ids: list[UUID],
    file_cache: dict[frozenset[UUID], list["File"]] | None = None,
) -> list["File"]:
    cache_key = frozenset(requested_ids)
    if file_cache is not None and cache_key in file_cache:
        return _order_files_by_requested_ids(
            files=file_cache[cache_key],
            requested_ids=requested_ids,
        )
    files = await file_service.get_files_by_ids(
        file_ids=requested_ids,
        include_transcription=True,
    )
    if file_cache is not None:
        file_cache[cache_key] = files
    return _order_files_by_requested_ids(files=files, requested_ids=requested_ids)


async def describe_files_by_requested_ids(
    *,
    file_service: FileService,
    requested_ids: list[UUID],
) -> list["FileInfo"]:
    """Identify run input files without reading their bytes.

    Audio steps use this and read each payload only while that file is being
    transcribed, so a run's memory cost is one audio file rather than every file
    the step requested. Deliberately uncached: identities are cheap, and a cache
    entry here must never be mistaken for one carrying content.
    """
    described = await file_service.get_owned_file_infos(file_ids=requested_ids)
    return _order_files_by_requested_ids(
        files=described,
        requested_ids=requested_ids,
    )


def _order_files_by_requested_ids(
    *, files: list[_RuntimeFile], requested_ids: list[UUID]
) -> list[_RuntimeFile]:
    file_by_id = {file.id: file for file in files}
    return [
        file_by_id[file_id]
        for file_id in dict.fromkeys(requested_ids)
        if file_id in file_by_id
    ]
