"""What a flow's transcription service adds to the transcript the flow's model
wrote, shared by batch and live flow transcripts.

When the run labels speakers, the service labels them, and its failure fails
the step: the author asked for the labels. Otherwise the service places the
words in time, which a reader uses to follow the audio. The text never
depends on that, so a timing that fails leaves the transcript as the model
wrote it and records why (``WordTimingOutcome``).
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.flows.runtime.run_cancellation import FlowStepCancelledError
from eneo.main.exceptions import (
    APIKeyNotConfiguredException,
    OpenAIException,
    TypedIOValidationException,
)
from eneo.main.logging import get_logger
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
)
from eneo.model_providers.infrastructure.litellm_transport import (
    provider_failure_for_code,
)
from eneo.transcription_services.client import TIMESTAMP_TASK, SubmissionRejected

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eneo.files.transcript import TranscriptSegment
    from eneo.flows.runtime.remote_transcription import RemoteFlowTranscriber
    from eneo.model_providers.domain.provider_call_observer import ProviderCallObserver
    from eneo.transcription_models.domain.transcription_model import TranscriptionModel
    from eneo.transcription_services.client import TranscriptionJobResult

logger = get_logger(__name__)
DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT = "skipped:empty_transcript"

# Refusals, the step's deadline, cancellation and evidence gaps already say
# what happened; they end the step whichever task the service was given.
_STEP_ENDINGS = (
    TypedIOValidationException,
    ProviderCallObserverError,
    FlowStepCancelledError,
)


class WordTimingOutcome(StrEnum):
    """What came of having the service time a transcript's words: done, or
    the closed reason it failed and the transcript kept the model's text
    without segments."""

    DONE = "done"
    # The chosen service could not be used: not usable in the space when the
    # step ran, removed meanwhile, or not reachable.
    UNAVAILABLE = "unavailable"
    # The service does not offer word timing: it refused or ignored the task.
    UNSUPPORTED = "unsupported"
    # The service rejected the connection's key.
    CREDENTIALS = "credentials"
    # The job failed or was cancelled on the service, or its outcome was lost.
    FAILED = "failed"
    # The job completed without timed words for the transcript it was sent.
    NO_TIMINGS = "no_timings"


class SpeakerServiceFailed(Exception):
    """The speaker identification service failed after the model wrote the
    text; the cause is chained. The step reports it as the speaker service's
    failure, not the transcription's."""


async def enrich_transcript(
    remote: RemoteFlowTranscriber,
    file: SpooledAudio,
    transcription_model: TranscriptionModel,
    *,
    transcribed: TranscribedAudio,
    file_id: UUID,
    diarize: bool,
    language: str | None = None,
    observer: ProviderCallObserver | None = None,
    max_speakers: int | None = None,
) -> TranscribedAudio:
    """The transcript with its speakers labelled (``diarize``), else with its
    words timed."""
    if not diarize:
        return await _time_words(
            remote,
            file,
            transcription_model,
            transcribed=transcribed,
            file_id=file_id,
            language=language,
            observer=observer,
        )
    if not transcribed.segments:
        # Every chunk decoded to nothing; there is no text to label.
        logger.warning(
            "flow_transcription.diarization_skipped model=%s reason=empty_transcript",
            transcription_model.model_name,
        )
        return replace(transcribed, diarization=DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT)

    started = time.monotonic()
    try:
        labelled = await remote.label_speakers(
            file,
            file_id=file_id,
            words=None,
            segments=transcribed.segments,
            model_name=transcription_model.model_name,
            language=language,
            observer=observer,
            max_speakers=max_speakers,
        )
    except _STEP_ENDINGS:
        raise
    except Exception as exc:
        raise SpeakerServiceFailed() from exc
    return TranscribedAudio(
        text=labelled.text,
        duration_seconds=transcribed.duration_seconds,
        segments=transcribed.segments,
        transcript_segments=labelled.segments,
        diarization="external",
        diarization_elapsed_ms=int((time.monotonic() - started) * 1000),
        alignment=labelled.alignment,
        speaker_review=labelled.speaker_review,
        empty_intervals=transcribed.empty_intervals,
    )


