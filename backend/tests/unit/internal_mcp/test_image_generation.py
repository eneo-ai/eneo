"""Unit tests for the built-in image generation loopback server.

Covers the request-parameter resolution (caller choice over the model's
default, ``auto`` sends nothing), the response-to-bytes adapter, the MCP content and
usage ``_meta`` the tool returns, the public error mapping, reference images
(edit call selection, caps, model-facing errors), and the server mount.
"""

import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from litellm.exceptions import BadRequestError, UnsupportedParamsError

from eneo.files.file_models import FileType
from eneo.internal_mcp import image_generation
from eneo.internal_mcp.file_references import FileReferenceRejected
from eneo.internal_mcp.image_generation import (
    DEFAULT_MIME_TYPE,
    EDIT_REJECTED_MESSAGE,
    EDIT_UNSUPPORTED_MESSAGE,
    NO_IMAGE_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    generate_image,
    generate_with_litellm,
    image_bytes_from_response,
    load_reference_images,
    resolve_request_params,
    usage_meta_from_response,
)
from eneo.internal_mcp.registry import internal_mcp_mounts
from eneo.main.config import get_settings
from eneo.main.exceptions import OpenAIException
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.model_providers.infrastructure import litellm_transport

DEFAULTS = {"default_size": "1024x1024", "default_quality": "high"}


class TestResolveRequestParams:
    def test_caller_choice_wins_over_model_default(self):
        assert resolve_request_params(**DEFAULTS, size="1536x1024", quality="low") == {
            "size": "1536x1024",
            "quality": "low",
        }

    def test_model_default_fills_missing_or_invalid_choice(self):
        assert resolve_request_params(**DEFAULTS, size=None, quality="enormous") == {
            "size": "1024x1024",
            "quality": "high",
        }

    def test_auto_sends_nothing(self):
        assert (
            resolve_request_params(
                default_size="auto", default_quality="auto", size="auto", quality=None
            )
            == {}
        )


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
                "timeout": get_settings().image_generation_timeout_seconds,
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


def _patch_tool_context(monkeypatch, *, server: MCPServer, tenant_id):
    """Route ``generate_image`` at an in-memory provider row."""

    @asynccontextmanager
    async def fake_context(_ctx):
        container = SimpleNamespace(
            mcp_server_repo=lambda: SimpleNamespace(one=AsyncMock(return_value=server)),
            image_model_repo=lambda: SimpleNamespace(one_or_none=AsyncMock()),
            session=lambda: None,
            encryption_service=lambda: None,
        )
        yield SimpleNamespace(
            container=container, user=SimpleNamespace(tenant_id=tenant_id)
        )

    monkeypatch.setattr(image_generation, "internal_tool_context", fake_context)
    monkeypatch.setattr(image_generation, "bearer_from_ctx", lambda _ctx: "token")
    monkeypatch.setattr(
        image_generation, "mcp_server_id_from_token", lambda _t: server.id
    )


class TestGenerateImageGuard:
    async def test_deactivated_provider_is_not_configured(self, monkeypatch):
        tenant_id = uuid4()
        server = MCPServer(
            id=uuid4(),
            tenant_id=tenant_id,
            name="Images",
            http_url="http://localhost/internal-mcp/image_generation/mcp",
            http_auth_type="internal",
            purpose="image_generation",
            is_enabled=False,
            image_model_id=uuid4(),
        )
        _patch_tool_context(monkeypatch, server=server, tenant_id=tenant_id)
        load_provider = AsyncMock()
        monkeypatch.setattr(
            image_generation, "load_active_litellm_provider", load_provider
        )

        with pytest.raises(ValueError, match=NOT_CONFIGURED_MESSAGE):
            await generate_image("a cat", object())

        load_provider.assert_not_awaited()


def test_image_generation_server_is_mounted():
    mounts = dict(internal_mcp_mounts())
    assert "/internal-mcp/image_generation" in mounts
    assert mounts["/internal-mcp/image_generation"] is not None
    assert image_generation.mcp.name == "Eneo Image Generation"


def _image_response(payload: bytes = b"img"):
    return SimpleNamespace(
        data=[
            SimpleNamespace(
                b64_json=base64.b64encode(payload).decode(),
                url=None,
                revised_prompt=None,
            )
        ]
    )


