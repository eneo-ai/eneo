"""The external speaker-labelling service a transcribe step calls.

One service for the deployment, named by ``FLOW_SPEAKER_SERVICE_URL`` (and
its key), like the other singleton services Eneo talks to. The contract is
a job queue: ``POST /v1/jobs`` (multipart ``file`` plus form fields) answers
202 with a job id, ``GET /v1/jobs/{id}`` reports ``status`` until it is
``completed``, ``failed`` or ``cancelled``, and ``GET /v1/jobs/{id}/result``
returns the transcript segments with ``speaker`` labels (409 while the job
still runs). Eneo sends the chunk windows its own transcription produced;
the service labels speakers inside them and never rewrites the text.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional, cast
from uuid import uuid4

import httpx

from eneo.files.transcript import TranscriptSegment
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)

SUBMIT_TIMEOUT_SECONDS = 600.0
RESULT_TIMEOUT_SECONDS = 120.0
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class SpeakerServiceError(Exception):
    """The service could not label the audio; ``code`` is the run-facing reason."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class SpeakerServiceConfig:
    base_url: str
    api_key: Optional[str]
    poll_seconds: float


def configured_speaker_service() -> Optional[SpeakerServiceConfig]:
    settings = get_settings()
    url = (settings.flow_speaker_service_url or "").strip().rstrip("/")
    if not url:
        return None
    return SpeakerServiceConfig(
        base_url=url,
        api_key=settings.flow_speaker_service_api_key or None,
        poll_seconds=max(0.5, float(settings.flow_speaker_service_poll_seconds)),
    )


def parse_result_segments(raw: object) -> list[TranscriptSegment]:
    if not isinstance(raw, list):
        raise SpeakerServiceError(
            "flow_speaker_service_malformed", "job result without segments"
        )
    segments: list[TranscriptSegment] = []
    for item in cast(list[Any], raw):
        if not isinstance(item, dict):
            continue
        entry = cast(dict[str, Any], item)
        try:
            segments.append(
                TranscriptSegment(
                    text=str(entry.get("text") or ""),
                    start=float(entry["start"]),
                    end=float(entry["end"]),
                    speaker=str(entry["speaker"]) if entry.get("speaker") else None,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SpeakerServiceError(
                "flow_speaker_service_malformed", f"segment without timing: {exc}"
            ) from exc
    return segments


class SpeakerService:
    """One diarize job per call; no state between calls."""

    def __init__(self, config: SpeakerServiceConfig) -> None:
        self.config = config

    @property
    def _auth(self) -> dict[str, str]:
        if self.config.api_key:
            return {"Authorization": f"Bearer {self.config.api_key}"}
        return {}

    async def label_speakers(
        self,
        data: bytes,
        *,
        filename: str,
        mimetype: str,
        segments: list[TranscriptSegment],
        model_name: str,
        language: Optional[str],
        max_speakers: Optional[int],
    ) -> list[TranscriptSegment]:
        form: dict[str, str] = {
            "task": "diarize",
            "diarize": "true",
            "language": language or "auto",
            "model": model_name,
            "segments": json.dumps(
                [{"text": s.text, "start": s.start, "end": s.end} for s in segments]
            ),
        }
        if max_speakers is not None:
            form["max_speakers"] = str(max_speakers)
        try:
            async with httpx.AsyncClient(timeout=SUBMIT_TIMEOUT_SECONDS) as http:
                response = await http.post(
                    f"{self.config.base_url}/v1/jobs",
                    headers={**self._auth, "Idempotency-Key": str(uuid4())},
                    data=form,
                    files={"file": (filename, data, mimetype)},
                )
        except httpx.HTTPError as exc:
            raise SpeakerServiceError(
                "flow_speaker_service_unavailable",
                f"could not reach the speaker service: {type(exc).__name__}",
            ) from exc
        if response.status_code in (401, 403):
            raise SpeakerServiceError(
                "flow_speaker_service_credentials",
                "the speaker service refused the key",
            )
        if response.status_code != 202:
            raise SpeakerServiceError(
                "flow_speaker_service_rejected",
                f"the speaker service answered {response.status_code}",
            )
        job_id = str(response.json().get("job_id") or "")
        if not job_id:
            raise SpeakerServiceError(
                "flow_speaker_service_malformed", "accepted job without a job id"
            )
        await self._wait(job_id)
        return await self._result(job_id)

    async def _wait(self, job_id: str) -> None:
        while True:
            try:
                async with httpx.AsyncClient(timeout=RESULT_TIMEOUT_SECONDS) as http:
                    response = await http.get(
                        f"{self.config.base_url}/v1/jobs/{job_id}", headers=self._auth
                    )
            except httpx.HTTPError as exc:
                raise SpeakerServiceError(
                    "flow_speaker_service_unavailable",
                    f"lost the speaker service while waiting: {type(exc).__name__}",
                ) from exc
            if response.status_code != 200:
                raise SpeakerServiceError(
                    "flow_speaker_service_rejected",
                    f"job status answered {response.status_code}",
                )
            body = cast(dict[str, Any], response.json())
            status = str(body.get("status") or "")
            if status == "completed":
                return
            if status in TERMINAL_STATUSES:
                reason = str(body.get("reason") or body.get("error") or status)
                raise SpeakerServiceError(
                    "flow_speaker_service_failed", f"speaker labelling {reason}"
                )
            await asyncio.sleep(self.config.poll_seconds)

    async def _result(self, job_id: str) -> list[TranscriptSegment]:
        try:
            async with httpx.AsyncClient(timeout=RESULT_TIMEOUT_SECONDS) as http:
                response = await http.get(
                    f"{self.config.base_url}/v1/jobs/{job_id}/result",
                    headers=self._auth,
                )
        except httpx.HTTPError as exc:
            raise SpeakerServiceError(
                "flow_speaker_service_unavailable",
                f"could not fetch the speaker result: {type(exc).__name__}",
            ) from exc
        if response.status_code != 200:
            raise SpeakerServiceError(
                "flow_speaker_service_rejected",
                f"job result answered {response.status_code}",
            )
        body = cast(dict[str, Any], response.json())
        return parse_result_segments(body.get("segments"))