async def _time_words(
    remote: RemoteFlowTranscriber,
    file: SpooledAudio,
    transcription_model: TranscriptionModel,
    *,
    transcribed: TranscribedAudio,
    file_id: UUID,
    language: str | None,
    observer: ProviderCallObserver | None,
) -> TranscribedAudio:
    spoken = transcribed.segments
    if not spoken:
        # Every chunk decoded to nothing; there are no words to time.
        return transcribed
    try:
        result = await remote.time_words(
            file,
            file_id=file_id,
            segments=spoken,
            model_name=transcription_model.model_name,
            language=language,
            observer=observer,
        )
    except _STEP_ENDINGS:
        raise
    except Exception as exc:
        return _untimed(transcribed, _timing_failure(exc), error=exc)
    lines = _timed_lines(result, spoken)
    if lines is None:
        return _untimed(transcribed, WordTimingOutcome.NO_TIMINGS)
    return replace(
        transcribed,
        transcript_segments=lines,
        alignment=result.alignment,
        word_timing=WordTimingOutcome.DONE,
    )


def _untimed(
    transcribed: TranscribedAudio,
    reason: WordTimingOutcome,
    *,
    error: Exception | None = None,
) -> TranscribedAudio:
    # The error's type only: a transport error's text can quote credentials.
    logger.warning(
        "flow_transcription.word_timing_failed reason=%s error=%s",
        reason.value,
        type(error).__name__ if error is not None else None,
    )
    return replace(transcribed, word_timing=reason)


def _timing_failure(error: Exception) -> WordTimingOutcome:
    """The closed reason a timing job failed, read from the typed errors the
    remote transcriber raises."""
    if isinstance(error, APIKeyNotConfiguredException):
        return WordTimingOutcome.CREDENTIALS
    details = (error.details or {}) if isinstance(error, OpenAIException) else {}
    if isinstance(error.__cause__, SubmissionRejected) or (
        details.get("reason") == f"{TIMESTAMP_TASK}_task_unsupported"
    ):
        return WordTimingOutcome.UNSUPPORTED
    if isinstance(error, OpenAIException):
        failure = provider_failure_for_code(error.code)
        if failure is not None and failure.unavailable:
            return WordTimingOutcome.UNAVAILABLE
    return WordTimingOutcome.FAILED


def _timed_lines(
    result: TranscriptionJobResult, spoken: Sequence[TranscriptSegment]
) -> tuple[TranscriptSegment, ...] | None:
    """The result's lines when they time the transcript that was sent: every
    line labels no one and is timed word by word (its words say its text, in
    order, each within the line), and together the lines say what the model
    wrote. None otherwise, so partial or impossible timings are reported as
    none rather than stored; the lines were already dropped when they did not
    render the service's own text."""
    lines = result.segments
    if not lines or any(
        line.speaker is not None
        or line.speaker_attribution is not None
        or line.overlap_ids
        or not _timed_word_by_word(line)
        for line in lines
    ):
        return None
    if _tokens(line.text for line in lines) != _tokens(
        segment.text for segment in spoken
    ):
        return None
    return lines


# How far a word may reach past its line's own window: the aligner pads windows.
_WORD_WINDOW_SLACK_S = 0.5


def _timed_word_by_word(line: TranscriptSegment) -> bool:
    words = line.words
    # One entry per word: an entry that holds several (a whole sentence) gives
    # them all one time, and nothing could be sought or lit word by word.
    if (
        not words
        or any(len(word.word.split()) != 1 for word in words)
        or _tokens(word.word for word in words) != _tokens([line.text])
    ):
        return False
    previous_start = line.start - _WORD_WINDOW_SLACK_S
    for word in words:
        if not (
            previous_start <= word.start <= word.end
            and word.end <= line.end + _WORD_WINDOW_SLACK_S
        ):
            return False
        previous_start = word.start
    return True


def _tokens(texts: Iterable[str]) -> list[str]:
    """The words of ``texts`` as written. A token without a letter or digit,
    such as a lone dash, is not one: the service's aligner may leave it out."""
    return [
        token
        for token in " ".join(texts).split()
        if any(char.isalnum() for char in token)
    ]
