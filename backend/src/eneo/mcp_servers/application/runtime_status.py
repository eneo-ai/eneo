"""Bounded, advisory diagnostics. Never consulted on the tool execution path."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError

from eneo.files.file_reference import file_reference_base_url
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)


RuntimeWarning = Literal[
    "version_mismatch",
    "revision_mismatch",
    "unverified",
    "confinement_unavailable",
    "file_origin_unreachable",
    "file_origin_not_allowed",
    "file_origin_unknown",
]
FILE_ORIGIN_WARNING: dict[str, RuntimeWarning] = {
    "unreachable": "file_origin_unreachable",
    "not_allowed": "file_origin_not_allowed",
    "unknown": "file_origin_unknown",
}


class RuntimeStatus(BaseModel):
    configured: bool = False
    state: Literal[
        "not_configured", "ready", "unreachable", "unauthorized", "unverified"
    ] = "not_configured"
    expected_version: str
    expected_revision: str = "unknown"
    version: str | None = None
    revision: str | None = None
    warnings: list[RuntimeWarning] = Field(default_factory=list[RuntimeWarning])
    files_confined: bool | None = None
    tcp_confined: bool | None = None
    file_origin: Literal["reachable", "unreachable", "not_allowed", "unknown"] = (
        "unknown"
    )
    active: int = 0
    queued: int = 0


class _Counts(BaseModel):
    active: int = Field(ge=0, le=256)
    queued: int = Field(ge=0, le=256)


class _Confinement(BaseModel):
    files: bool
    tcp: bool


class _Diagnostic(BaseModel):
    version: str = Field(max_length=128)
    revision: str = Field(max_length=64)
    confinement: _Confinement
    execution: _Counts
    file_origin: Literal["reachable", "unreachable", "not_allowed", "unknown"]


_cache: tuple[str, float, RuntimeStatus] | None = None
_lock = asyncio.Lock()


def compare_versions(
    expected: str, actual: str, expected_revision: str, actual_revision: str
) -> list[RuntimeWarning]:
    versions = [value.removeprefix("v") for value in (expected, actual)]
    unverified = any(
        value.lower() in ("dev", "unknown", "") or value.lower().endswith("-dev")
        for value in versions
    )
    warnings: list[RuntimeWarning] = (
        ["unverified"]
        if unverified
        else (["version_mismatch"] if versions[0] != versions[1] else [])
    )

    def known(value: str) -> bool:
        return len(value) == 40 and all(c in "0123456789abcdef" for c in value)

    if (
        known(expected_revision)
        and known(actual_revision)
        and expected_revision != actual_revision
    ):
        warnings.append("revision_mismatch")
    return warnings


async def runtime_status() -> RuntimeStatus:
    global _cache
    settings = get_settings()
    base = str(settings.tool_runtime_url or "").rstrip("/")
    token = settings.tool_runtime_token or ""
    file_base = file_reference_base_url(settings) or ""
    expected = settings.app_version
    revision = settings.app_revision
    key = hashlib.sha256(
        f"{base}\n{token}\n{file_base}\n{expected}\n{revision}".encode()
    ).hexdigest()
    async with _lock:
        if _cache and _cache[0] == key and time.monotonic() < _cache[1]:
            return _cache[2].model_copy(deep=True)
        status = RuntimeStatus(
            expected_version=expected,
            expected_revision=revision,
            configured=bool(base and token),
        )
        if status.configured:
            status.state = "unreachable"
            headers = {"Authorization": f"Bearer {token}"}
            if file_base:
                parsed = urlsplit(file_base)
                headers["X-Eneo-File-Origin"] = f"{parsed.scheme}://{parsed.netloc}"
            try:
                async with asyncio.timeout(3):
                    async with httpx.AsyncClient(
                        timeout=3, trust_env=False, follow_redirects=False
                    ) as client:
                        async with client.stream(
                            "GET", f"{base}/diagnostics", headers=headers
                        ) as response:
                            if response.status_code in (401, 403):
                                status.state = "unauthorized"
                            elif response.status_code == 404:
                                status.state = "unverified"
                                status.warnings = ["unverified"]
                            else:
                                response.raise_for_status()
                                body = bytearray()
                                async for chunk in response.aiter_bytes():
                                    body.extend(chunk)
                                    if len(body) > 32768:
                                        raise ValueError(
                                            "Oversized runtime diagnostics"
                                        )
                                data = _Diagnostic.model_validate_json(body)
                                status.state = "ready"
                                status.version, status.revision = (
                                    data.version,
                                    data.revision,
                                )
                                status.files_confined, status.tcp_confined = (
                                    data.confinement.files,
                                    data.confinement.tcp,
                                )
                                status.file_origin = data.file_origin
                                status.active, status.queued = (
                                    data.execution.active,
                                    data.execution.queued,
                                )
                                status.warnings = compare_versions(
                                    expected, data.version, revision, data.revision
                                )
                                if not data.confinement.files:
                                    status.warnings.append("confinement_unavailable")
                                if data.file_origin != "reachable":
                                    status.warnings.append(
                                        FILE_ORIGIN_WARNING[data.file_origin]
                                    )
            except (httpx.HTTPError, TimeoutError, ValidationError, ValueError):
                # Exception text can contain origins or credentials. Log only safe state.
                status.state = "unreachable"
            if status.warnings or status.state not in ("ready", "unverified"):
                logger.warning(
                    "Bundled runtime diagnostic",
                    extra={
                        "runtime_state": status.state,
                        "runtime_warnings": status.warnings,
                    },
                )
        _cache = (key, time.monotonic() + 30, status)
        return status.model_copy(deep=True)
