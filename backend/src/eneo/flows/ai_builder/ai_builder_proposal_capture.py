"""Env-gated capture tap for rejected proposal payloads.

When `ENEO_AI_BUILDER_REJECTED_PROPOSAL_CAPTURE_DIR` names a directory,
every proposal rejected at the parse, architecture, or quality boundary
is written there with its issues, and raw tool arguments that fail JSON
decoding are written as text. Repair loops can then be attributed
against the exact rejected shape. Off in normal operation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from eneo.main.logging import get_logger

logger = get_logger(__name__)

REJECTED_PROPOSAL_CAPTURE_DIR_ENV = "ENEO_AI_BUILDER_REJECTED_PROPOSAL_CAPTURE_DIR"


def capture_rejected_proposal_arguments(
    arguments: dict[str, Any],
    *,
    session_id: str,
    issues: list[str],
) -> None:
    _write_capture(
        prefix="rejected-proposal",
        payload={
            "session_id": session_id,
            "issues": issues,
            "arguments": arguments,
        },
    )


def capture_quality_rejected_spec(
    spec_payload: dict[str, Any],
    *,
    session_id: str,
    failure_codes: list[str],
) -> None:
    """Capture a compiled spec the quality critics rejected.

    Quality rejections happen after compilation, so the compiled spec —
    not the raw arguments — is the shape repair loops must be attributed
    against (a four-attempt runtime_metadata loop was unattributable
    without it, 2026-08-06).
    """

    _write_capture(
        prefix="quality-rejected-spec",
        payload={
            "session_id": session_id,
            "failure_codes": failure_codes,
            "spec": spec_payload,
        },
    )


def capture_malformed_proposal_arguments(
    raw_arguments: str,
    *,
    session_id: str,
    error_message: str,
) -> None:
    """Capture tool arguments that failed raw JSON decoding.

    Malformed-JSON repair responses are the one rejection class the
    structured tap cannot see (there is no parsed dict yet).
    """

    capture_dir = os.environ.get(REJECTED_PROPOSAL_CAPTURE_DIR_ENV)
    if not capture_dir:
        return
    try:
        directory = Path(capture_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stored_content = (
            f"session_id: {session_id}\nerror: {error_message}\n---\n{raw_arguments}"
        )
        digest = hashlib.sha256(stored_content.encode("utf-8")).hexdigest()[:12]
        (directory / f"malformed-proposal-{digest}.txt").write_text(
            stored_content,
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Malformed proposal capture failed", exc_info=True)


def _write_capture(*, prefix: str, payload: dict[str, Any]) -> None:
    capture_dir = os.environ.get(REJECTED_PROPOSAL_CAPTURE_DIR_ENV)
    if not capture_dir:
        return
    try:
        directory = Path(capture_dir)
        directory.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]
        (directory / f"{prefix}-{digest}.json").write_text(
            encoded,
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Rejected proposal capture failed", exc_info=True)
