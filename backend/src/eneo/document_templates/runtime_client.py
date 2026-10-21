"""What the bundled tool runtime does for templates outside tool calls.

Inspection (which fields and styles a template has) and the built-in template
both come from the runtime, so the one implementation of the Word conventions
lives there. Both are bounded, bearer-authenticated calls to the runtime's
own routes; neither is on a tool execution path.
"""

from __future__ import annotations

import asyncio
import base64
import random
from typing import Any, Literal, cast

import httpx
from pydantic import BaseModel, Field, ValidationError

from eneo.document_templates.domain import TemplateInspection
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 20
_MAX_BUILTIN_BYTES = 2 * 1024 * 1024


class RuntimeUnavailable(Exception):
    """The runtime is not configured or did not answer."""


class _Placeholder(BaseModel):
    name: str = Field(max_length=1000)
    syntax: str = Field(max_length=16)
    kind: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=500)
    hint: str | None = Field(default=None, max_length=2000)
    location: str = Field(max_length=16)
    section_heading: str | None = Field(default=None, max_length=200)
    heading_level: int | None = Field(default=None, ge=0, le=9)
    container: str | None = Field(default=None, max_length=16)
    in_table: bool | None = None
    multiline: bool | None = None
    supported: bool
    reason: str | None = Field(default=None, max_length=500)
    reason_code: str | None = Field(default=None, max_length=32)


class _Check(BaseModel):
    ok: bool
    detail: str = Field(max_length=500)


class _Report(BaseModel):
    syntax: str = Field(max_length=16)
    placeholders: list[_Placeholder] = Field(
        default_factory=list[_Placeholder], max_length=256
    )
    checks: dict[str, _Check] = Field(default_factory=dict[str, _Check])
    language: str | None = Field(default=None, max_length=64)


def configured() -> bool:
    """Whether a tool runtime is configured to inspect templates."""
    return _runtime() is not None


def _runtime() -> tuple[str, str] | None:
    settings = get_settings()
    base = str(settings.tool_runtime_url or "").rstrip("/")
    token = settings.tool_runtime_token or ""
    return (base, token) if base and token else None


async def inspect_template(template: bytes) -> TemplateInspection | None:
    """The runtime's reading of a template, or None when no runtime is configured.

    A template the runtime refuses (not a Word file, macros) raises a
    BadRequestException with the runtime's message.
    """
    runtime = _runtime()
    if runtime is None:
        return None
    base, token = runtime
    try:
        async with asyncio.timeout(_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS, trust_env=False, follow_redirects=False
            ) as client:
                attempt = 0
                while True:
                    response = await client.post(
                        f"{base}/templates/inspect",
                        content=template,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/octet-stream",
                        },
                    )
                    if response.status_code != 429 or not await _wait_out_busy(attempt):
                        break
                    attempt += 1
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("Template inspection failed: runtime unreachable (%s)", exc)
        raise RuntimeUnavailable() from exc
    if response.status_code == 422:
        message = "The template could not be read."
        try:
            payload = cast(dict[str, Any], response.json())
            message = str(payload.get("message") or message)[:500]
        except ValueError:
            pass
        raise BadRequestException(message)
    if response.status_code != 200:
        logger.warning(
            "Template inspection failed: runtime answered %s", response.status_code
        )
        raise RuntimeUnavailable()
    try:
        report = _Report.model_validate(response.json())
    except (ValidationError, ValueError) as exc:
        logger.warning("Template inspection returned an unreadable report: %s", exc)
        raise RuntimeUnavailable() from exc
    syntax = (
        report.syntax
        if report.syntax in ("controls", "braces", "mixed", "none")
        else "unknown"
    )
    return TemplateInspection(
        syntax=cast(Any, syntax),
        placeholders=[p.model_dump(exclude_none=True) for p in report.placeholders],
        checks={name: check.model_dump() for name, check in report.checks.items()},
        language=report.language,
    )


