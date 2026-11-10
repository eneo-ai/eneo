"""Why a streamed step's audio is transcribed by the transcription model.

A step whose audio was streamed while it was recorded asks for the live text
as its transcript. When that text cannot be used, the transcription model
transcribes the files instead and the step records one of these reasons, so
the switch is never silent.
"""

from typing import Literal

# The run's admission could not bind the live transcript to the step's files.
LiveTranscriptRefusal = Literal["not_found", "already_bound", "files_mismatch"]

LiveFallbackReason = Literal[
    # The audio was streamed, but the run named no live transcript.
    "not_received",
    LiveTranscriptRefusal,
    # The model that streamed the text is no longer available to the flow.
    "unavailable",
    # The live text has no timing to place it on the audio.
    "no_timing",
    # The decoded files are not the length of the audio the session heard.
    "duration_mismatch",
]
