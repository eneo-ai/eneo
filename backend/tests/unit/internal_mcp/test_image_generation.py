"""Unit tests for the built-in image generation loopback server.

Covers the request-parameter resolution (caller choice over provider default,
``auto`` sends nothing), the response-to-bytes adapter, the MCP content and
usage ``_meta`` the tool returns, the public error mapping, and the server mount.
"""

import base64
from types import SimpleNamespace

import pytest
from litellm.exceptions import UnsupportedParamsError

from eneo.internal_mcp import image_generation
from eneo.internal_mcp.image_generation import (
    DEFAULT_MIME_TYPE,
    NO_IMAGE_MESSAGE,
    generate_with_litellm,
    image_bytes_from_response,
    resolve_request_params,
    usage_meta_from_response,
)
from eneo.internal_mcp.registry import internal_mcp_mounts
from eneo.main.exceptions import OpenAIException
from eneo.model_providers.infrastructure import litellm_transport

CONFIG = {
    "model_provider_id": "0" * 32,
    "model": "gpt-image-1",
    "size": "1024x1024",
    "quality": "high",
}


class TestResolveRequestParams:
    def test_caller_choice_wins_over_provider_default(self):
        assert resolve_request_params(CONFIG, "1536x1024", "low") == {
            "size": "1536x1024",
            "quality": "low",
        }

    def test_provider_default_fills_missing_or_invalid_choice(self):
        assert resolve_request_params(CONFIG, None, "enormous") == {
            "size": "1024x1024",
            "quality": "high",
        }

    def test_auto_sends_nothing(self):
        config = {**CONFIG, "size": "auto", "quality": "auto"}
        assert resolve_request_params(config, "auto", None) == {}


class TestImageBytesFromResponse:
    async def test_base64_payload(self):
        encoded = base64.b64encode(b"png-bytes").decode()
        response = SimpleNamespace(
            data=[SimpleNamespace(b64_json=encoded, url=None, revised_prompt="a cat")]
        )

        assert await image_bytes_from_response(response) == (b"png-bytes", "a cat")

    async def test_empty_response_is_rejected(self):
        with pytest.raises(ValueError, match=NO_IMAGE_MESSAGE):
            await image_bytes_from_response(SimpleNamespace(data=[]))


class TestUsageMetaFromResponse:
    def test_reports_provider_token_usage_under_otel_names(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=38, output_tokens=1056),
            model=None,
        )

        assert usage_meta_from_response(
            response, provider_type="openai", model="gpt-image-1"
        ) == {
            "gen_ai.operation.name": "generate_content",
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": "gpt-image-1",
            "gen_ai.usage.input_tokens": 38,
            "gen_ai.usage.output_tokens": 1056,
        }

    def test_omits_tokens_the_provider_did_not_report(self):
        response = SimpleNamespace(usage=None, model="dall-e-3")

        assert usage_meta_from_response(
            response, provider_type="azure", model="dall-e-3"
        ) == {
            "gen_ai.operation.name": "generate_content",
            "gen_ai.provider.name": "azure.ai.openai",
            "gen_ai.request.model": "dall-e-3",
            "gen_ai.response.model": "dall-e-3",
        }


class TestGenerateWithLitellm:
    async def test_returns_text_and_image_blocks_with_usage_meta(self, monkeypatch):
        calls: list[dict] = []

        async def fake_generation(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(b"img").decode(),
                        url=None,
                        revised_prompt=None,
                    )
                ],
                usage=SimpleNamespace(input_tokens=12, output_tokens=1000),
            )

        monkeypatch.setattr(litellm_transport, "aimage_generation", fake_generation)

        result = await generate_with_litellm(
            route="azure/gpt-image-1",
            provider_kwargs={"api_key": "k", "api_base": "https://x"},
            prompt="a lighthouse",
            params={"size": "1024x1536"},
            provider_type="azure",
        )

        text, image = result.content
        assert text.type == "text" and "shown to the user" in text.text
        assert result.meta == {
            "gen_ai.operation.name": "generate_content",
            "gen_ai.provider.name": "azure.ai.openai",
            "gen_ai.request.model": "gpt-image-1",
            "gen_ai.usage.input_tokens": 12,
            "gen_ai.usage.output_tokens": 1000,
        }
        assert image.type == "image"
        assert image.mimeType == DEFAULT_MIME_TYPE
        assert base64.b64decode(image.data) == b"img"
        assert calls == [
            {
                "model": "azure/gpt-image-1",
                "prompt": "a lighthouse",
                "n": 1,
                "response_format": "b64_json",
                "size": "1024x1536",
                "api_key": "k",
                "api_base": "https://x",
            }
        ]

    async def test_rejected_parameter_is_dropped_and_the_call_retried(
        self, monkeypatch
    ):
        calls: list[dict] = []

        async def fake_generation(**kwargs):
            calls.append(dict(kwargs))
            if "response_format" in kwargs:
                raise UnsupportedParamsError(
                    status_code=500,
                    message=(
                        "Setting `response_format` is not supported by openai, "
                        "gpt-image-1. To drop it from the call, set "
                        "`litellm.drop_params = True`."
                    ),
                )
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(b"img").decode(),
                        url=None,
                        revised_prompt=None,
                    )
                ]
            )

        monkeypatch.setattr(litellm_transport, "aimage_generation", fake_generation)

        result = await generate_with_litellm(
            route="openai/gpt-image-1",
            provider_kwargs={"api_key": "k"},
            prompt="a cat",
            params={"size": "1024x1024", "quality": "high"},
            provider_type="openai",
        )

        assert base64.b64decode(result.content[1].data) == b"img"
        assert len(calls) == 2
        assert "response_format" in calls[0]
        assert "response_format" not in calls[1]
        assert calls[1]["size"] == "1024x1024" and calls[1]["quality"] == "high"

    async def test_rejected_prompt_is_not_retried(self, monkeypatch):
        async def fake_generation(**kwargs):
            raise UnsupportedParamsError(
                status_code=500, message="Setting `prompt` is not supported by x, y."
            )

        monkeypatch.setattr(litellm_transport, "aimage_generation", fake_generation)

        with pytest.raises(OpenAIException):
            await generate_with_litellm(
                route="openai/gpt-image-1",
                provider_kwargs={},
                prompt="a cat",
                params={},
                provider_type="openai",
            )

    async def test_provider_failure_maps_to_public_error(self, monkeypatch):
        async def failing(**_kwargs):
            raise RuntimeError("socket closed")

        monkeypatch.setattr(litellm_transport, "aimage_generation", failing)
        monkeypatch.setattr(
            litellm_transport, "is_provider_unavailable_error", lambda _e: False
        )

        with pytest.raises(OpenAIException):
            await generate_with_litellm(
                route="openai/gpt-image-1",
                provider_kwargs={},
                prompt="x",
                params={},
                provider_type="openai",
            )


def test_image_generation_server_is_mounted():
    mounts = dict(internal_mcp_mounts())
    assert "/internal-mcp/image_generation" in mounts
    assert mounts["/internal-mcp/image_generation"] is not None
    assert image_generation.mcp.name == "Eneo Image Generation"
