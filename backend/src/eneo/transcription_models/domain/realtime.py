"""Which transcription models can stream: the one owner of that rule.

Eneo's live transcription client speaks vLLM's realtime WebSocket dialect
(`/v1/realtime`), so only models served by a vLLM-compatible provider can
carry the realtime capability. vadsa, the NeMo server for Swedish ASR,
presents itself as one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eneo.tenants.provider_field_config import get_canonical_provider_type

if TYPE_CHECKING:
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

REALTIME_PROVIDER_TYPE = "hosted_vllm"


def speaks_realtime_dialect(provider_type: str | None) -> bool:
    return (
        provider_type is not None
        and get_canonical_provider_type(provider_type) == REALTIME_PROVIDER_TYPE
    )


def streams_live(model: TranscriptionModel) -> bool:
    """Whether ``model`` can stream a live transcript: an administrator marked
    it realtime and its provider speaks the dialect."""
    return model.supports_realtime and speaks_realtime_dialect(model.provider_type)
