"""Which transcription models can stream: the one owner of that rule.

Eneo's live transcription client speaks vLLM's realtime WebSocket dialect
(`/v1/realtime`), so only models served by a vLLM-compatible provider can
carry the realtime capability. vadsa, the NeMo server for Swedish ASR,
presents itself as one.
"""

from eneo.tenants.provider_field_config import get_canonical_provider_type

REALTIME_PROVIDER_TYPE = "hosted_vllm"


def speaks_realtime_dialect(provider_type: str | None) -> bool:
    return (
        provider_type is not None
        and get_canonical_provider_type(provider_type) == REALTIME_PROVIDER_TYPE
    )
