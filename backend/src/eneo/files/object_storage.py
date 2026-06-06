"""S3-compatible object storage for original uploaded file bytes.

Eneo's file processor extracts text from documents on upload and drops the
original bytes (only images/audio keep a ``blob``). That leaves Eneo unable to
hand a downstream consumer (an MCP tool's URL input) the real PDF/DOCX/CSV. When
an S3-compatible store is configured, ``save_file`` streams the original bytes
here and persists the returned key on ``files.storage_key``; the signed download
endpoint later streams the bytes back.

Generic by design: any tool can consume the signed URL Eneo mints over these
objects. The store is private — bytes are only reachable through Eneo's
signed-URL proxy, never via a public bucket URL.

Everything degrades gracefully: when the store is not configured the methods are
inert (``is_configured()`` is False and callers skip the upload), and an upload
failure raises ``ObjectStorageError`` which the caller turns into a NULL
``storage_key`` rather than a failed upload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

import aioboto3  # pyright: ignore[reportMissingTypeStubs]  # no stubs published for aioboto3
from botocore.config import (  # pyright: ignore[reportMissingTypeStubs]  # no stubs for botocore
    Config as BotoConfig,
)

from eneo.main.config import get_settings
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.main.config import Settings

logger = get_logger(__name__)

# Stream objects back in ~1 MiB chunks so a large download never materializes
# fully in memory on the Eneo side.
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class ObjectStorageError(Exception):
    """Raised when an object-storage operation fails (transport/HTTP/config)."""


class FileObjectStorage:
    """Thin async wrapper over an S3-compatible store via aioboto3."""

    def __init__(self, settings: "Settings | None" = None):
        # The DI container's config provider is never initialized, so default to
        # the module settings singleton (mirrors CompletionService's pattern).
        self._settings = settings or get_settings()
        self._bucket = self._settings.file_storage_s3_bucket

    def is_configured(self) -> bool:
        """True only when every value needed to reach the store is set."""
        s = self._settings
        return bool(
            s.file_storage_s3_endpoint_url
            and s.file_storage_s3_bucket
            and s.file_storage_s3_access_key
            and s.file_storage_s3_secret_key
        )

    def _client(self) -> Any:
        # aioboto3 ships no type stubs, so the client is dynamically typed.
        # Returning Any keeps the unknown-type cascade out of the call sites.
        s = self._settings
        addressing = "path" if s.file_storage_s3_use_path_style else "auto"
        session: Any = aioboto3.Session()
        config: Any = BotoConfig(s3={"addressing_style": addressing})
        return session.client(
            "s3",
            endpoint_url=s.file_storage_s3_endpoint_url,
            aws_access_key_id=s.file_storage_s3_access_key,
            aws_secret_access_key=s.file_storage_s3_secret_key,
            region_name=s.file_storage_s3_region,
            config=config,
        )

    async def upload(self, key: str, data: bytes, content_type: Optional[str]) -> None:
        """Put ``data`` at ``key``. Raises ObjectStorageError on failure."""
        if not self.is_configured():
            raise ObjectStorageError("Object storage is not configured")
        try:
            async with self._client() as client:
                await client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type or "application/octet-stream",
                )
        except Exception as exc:  # noqa: BLE001 - normalize SDK/transport errors
            raise ObjectStorageError(f"Failed to upload object {key}: {exc}") from exc

    async def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """Yield the object's bytes in chunks. Raises ObjectStorageError.

        The aioboto3 client context is kept open for the lifetime of the
        generator so the streaming body stays readable while chunks are pulled.
        """
        if not self.is_configured():
            raise ObjectStorageError("Object storage is not configured")
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self._bucket, Key=key)
                # The aiobotocore streaming body exposes chunked iteration via
                # iter_chunks(); its read() does not take a size argument.
                async for chunk in response["Body"].iter_chunks(_DOWNLOAD_CHUNK_SIZE):
                    yield chunk
        except ObjectStorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize SDK/transport errors
            raise ObjectStorageError(f"Failed to read object {key}: {exc}") from exc

    async def delete(self, key: str) -> None:
        """Best-effort delete; logs and swallows failures (never raises)."""
        if not self.is_configured() or not key:
            return
        try:
            async with self._client() as client:
                await client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.warning("[file-storage] failed to delete object %s: %s", key, exc)
