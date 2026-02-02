"""Audit export service for CSV and JSONL exports.

This service handles all export operations for audit logs, including:
- In-memory CSV/JSONL exports for small datasets
- Streaming exports to file for large datasets
- Progress tracking and cancellation support

Extracted from AuditService to improve single responsibility and testability.
"""

import csv
import logging
import os
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Optional
from uuid import UUID, uuid4

import aiofiles
import orjson

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.repositories.audit_log_repository import AuditLogRepository
from intric.main.config import get_settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ExportTooLargeError(Exception):
    """Raised when in-memory export exceeds safety limit.

    In-memory exports (export_csv, export_jsonl) buffer the entire result set
    in memory. For large datasets, use streaming exports (export_csv_stream,
    export_jsonl_stream) or set max_records parameter.
    """

    def __init__(self, record_count: int, limit: int):
        self.record_count = record_count
        self.limit = limit
        super().__init__(
            f"In-memory export exceeds {limit:,} records ({record_count:,} found). "
            f"Use streaming export methods or pass max_records parameter."
        )


# CSV header row - defined once for consistency across all export methods
CSV_HEADERS = [
    "Timestamp",
    "Actor ID",
    "Actor Type",
    "Action",
    "Entity Type",
    "Entity ID",
    "Description",
    "Outcome",
    "Error Message",
    "Metadata",
]