async def builtin_template(language: str) -> bytes:
    """Eneo's built-in template as the runtime builds it."""
    runtime = _runtime()
    if runtime is None:
        raise RuntimeUnavailable()
    base, token = runtime
    try:
        async with asyncio.timeout(_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream(
                    "GET",
                    f"{base}/templates/builtin.docx",
                    params={"language": language},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    if response.status_code != 200:
                        raise RuntimeUnavailable()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > _MAX_BUILTIN_BYTES:
                            raise RuntimeUnavailable()
                        chunks.append(chunk)
                    return b"".join(chunks)
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise RuntimeUnavailable() from exc


_DOCX_MIMETYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_PDF_MIMETYPE = "application/pdf"
_RENDER_TIMEOUT_SECONDS = 90
_MAX_RENDERED_BYTES = 20 * 1024 * 1024
# The runtime serves a few template and document requests at once and answers
# 429 to the rest; a busy answer is retried after these pauses.
_BUSY_RETRY_SECONDS = (0.2, 0.5, 1.0, 2.0)


async def _wait_out_busy(attempt: int) -> bool:
    """Pause before retrying a busy runtime; False once the retries are spent."""
    if attempt >= len(_BUSY_RETRY_SECONDS):
        return False
    await asyncio.sleep(_BUSY_RETRY_SECONDS[attempt] * (1 + random.random() / 2))
    return True


async def render_document(
    *,
    content: str = "",
    title: str = "",
    output_type: str = "docx",
    template: bytes | None = None,
    values: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    """Render Markdown, or fill a Word template's fields, in the runtime.

    The request carries content and template bytes, never file URLs or local
    paths; the credential stays on the backend-to-runtime connection. A
    rendering the runtime refuses raises BadRequestException.
    """
    runtime = _runtime()
    if runtime is None:
        raise RuntimeUnavailable("The document runtime is not configured.")
    if output_type not in {"docx", "pdf"} or (
        values is not None and output_type != "docx"
    ):
        raise BadRequestException("Unsupported document format.")
    payload: dict[str, Any] = {
        "mode": "fill" if values is not None else "render",
        "format": output_type,
    }
    if values is None:
        payload.update(content=content, title=title, language="sv", include_title=False)
    else:
        payload["values"] = values
    if template is not None:
        payload["template"] = base64.b64encode(template).decode("ascii")
    expected = _PDF_MIMETYPE if output_type == "pdf" else _DOCX_MIMETYPE
    base, token = runtime
    try:
        async with asyncio.timeout(_RENDER_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=_RENDER_TIMEOUT_SECONDS,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                attempt = 0
                while True:
                    rendered = await _render_once(
                        client, f"{base}/documents/render", token, payload, expected
                    )
                    if rendered is not None:
                        return rendered, expected
                    if not await _wait_out_busy(attempt):
                        raise RuntimeUnavailable("The document runtime is busy.")
                    attempt += 1
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise RuntimeUnavailable("The document runtime is unavailable.") from exc


async def _render_once(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    payload: dict[str, Any],
    expected: str,
) -> bytes | None:
    """The rendered bytes, or None when the runtime is busy."""
    async with client.stream(
        "POST", url, json=payload, headers={"Authorization": f"Bearer {token}"}
    ) as response:
        if response.status_code == 429:
            return None
        if response.status_code == 422:
            raise BadRequestException(
                "The document or template could not be rendered within its limits."
            )
        if response.status_code != 200:
            raise RuntimeUnavailable(
                "The document runtime did not complete the request."
            )
        if response.headers.get("content-type", "").split(";", 1)[0] != expected:
            raise RuntimeUnavailable(
                "The document runtime returned an unexpected format."
            )
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > _MAX_RENDERED_BYTES:
                raise BadRequestException(
                    "The generated document exceeds its size limit."
                )
            chunks.append(chunk)
        return b"".join(chunks)


async def ensure_document_runtime() -> None:
    """Verify the deterministic protocol before a caller allocates paid work."""
    runtime = _runtime()
    if runtime is None:
        raise RuntimeUnavailable("The document runtime is not configured.")
    base, token = runtime
    try:
        async with asyncio.timeout(5):
            async with httpx.AsyncClient(
                timeout=5, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream(
                    "GET",
                    base + "/documents/render",
                    headers={"Authorization": "Bearer " + token},
                ) as response:
                    if response.status_code != 200:
                        raise RuntimeUnavailable(
                            "The document runtime protocol is unavailable."
                        )
                    parts: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 16_384:
                            raise RuntimeUnavailable(
                                "The document runtime protocol is invalid."
                            )
                        parts.append(chunk)
                    protocol = _DocumentProtocol.model_validate_json(b"".join(parts))
                    if (
                        set(protocol.formats) != {"docx", "pdf"}
                        or not protocol.template_fill
                    ):
                        raise RuntimeUnavailable(
                            "The document runtime protocol is unavailable."
                        )

    except (httpx.HTTPError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeUnavailable("The document runtime is unavailable.") from exc


class _DocumentProtocol(BaseModel):
    protocol: Literal[1]
    formats: list[Literal["docx", "pdf"]]
    template_fill: bool
