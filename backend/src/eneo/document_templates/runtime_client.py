"""What the bundled tool runtime does for templates outside tool calls.

Inspection (which fields and styles a template has) and the built-in template
both come from the runtime, so the one implementation of the Word conventions
lives there. Both are bounded, bearer-authenticated calls to the runtime's
own routes; neither is on a tool execution path.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

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
    name: str = Field(max_length=200)
    syntax: str = Field(max_length=16)
    kind: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=500)
    hint: str | None = Field(default=None, max_length=2000)
    location: str = Field(max_length=16)
    supported: bool
    reason: str | None = Field(default=None, max_length=500)


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
                response = await client.post(
                    f"{base}/templates/inspect",
                    content=template,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/octet-stream",
                    },
                )
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