def _sanitize_csv_cell(value: str) -> str:
    """
    Prevent CSV injection attacks.

    Prefixes values starting with special characters (=, +, -, @, tab, carriage return)
    with a single quote to prevent formula execution in Excel and other spreadsheet software.

    Args:
        value: Cell value to sanitize

    Returns:
        Sanitized cell value
    """
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _orjson_default(obj: Any) -> Any:
    """
    Default handler for orjson serialization of non-standard types.

    Handles types that orjson cannot serialize natively:
    - UUID: Converted to string representation
    - Enum: Uses .value attribute
    - datetime/date/time: ISO 8601 format via .isoformat()
    - Decimal: String representation (preserves precision)
    - bytes: Decoded as latin1 (lossless for all byte values)
    - Path: String representation of path

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation

    Raises:
        TypeError: If object type is not handled
    """
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("latin1")
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class AuditExportService:
    """Service for audit log export operations.

    Handles CSV and JSONL exports with support for:
    - Small in-memory exports (export_csv, export_jsonl)
    - Large streaming exports to file (stream_export_to_file)
    - Progress tracking and cancellation for background jobs
    """

    # Batch size for yielding: ~1000 rows reduces async context-switching overhead
    # while maintaining memory efficiency. Gemini 3 Pro validated this approach.
    STREAM_BATCH_SIZE = 1000

    # Safety limit for in-memory exports to prevent OOM.
    # Exports exceeding this raise ExportTooLargeError unless max_records is set.
    EXPORT_MEMORY_LIMIT = 100_000

    def __init__(self, repository: AuditLogRepository):
        """Initialize export service.

        Args:
            repository: Audit log repository for data access
        """
        self.repository = repository

    def _get_log_stream(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        batch_size: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        """Get appropriate log stream based on user_id vs actor_id filtering.

        Centralizes log stream selection logic to avoid 4x code duplication.
        Uses stream_user_logs_raw for GDPR exports (user as actor OR target),
        otherwise uses stream_logs_raw for standard filtering.

        Args:
            tenant_id: Tenant ID for multi-tenancy isolation
            user_id: GDPR export filter (user as actor OR target entity)
            actor_id: Filter by actor (ignored if user_id is set)
            action: Filter by action type (ignored if user_id is set)
            from_date: Filter from date
            to_date: Filter to date
            batch_size: Optional batch size for cursor yielding

        Returns:
            AsyncIterator yielding raw log dicts from SQLAlchemy Core
        """
        if user_id:
            if batch_size is None:
                return self.repository.stream_user_logs_raw(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    from_date=from_date,
                    to_date=to_date,
                )
            return self.repository.stream_user_logs_raw(
                tenant_id=tenant_id,
                user_id=user_id,
                from_date=from_date,
                to_date=to_date,
                batch_size=batch_size,
            )
        if batch_size is None:
            return self.repository.stream_logs_raw(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                from_date=from_date,
                to_date=to_date,
            )
        return self.repository.stream_logs_raw(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
            batch_size=batch_size,
        )

    async def _get_total_count(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> int:
        """Get total count for the appropriate filter type.

        Centralizes count logic to avoid 2x code duplication.

        Args:
            tenant_id: Tenant ID for multi-tenancy isolation
            user_id: GDPR export filter (user as actor OR target entity)
            actor_id: Filter by actor (ignored if user_id is set)
            action: Filter by action type (ignored if user_id is set)
            from_date: Filter from date
            to_date: Filter to date

        Returns:
            Total count of matching records
        """
        if user_id:
            return await self.repository.count_user_logs(
                tenant_id=tenant_id,
                user_id=user_id,
                from_date=from_date,
                to_date=to_date,
            )
        return await self.repository.count_logs(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
        )

    def _raw_dict_to_csv_row(self, log_dict: dict) -> list:
        """Convert raw audit log dict to CSV row with sanitization.

        Used with stream_logs_raw() for optimized exports without ORM overhead.
        Handles both datetime objects (from asyncpg) and ISO strings (from tests).
        Metadata is serialized as JSON (not Python repr) for consistent parsing.
        """
        # Handle datetime objects from SQLAlchemy Core (asyncpg returns native datetime)
        ts = log_dict["timestamp"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()

        # Serialize metadata as JSON for consistent output format
        # Use orjson with _orjson_default to handle UUID/Decimal/datetime in metadata
        metadata = log_dict.get("metadata", {})
        metadata_json = (
            orjson.dumps(metadata, default=_orjson_default).decode("utf-8")
            if metadata
            else "{}"
        )

        # Handle None description - use explicit None check to preserve empty strings
        description = log_dict.get("description")
        description_value = description if description is not None else ""
        actor_id_value = log_dict.get("actor_id") or ""

        return [
            ts,
            actor_id_value,
            log_dict["actor_type"],
            log_dict["action"],
            log_dict["entity_type"],
            log_dict["entity_id"],
            _sanitize_csv_cell(description_value),
            log_dict["outcome"],
            _sanitize_csv_cell(log_dict.get("error_message") or ""),
            _sanitize_csv_cell(metadata_json),
        ]

    async def export_csv(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        max_records: Optional[int] = None,
    ) -> str:
        """
        Export audit logs to CSV format using streaming for memory efficiency.

        Uses repository stream iterators to prevent memory exhaustion.
        For datasets larger than EXPORT_MEMORY_LIMIT, raises ExportTooLargeError
        unless max_records is specified.

        Args:
            tenant_id: Tenant ID
            user_id: Filter for GDPR export (user as actor OR target)
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            max_records: Maximum number of records to export (None for unlimited)

        Returns:
            CSV string with audit logs

        Raises:
            ExportTooLargeError: If record count exceeds EXPORT_MEMORY_LIMIT
                and max_records is not set or exceeds limit
        """
        # OOM protection: validate max_records doesn't bypass limit
        if max_records is not None and max_records > self.EXPORT_MEMORY_LIMIT:
            raise ExportTooLargeError(max_records, self.EXPORT_MEMORY_LIMIT)

        # OOM protection: check count first if no max_records limit
        if max_records is None:
            total_count = await self._get_total_count(
                tenant_id=tenant_id,
                user_id=user_id,
                actor_id=actor_id,
                action=action,
                from_date=from_date,
                to_date=to_date,
            )
            if total_count > self.EXPORT_MEMORY_LIMIT:
                raise ExportTooLargeError(total_count, self.EXPORT_MEMORY_LIMIT)

        output = StringIO()
        writer = csv.writer(output)

        # Write header using module constant for consistency
        writer.writerow(CSV_HEADERS)

        # Stream logs using helper
        log_stream = self._get_log_stream(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
        )

        total_exported = 0
        async for log in log_stream:
            writer.writerow(self._raw_dict_to_csv_row(log))
            total_exported += 1

            # Check max_records limit
            if max_records and total_exported >= max_records:
                break

        return output.getvalue()

    async def export_jsonl(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        max_records: Optional[int] = None,
    ) -> str:
        """
        Export audit logs to JSON Lines (JSONL) format using streaming.

        JSONL is ideal for large exports as it:
        - Maintains data types (no string conversion)
        - Streams efficiently line-by-line
        - Is machine-readable and easily parsable
        - Works well with log analysis tools (jq, grep, etc.)

        Uses orjson for performance and datetime handling (stdlib json
        cannot serialize datetime objects).

        Args:
            tenant_id: Tenant ID
            user_id: Filter for GDPR export (user as actor OR target)
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            max_records: Maximum number of records to export (None for unlimited)

        Returns:
            JSONL string with one JSON object per line

        Raises:
            ExportTooLargeError: If record count exceeds EXPORT_MEMORY_LIMIT
                and max_records is not set or exceeds limit
        """
        # OOM protection: validate max_records doesn't bypass limit
        if max_records is not None and max_records > self.EXPORT_MEMORY_LIMIT:
            raise ExportTooLargeError(max_records, self.EXPORT_MEMORY_LIMIT)

        # OOM protection: check count first if no max_records limit
        if max_records is None:
            total_count = await self._get_total_count(
                tenant_id=tenant_id,
                user_id=user_id,
                actor_id=actor_id,
                action=action,
                from_date=from_date,
                to_date=to_date,
            )
            if total_count > self.EXPORT_MEMORY_LIMIT:
                raise ExportTooLargeError(total_count, self.EXPORT_MEMORY_LIMIT)

        output = StringIO()

        # Stream logs using helper
        log_stream = self._get_log_stream(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
        )

        total_exported = 0
        async for log in log_stream:
            # Use orjson for datetime support (stdlib json cannot serialize datetime)
            output.write(
                orjson.dumps(log, default=_orjson_default).decode("utf-8") + "\n"
            )
            total_exported += 1

            # Check max_records limit
            if max_records and total_exported >= max_records:
                break

        return output.getvalue()

    # =========================================================================
    # Generator-based exports for StreamingResponse (memory-safe)
    # =========================================================================

    async def export_csv_stream(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        max_records: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Generator-based CSV export for FastAPI StreamingResponse.

        Yields CSV content in batches (~1000 rows) to reduce async overhead
        while maintaining constant memory usage. Use with StreamingResponse
        for memory-safe exports of any dataset size.

        Args:
            tenant_id: Tenant ID
            user_id: Filter for GDPR export (user as actor OR target)
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            max_records: Maximum number of records to export (None for unlimited)

        Yields:
            CSV content chunks (header + batched rows)
        """
        # Yield header first
        header_output = StringIO()
        writer = csv.writer(header_output)
        writer.writerow(CSV_HEADERS)
        yield header_output.getvalue()

        # Get log stream using helper
        log_stream = self._get_log_stream(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
        )

        # Batch rows to reduce async context-switching overhead
        batch: list = []
        total_exported = 0

        async for log in log_stream:
            batch.append(self._raw_dict_to_csv_row(log))
            total_exported += 1

            # Yield batch when full
            if len(batch) >= self.STREAM_BATCH_SIZE:
                batch_output = StringIO()
                batch_writer = csv.writer(batch_output)
                batch_writer.writerows(batch)
                yield batch_output.getvalue()
                batch.clear()

            # Check max_records limit
            if max_records and total_exported >= max_records:
                break

        # Yield remaining rows
        if batch:
            batch_output = StringIO()
            batch_writer = csv.writer(batch_output)
            batch_writer.writerows(batch)
            yield batch_output.getvalue()

    async def export_jsonl_stream(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        max_records: Optional[int] = None,
    ) -> AsyncIterator[bytes]:
        """
        Generator-based JSONL export for FastAPI StreamingResponse.

        Yields JSONL content in batches (~1000 rows) as bytes to reduce async
        overhead while maintaining constant memory usage. Use with StreamingResponse
        for memory-safe exports of any dataset size.

        Args:
            tenant_id: Tenant ID
            user_id: Filter for GDPR export (user as actor OR target)
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            max_records: Maximum number of records to export (None for unlimited)

        Yields:
            JSONL content chunks as bytes (batched JSON lines)
        """
        # Get log stream using helper
        log_stream = self._get_log_stream(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
        )

        # Batch rows to reduce async context-switching overhead
        batch: list = []
        total_exported = 0

        async for log in log_stream:
            batch.append(log)
            total_exported += 1

            # Yield batch when full - yield bytes directly (no decode overhead)
            if len(batch) >= self.STREAM_BATCH_SIZE:
                chunk = (
                    b"\n".join(
                        orjson.dumps(item, default=_orjson_default) for item in batch
                    )
                    + b"\n"
                )
                yield chunk
                batch.clear()

            # Check max_records limit
            if max_records and total_exported >= max_records:
                break

        # Yield remaining rows
        if batch:
            chunk = (
                b"\n".join(
                    orjson.dumps(item, default=_orjson_default) for item in batch
                )
                + b"\n"
            )
            yield chunk

    async def stream_export_to_file(
        self,
        file_path: str,
        tenant_id: UUID,
        format: str,
        progress_callback: Callable[[int, int], Awaitable[None]],
        cancellation_check: Callable[[], Awaitable[bool]],
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        max_records: Optional[int] = None,
    ) -> int:
        """
        Stream export audit logs to file with progress tracking and cancellation.

        Uses server-side cursors for constant memory usage (~50MB) regardless
        of dataset size. Supports both CSV and JSONL formats.

        Args:
            file_path: Absolute path to output file
            tenant_id: Tenant ID for multi-tenant isolation
            format: Export format ('csv' or 'jsonl')
            progress_callback: Async callback(processed, total) for progress updates
            cancellation_check: Async callback() returning True if job should cancel
            user_id: GDPR export filter (user as actor OR target)
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            max_records: Maximum records to export (None for unlimited)

        Returns:
            Total number of records exported

        Raises:
            ValueError: If format is not 'csv' or 'jsonl'
        """
        # Validate format before processing
        if format not in ("csv", "jsonl"):
            raise ValueError(
                f"Unsupported export format: {format}. Use 'csv' or 'jsonl'."
            )

        # Settings bounds validation to prevent memory spikes from misconfiguration
        MAX_BUFFER_SIZE = 10_000
        MAX_BATCH_SIZE = 5_000
        MIN_BUFFER_SIZE = 1
        MIN_BATCH_SIZE = 1
        MIN_PROGRESS_INTERVAL = 1

        settings = get_settings()
        # Clamp settings to reasonable bounds (min <= value <= max)
        batch_size = max(
            MIN_BATCH_SIZE, min(settings.export_batch_size or 1000, MAX_BATCH_SIZE)
        )
        buffer_size = max(
            MIN_BUFFER_SIZE, min(settings.export_buffer_size or 1000, MAX_BUFFER_SIZE)
        )
        # Guard against division-by-zero if progress_interval is 0 or None
        progress_interval = max(
            settings.export_progress_interval or 100, MIN_PROGRESS_INTERVAL
        )

        # Get total count for progress calculation using helper
        total_records = await self._get_total_count(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
        )

        # Apply max_records limit to total
        if max_records and total_records > max_records:
            total_records = max_records

        processed = 0
        buffer: list = []
        cancelled = False  # Track cancellation to handle cleanup after file closes

        # Use atomic file write pattern: write to temp file, then rename
        # This prevents partial/corrupted files on crash or cancellation
        # Use UUID in temp path to prevent concurrent export collisions
        temp_path = f"{file_path}.{uuid4().hex}.tmp"

        try:
            async with aiofiles.open(temp_path, mode="wb") as file:
                # Write CSV header if needed using module constant for consistency
                if format == "csv":
                    header_output = StringIO()
                    writer = csv.writer(header_output)
                    writer.writerow(CSV_HEADERS)
                    await file.write(header_output.getvalue().encode("utf-8"))

                # Stream logs from repository using raw dicts (SQLAlchemy Core)
                # ~2-3x faster than ORM streaming by bypassing hydration + domain conversion
                log_stream = self._get_log_stream(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    actor_id=actor_id,
                    action=action,
                    from_date=from_date,
                    to_date=to_date,
                    batch_size=batch_size,
                )

                async for log in log_stream:
                    # Check cancellation periodically with exception handling
                    if processed % progress_interval == 0:
                        # Cancellation check with graceful error handling
                        try:
                            if await cancellation_check():
                                logger.info(
                                    "Export cancelled",
                                    extra={
                                        "tenant_id": str(tenant_id),
                                        "processed": processed,
                                    },
                                )
                                # Flush remaining buffer before exit
                                if buffer:
                                    await self._flush_buffer(file, buffer, format)
                                # Set cancelled flag - delete temp file AFTER async with closes
                                # (Windows cannot delete open files)
                                cancelled = True
                                break
                        except Exception as e:
                            logger.warning(f"Cancellation check failed: {e}")
                            # Continue export on callback error

                        # Progress callback with graceful error handling
                        try:
                            await progress_callback(processed, total_records)
                        except Exception as e:
                            logger.warning(f"Progress callback failed: {e}")
                            # Continue export on callback error

                    # Add to buffer - log is already a dict from raw streaming
                    if format == "csv":
                        buffer.append(self._raw_dict_to_csv_row(log))
                    else:  # jsonl
                        buffer.append(log)  # Already a dict, no conversion needed

                    processed += 1

                    # Check max_records limit
                    if max_records and processed >= max_records:
                        break

                    # Flush buffer when full
                    if len(buffer) >= buffer_size:
                        await self._flush_buffer(file, buffer, format)
                        buffer.clear()

                # Flush remaining buffer (skip if cancelled - already flushed in cancellation block)
                if buffer and not cancelled:
                    await self._flush_buffer(file, buffer, format)

            # Handle cancellation after file is closed (safe to delete on all platforms)
            if cancelled:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return processed

            # Atomic rename: only after successful write
            os.replace(temp_path, file_path)

        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

        # Final progress update with exception handling
        try:
            await progress_callback(processed, total_records)
        except Exception as e:
            logger.warning(f"Final progress callback failed: {e}")

        logger.info(
            "Export completed",
            extra={
                "tenant_id": str(tenant_id),
                "format": format,
                "total_records": processed,
                "file_path": file_path,
            },
        )

        return processed

    async def _flush_buffer(
        self,
        file: aiofiles.threadpool.binary.AsyncBufferedIOBase,
        buffer: list,
        format: str,
    ) -> None:
        """Flush buffer to file with format-specific serialization."""
        if format == "csv":
            # Use StringIO + writerows for efficient CSV batch writing
            output = StringIO()
            writer = csv.writer(output)
            writer.writerows(buffer)  # writerows is faster than loop
            await file.write(output.getvalue().encode("utf-8"))
        else:  # jsonl
            # Batch serialize with join - O(n) instead of O(n²) concatenation
            # Memory: ~45-50MB temporary allocation for 50k records, acceptable trade-off
            chunk = (
                b"\n".join(
                    orjson.dumps(item, default=_orjson_default) for item in buffer
                )
                + b"\n"
            )
            await file.write(chunk)
