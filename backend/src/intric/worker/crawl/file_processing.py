from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from intric.worker.crawl.persistence import ExistingBlobState

ChangedFileProcessor = Callable[[Path, str, bytes], Awaitable[None]]
FileProcessingErrorRecorder = Callable[[Path, str, Exception], None]


class MissingFileEmbeddingModelError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FileProcessingResult:
    files_downloaded: int
    files_failed: int
    files_hash_retained: int
    cleanup_protected_titles: frozenset[str]
    failed_titles: frozenset[str]


async def process_files(
    *,
    files: Iterable[Path] | None,
    existing_blob_state_by_title: Mapping[str, ExistingBlobState],
    embedding_model_id: UUID | None,
    process_changed_file: ChangedFileProcessor,
    record_file_processing_error: FileProcessingErrorRecorder | None = None,
) -> FileProcessingResult:
    """Retained and processed files are cleanup-protected; failed files are not."""

    files_downloaded = 0
    files_failed = 0
    files_hash_retained = 0
    cleanup_protected_titles: set[str] = set()
    failed_titles: set[str] = set()

    for file in files or ():
        files_downloaded += 1
        filename = file.stem
        try:
            file_bytes = file.read_bytes()
            content_hash = hashlib.sha256(file_bytes).digest()
        except Exception as exc:
            if record_file_processing_error is not None:
                record_file_processing_error(file, filename, exc)
            files_failed += 1
            failed_titles.add(filename)
            continue

        existing_file_state = existing_blob_state_by_title.get(filename)

        if existing_file_state is not None and existing_file_state.is_current_for(
            content_hash=content_hash,
            embedding_model_id=embedding_model_id,
        ):
            files_hash_retained += 1
            cleanup_protected_titles.add(filename)
            continue

        if embedding_model_id is None:
            if record_file_processing_error is not None:
                record_file_processing_error(
                    file,
                    filename,
                    MissingFileEmbeddingModelError(
                        f"Cannot process changed file '{filename}' without an "
                        "embedding model"
                    ),
                )
            files_failed += 1
            failed_titles.add(filename)
            continue

        try:
            await process_changed_file(file, filename, content_hash)
        except Exception as exc:
            if record_file_processing_error is not None:
                record_file_processing_error(file, filename, exc)
            files_failed += 1
            failed_titles.add(filename)
            continue

        cleanup_protected_titles.add(filename)

    return FileProcessingResult(
        files_downloaded=files_downloaded,
        files_failed=files_failed,
        files_hash_retained=files_hash_retained,
        cleanup_protected_titles=frozenset(cleanup_protected_titles),
        failed_titles=frozenset(failed_titles),
    )
