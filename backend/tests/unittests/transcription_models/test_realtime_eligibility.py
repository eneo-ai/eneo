"""Which providers can carry live text: the truth table of the one rule."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlsplit

import pytest

from eneo.flows.runtime.live_transcription.upstream import realtime_websocket_url
from eneo.transcription_models.domain.realtime import (
    realtime_eligibility,
    streams_live,
)
from eneo.transcription_models.domain.transcription_model import TranscriptionModel

GATEWAY = "https://gateway.example.se"


def _eligibility(
    provider_type: str | None,
    *,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    headers: bool = False,
    active: bool = True,
) -> str:
    return realtime_eligibility(
        provider_type=provider_type,
        credentials=credentials or {},
        config=config or {},
        has_outbound_headers=headers,
        is_active=active,
    )


ELIGIBLE = [
    ("hosted_vllm", {"endpoint": "http://vadsa:8000"}, {}),
    ("vllm", {"endpoint": "http://vadsa:8000/v1"}, {}),
    ("VLLM", {"endpoint": "https://asr.example.se"}, {}),
    ("openai", {"endpoint": GATEWAY}, {}),
    ("openai", {"endpoint": f"{GATEWAY}/v1"}, {}),
    ("openai", {"endpoint": f"{GATEWAY}/v1/"}, {}),
    ("openai", {"endpoint": "http://gateway.internal:8080"}, {}),
    ("OpenAI", {"endpoint": f" {GATEWAY.upper()} "}, {}),
    # The endpoint a request resolves: credentials answer first.
    ("openai", {}, {"endpoint": GATEWAY}),
    ("openai", {"endpoint": "https://api.openai.com"}, {"endpoint": GATEWAY}),
]


@pytest.mark.parametrize(("provider_type", "config", "credentials"), ELIGIBLE)
def test_a_provider_that_can_carry_live_text(
    provider_type: str, config: dict[str, Any], credentials: dict[str, Any]
):
    assert (
        _eligibility(provider_type, config=config, credentials=credentials)
        == "eligible"
    )


@pytest.mark.parametrize(("provider_type", "config", "credentials"), ELIGIBLE)
def test_every_eligible_endpoint_opens_the_realtime_socket_on_the_same_host(
    provider_type: str, config: dict[str, Any], credentials: dict[str, Any]
):
    endpoint = credentials.get("endpoint", config.get("endpoint"))
    url = realtime_websocket_url(endpoint)

    assert urlsplit(url).scheme in ("ws", "wss")
    assert urlsplit(url).hostname == urlsplit(endpoint.strip()).hostname
    assert url.endswith("/v1/realtime")
    assert "/v1/v1/" not in url


@pytest.mark.parametrize(
    ("provider_type", "config", "credentials"),
    [
        ("hosted_vllm", {}, {}),
        ("vllm", {"endpoint": ""}, {}),
        ("openai", {}, {}),
        ("openai", {"endpoint": "   "}, {}),
        # An empty credential value shadows config, as it does for a request.
        ("openai", {"endpoint": GATEWAY}, {"endpoint": ""}),
        ("hosted_vllm", {"endpoint": "http://vadsa:8000"}, {"endpoint": ""}),
        ("openai", {"endpoint": "gateway.example.se"}, {}),
        ("openai", {"endpoint": "ftp://gateway.example.se"}, {}),
        ("openai", {"endpoint": "https://user:secret@gateway.example.se"}, {}),
        # OpenAI's own service does not serve vLLM's realtime API.
        ("openai", {"endpoint": "https://api.openai.com"}, {}),
        ("openai", {"endpoint": "https://api.openai.com/v1"}, {}),
        ("openai", {"endpoint": "https://api.openai.com/v1/"}, {}),
        ("openai", {"endpoint": "HTTPS://API.OPENAI.COM:443/v1"}, {}),
        ("openai", {"endpoint": "https://api.openai.com./v1"}, {}),
        # IDNA maps the ideographic and fullwidth full stops to a root dot.
        ("openai", {"endpoint": "https://api.openai.com。"}, {}),
        ("openai", {"endpoint": "https://api.openai.com。/v1"}, {}),
        ("openai", {"endpoint": "https://api.openai.com．"}, {}),
        ("openai", {"endpoint": "https://api.openai.com．/v1"}, {}),
        ("openai", {"endpoint": "https://api.openai.com｡"}, {}),
        ("openai", {"endpoint": "https://api.openai.com｡/v1"}, {}),
        ("openai", {"endpoint": "https://eu.api.openai.com/v1"}, {}),
        ("openai", {"endpoint": "https://openai.com"}, {}),
        ("openai", {}, {"endpoint": "https://api.openai.com/v1"}),
    ],
)
def test_a_provider_without_a_usable_endpoint(
    provider_type: str, config: dict[str, Any], credentials: dict[str, Any]
):
    assert (
        _eligibility(provider_type, config=config, credentials=credentials)
        == "endpoint_required"
    )


def test_a_lookalike_host_is_not_openais_own():
    assert (
        _eligibility("openai", config={"endpoint": "https://notopenai.com/v1"})
        == "eligible"
    )


@pytest.mark.parametrize(
    "provider_type", [None, "azure", "anthropic", "gemini", "mistral", ""]
)
def test_other_provider_types_cannot_carry_live_text(provider_type: str | None):
    assert (
        _eligibility(provider_type, config={"endpoint": GATEWAY})
        == "unsupported_provider"
    )


@pytest.mark.parametrize("provider_type", ["hosted_vllm", "vllm", "openai"])
def test_a_provider_with_outbound_headers_cannot_carry_live_text(provider_type: str):
    # The live path cannot send them, as file transcription cannot.
    assert (
        _eligibility(provider_type, config={"endpoint": GATEWAY}, headers=True)
        == "outbound_headers_configured"
    )


@pytest.mark.parametrize(
    ("provider_type", "config", "headers", "active", "expected"),
    [
        ("openai", {"endpoint": GATEWAY}, False, True, "eligible"),
        ("openai", {"endpoint": GATEWAY}, False, False, "provider_inactive"),
        # Switching the provider on fixes neither its endpoint nor its headers,
        # so those reasons come first.
        ("openai", {}, False, False, "endpoint_required"),
        (
            "hosted_vllm",
            {"endpoint": GATEWAY},
            True,
            False,
            "outbound_headers_configured",
        ),
        (None, {"endpoint": GATEWAY}, False, False, "unsupported_provider"),
    ],
)
def test_a_switched_off_provider_carries_no_live_text_and_says_so_last(
    provider_type: str | None,
    config: dict[str, Any],
    headers: bool,
    active: bool,
    expected: str,
):
    assert (
        _eligibility(provider_type, config=config, headers=headers, active=active)
        == expected
    )


@pytest.mark.parametrize(
    ("marked", "eligibility", "expected"),
    [
        (True, "eligible", True),
        (False, "eligible", False),
        (True, "endpoint_required", False),
        (True, "unsupported_provider", False),
        (True, "outbound_headers_configured", False),
        (True, "provider_inactive", False),
    ],
)
def test_a_model_streams_live_only_when_marked_and_its_provider_is_eligible(
    marked: bool, eligibility: str, expected: bool
):
    model = SimpleNamespace(supports_realtime=marked, realtime_eligibility=eligibility)

    assert streams_live(cast(TranscriptionModel, model)) is expected
