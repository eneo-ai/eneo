"""Push file bytes to an external file-storage service at upload time.

Eneo only persists extracted text for document uploads (PDFs, DOCX, ...).
That makes eneo unable to hand a downstream consumer (eg an MCP server's
``ingest_url`` tool) the *original* file. To bridge that gap we POST the
raw upload bytes to a dedicated storage service (today: the eneo-knowledge
file-storage feature, which lives on the same host as the eneo-knowledge
MCP but is itself NOT part of the MCP protocol) the moment a file is
uploaded, and persist the returned URL on the file row. Chat turns then
read ``file.storage_url`` directly — no per-turn upload, no need for eneo
to retain originals.

This module is decoupled from the MCP layer on purpose: the storage
service is a generic offering, any MCP server (or built-in tool) can
consume the URLs it returns.
"""

from __future__ import annotations

from typing import Any, cast

import httpx

from intric.main.config import get_settings
from intric.main.logging import get_logger

logger = get_logger(__name__)


# Stay under typical reverse-proxy idle-timeout windows but long enough to
# handle multi-megabyte PDFs over a slow link.
_UPLOAD_TIMEOUT_SECONDS = 30.0


def _extract_url(response: httpx.Response) -> str | None:
    """Pull the storage URL out of the response.

    Accept either JSON ``{"url"|"download_url"|"href": ...}`` or a bare
    URL string so eneo isn't pinned to one response shape.
    """
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        body_dict = cast(dict[str, Any], body)
        for key in ("url", "download_url", "href"):
            value = body_dict.get(key)
            if value:
                return str(value)
    text = response.text.strip()
    return text or None


async def upload_raw_to_storage(
    *,
    filename: str,
    mimetype: str | None,
    raw_bytes: bytes,
) -> str | None:
    """POST raw bytes to the configured storage service and return its URL.

    Returns ``None`` (with a warning logged) when:
    - storage is not configured (either URL or bearer missing)
    - the upload fails at transport or HTTP layer
    - the response carries no URL we can extract

    Knowledge host-scopes uploads (no session header sent) — files are
    visible to any MCP session on the same server.
    """
    settings = get_settings()
    storage_url = settings.file_storage_url
    bearer = settings.file_storage_bearer_token
    if not storage_url or not bearer:
        return None

    headers = {"Authorization": f"Bearer {bearer}"}
    files_payload = {
        "file": (filename, raw_bytes, mimetype or "application/octet-stream")
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                storage_url,
                headers=headers,
                files=files_payload,
                timeout=_UPLOAD_TIMEOUT_SECONDS,
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "[file-storage] upload of %s failed (transport): %s", filename, exc
        )
        return None

    if response.status_code >= 400:
        logger.warning(
            "[file-storage] upload of %s returned %d: %s",
            filename,
            response.status_code,
            response.text[:200],
        )
        return None

    url = _extract_url(response)
    if not url:
        logger.warning(
            "[file-storage] upload of %s succeeded but no URL in response",
            filename,
        )
        return None
    return url
