"""Which transcription models can stream live text: the one owner of that rule.

Eneo's live transcription client speaks vLLM's realtime WebSocket dialect
(``/v1/realtime`` on the provider's endpoint), so a provider can carry live
text when it points at a server that serves that API: a vLLM provider (vadsa,
the NeMo server for Swedish ASR, presents itself as one), or an OpenAI provider
with the endpoint of a gateway that speaks the dialect. OpenAI's own service
does not, and a provider with outbound headers cannot be used because the live
path does not send them, just as file transcription refuses them. A provider
that is switched off carries no live text until it is switched on again.

Trust boundary: the answer decides where Eneo opens a WebSocket with the
provider's key, and whether a switched-off provider is used at all. Saving the
mark, admitting a session and opening the socket all read this rule; nothing
else may decide it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from eneo.model_providers.domain.outbound_header_destinations import (
    InvalidDestination,
    parse_destination,
)
from eneo.model_providers.infrastructure.tenant_model_credential_resolver import (
    lookup_provider_field,
)
from eneo.tenants.provider_field_config import get_canonical_provider_type

if TYPE_CHECKING:
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

RealtimeEligibility = Literal[
    "eligible",
    "endpoint_required",
    "unsupported_provider",
    "outbound_headers_configured",
    "provider_inactive",
]

_OPENAI_DOMAIN = "openai.com"


def realtime_eligibility(
    *,
    provider_type: str | None,
    credentials: Mapping[str, Any],
    config: Mapping[str, Any],
    has_outbound_headers: bool,
    is_active: bool,
) -> RealtimeEligibility:
    """Whether a provider can carry live text, and if not, what is missing.

    The endpoint is resolved exactly as a request resolves it: credentials
    first, and an empty credential value shadows config. A vLLM endpoint only
    has to be there; an OpenAI one must be an explicit http(s) URL whose host
    is not OpenAI's own (any ``*.openai.com``, regional hosts included).
    Whether the provider is switched on is asked last: switching it on fixes
    neither its endpoint nor its headers, so those reasons come first.
    """
    canonical = get_canonical_provider_type(provider_type) if provider_type else None
    if canonical not in ("hosted_vllm", "openai"):
        return "unsupported_provider"
    endpoint = lookup_provider_field(
        credentials=dict(credentials), config=dict(config), field="endpoint"
    )
    if not isinstance(endpoint, str) or not endpoint.strip():
        return "endpoint_required"
    if canonical == "openai" and not _is_gateway(endpoint):
        return "endpoint_required"
    if has_outbound_headers:
        return "outbound_headers_configured"
    if not is_active:
        return "provider_inactive"
    return "eligible"


def _is_gateway(endpoint: str) -> bool:
    try:
        # IDNA turns a fullwidth or ideographic full stop at the end into a
        # root dot, which the parser leaves in place: drop it before comparing.
        host = parse_destination(endpoint).host.rstrip(".")
    except InvalidDestination:
        return False
    return host != _OPENAI_DOMAIN and not host.endswith(f".{_OPENAI_DOMAIN}")


def streams_live(model: TranscriptionModel) -> bool:
    """Whether ``model`` can stream live text now: an administrator marked it
    and its provider can carry it."""
    return model.supports_realtime and model.realtime_eligibility == "eligible"
