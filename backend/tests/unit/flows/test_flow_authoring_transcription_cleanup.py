from __future__ import annotations

from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.flows.flow_authoring_transcription import apply_audio_transcription_defaults


def test_cleanup_strips_diarization_with_the_other_transcription_keys() -> None:
    metadata = apply_audio_transcription_defaults(
        metadata={
            "wizard": {
                "transcription_enabled": True,
                "transcription_diarization": False,
                "other": "kept",
            }
        },
        spec=FlowDraftSpecCore(flow_name="f", steps=[]),
        default_transcription_model_id=None,
    )

    assert metadata == {"wizard": {"other": "kept"}}