class TestGenerateWithReferenceImages:
    async def test_references_route_to_the_edit_call_without_response_format(
        self, monkeypatch
    ):
        edits: list[dict] = []
        generations: list[dict] = []

        async def fake_edit(**kwargs):
            edits.append(kwargs)
            return _image_response(b"edited")

        async def fake_generation(**kwargs):
            generations.append(kwargs)
            return _image_response()

        monkeypatch.setattr(litellm_transport, "aimage_edit", fake_edit)
        monkeypatch.setattr(litellm_transport, "aimage_generation", fake_generation)

        result = await generate_with_litellm(
            route="openai/gpt-image-1",
            provider_kwargs={"api_key": "k"},
            prompt="make it blue",
            params={"size": "1024x1024"},
            provider_type="openai",
            reference_images=[b"ref-1", b"ref-2"],
        )

        assert generations == []
        assert edits == [
            {
                "model": "openai/gpt-image-1",
                "prompt": "make it blue",
                "n": 1,
                "timeout": get_settings().image_generation_timeout_seconds,
                "size": "1024x1024",
                "api_key": "k",
                # Raw bytes: LiteLLM wraps each into the multipart field itself.
                "image": [b"ref-1", b"ref-2"],
            }
        ]
        text, image = result.content
        assert "edited from 2 reference images" in text.text
        assert base64.b64decode(image.data) == b"edited"

    async def test_provider_rejected_parameter_is_dropped_on_edits(self, monkeypatch):
        calls: list[dict] = []

        async def fake_edit(**kwargs):
            calls.append(dict(kwargs))
            if "quality" in kwargs:
                raise BadRequestError(
                    message="Unknown parameter: 'quality'.",
                    model="dall-e-2",
                    llm_provider="openai",
                )
            return _image_response()

        monkeypatch.setattr(litellm_transport, "aimage_edit", fake_edit)

        await generate_with_litellm(
            route="openai/dall-e-2",
            provider_kwargs={},
            prompt="x",
            params={"quality": "high"},
            provider_type="openai",
            reference_images=[b"ref"],
        )

        assert [("quality" in c) for c in calls] == [True, False]

    async def test_provider_without_edit_support_tells_the_model(self, monkeypatch):
        async def fake_edit(**_kwargs):
            raise ValueError("image edit is not supported for hosted_vllm")

        monkeypatch.setattr(litellm_transport, "aimage_edit", fake_edit)

        with pytest.raises(ValueError, match=EDIT_UNSUPPORTED_MESSAGE):
            await generate_with_litellm(
                route="hosted_vllm/sdxl",
                provider_kwargs={},
                prompt="x",
                params={},
                provider_type="hosted_vllm",
                reference_images=[b"ref"],
            )

    async def test_rejected_edit_request_tells_the_model(self, monkeypatch):
        async def fake_edit(**_kwargs):
            raise BadRequestError(
                message="Invalid value: 'dall-e-3'.",
                model="dall-e-3",
                llm_provider="openai",
            )

        monkeypatch.setattr(litellm_transport, "aimage_edit", fake_edit)

        with pytest.raises(ValueError, match=EDIT_REJECTED_MESSAGE):
            await generate_with_litellm(
                route="openai/dall-e-3",
                provider_kwargs={},
                prompt="x",
                params={},
                provider_type="openai",
                reference_images=[b"ref"],
            )


def _reference_file(file_type=FileType.IMAGE, blob=b"png", name="photo.png"):
    return SimpleNamespace(file_type=file_type, blob=blob, name=name)


class TestLoadReferenceImages:
    async def test_returns_the_bytes_behind_each_url(self, monkeypatch):
        seen: list[str] = []

        async def fake_resolve(url, _ctx, *, log_tag):
            seen.append(url)
            return _reference_file(blob=url.encode())

        monkeypatch.setattr(image_generation, "resolve_reference_file", fake_resolve)

        images = await load_reference_images(["https://x/1", "https://x/2"], object())

        assert seen == ["https://x/1", "https://x/2"]
        assert images == [b"https://x/1", b"https://x/2"]

    async def test_non_image_reference_is_rejected(self, monkeypatch):
        async def fake_resolve(_url, _ctx, *, log_tag):
            return _reference_file(file_type=FileType.TEXT, blob=None, name="a.csv")

        monkeypatch.setattr(image_generation, "resolve_reference_file", fake_resolve)

        with pytest.raises(ValueError, match="'a.csv' is not an image"):
            await load_reference_images(["https://x/1"], object())

    async def test_reference_caps_follow_the_tool_image_settings(self, monkeypatch):
        settings = get_settings()
        too_many = ["https://x/n"] * (settings.mcp_tool_image_max_count + 1)
        with pytest.raises(ValueError, match="At most"):
            await load_reference_images(too_many, object())

        async def fake_resolve(_url, _ctx, *, log_tag):
            return _reference_file(blob=b"x" * (settings.mcp_tool_image_max_bytes + 1))

        monkeypatch.setattr(image_generation, "resolve_reference_file", fake_resolve)
        with pytest.raises(ValueError, match="too large"):
            await load_reference_images(["https://x/1"], object())

    async def test_reference_rejections_surface_as_tool_errors(self, monkeypatch):
        async def fake_resolve(_url, _ctx, *, log_tag):
            raise FileReferenceRejected("bad link")

        monkeypatch.setattr(image_generation, "resolve_reference_file", fake_resolve)

        with pytest.raises(ValueError, match="bad link"):
            await load_reference_images(["https://x/1"], object())


class TestGenerateImageReferences:
    async def test_reference_urls_reach_the_provider_call(self, monkeypatch):
        tenant_id = uuid4()
        server = MCPServer(
            id=uuid4(),
            tenant_id=tenant_id,
            name="Images",
            http_url="http://localhost/internal-mcp/image_generation/mcp",
            http_auth_type="internal",
            purpose="image_generation",
            is_enabled=True,
            image_model_id=uuid4(),
        )
        _patch_tool_context(monkeypatch, server=server, tenant_id=tenant_id)
        provider = SimpleNamespace(
            provider_type="openai",
            create_credential_resolver=lambda _enc: None,
        )
        monkeypatch.setattr(
            image_generation,
            "load_active_litellm_provider",
            AsyncMock(return_value=provider),
        )
        monkeypatch.setattr(
            image_generation, "build_litellm_provider_kwargs", lambda _r: {}
        )
        loaded: list[list[str]] = []

        async def fake_load(urls, _ctx):
            loaded.append(list(urls))
            return [b"ref"]

        generate = AsyncMock(return_value="result")
        monkeypatch.setattr(image_generation, "load_reference_images", fake_load)
        monkeypatch.setattr(image_generation, "generate_with_litellm", generate)

        result = await generate_image(
            "make it blue", object(), reference_images=["https://x/1"]
        )

        assert result == "result"
        assert loaded == [["https://x/1"]]
        assert generate.await_args.kwargs["reference_images"] == [b"ref"]
        assert generate.await_args.kwargs["prompt"] == "make it blue"
