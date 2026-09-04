# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server: image generation through a tenant model provider.

The built-in image provider is an ordinary ``mcp_servers`` row with
``http_auth_type = "internal"`` whose endpoint is this loopback server. Its
``provider_config`` names the tenant model provider and model to call; the
ask path mints a scoped token that carries the row id, so the tool reads its
configuration from a row the caller cannot choose and uses the credentials
the tenant already manages under model providers.

The generated image is returned as an MCP ``image`` content block, which the
proxy caps and the ask path persists as a generated file like any other
provider's output. The image model's own token usage rides on the result's
``_meta`` under the OpenTelemetry GenAI attribute names (``gen_ai.usage.*``,
``gen_ai.request.model``, ...), so clients can account for it without an
eneo-specific contract.

See :mod:`eneo.internal_mcp.foundation` for the hosting and authentication
model shared by all internal servers.
"""

from __future__ import annotations

import base64
import logging
from typing import Any
from uuid import UUID

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from eneo.internal_mcp.constants import IMAGE_GENERATION_SERVER_NAME
from eneo.internal_mcp.foundation import (
    bearer_from_ctx,
    internal_tool_context,
    mcp_server_id_from_token,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    BUILTIN_IMAGE_QUALITIES,
    BUILTIN_IMAGE_SIZES,
    is_builtin_provider,
    validate_builtin_provider_config,
)
from eneo.model_providers.domain.model_route import resolve_model_route
from eneo.model_providers.infrastructure import litellm_transport
from eneo.model_providers.infrastructure.litellm_provider import (
    build_litellm_provider_kwargs,
    load_active_litellm_provider,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Eneo Image Generation",
    stateless_http=True,
    instructions=(
        "Generates images from text descriptions with the organisation's "
        "configured image model."
    ),
)

NOT_CONFIGURED_MESSAGE = (
    "Image generation is not configured for this provider. Ask an "
    "administrator to check the built-in provider's model selection."
)
NO_IMAGE_MESSAGE = "The image model returned no image."
DEFAULT_MIME_TYPE = "image/png"

# OpenTelemetry GenAI semantic-convention values for ``gen_ai.provider.name``
# where they differ from eneo's provider type.
_OTEL_PROVIDER_NAMES = {"azure": "azure.ai.openai"}


def resolve_request_params(
    config: dict[str, Any], size: str | None, quality: str | None
) -> dict[str, str]:
    """Size and quality for one call: the caller's valid choice, else the
    provider's default, and nothing at all for ``auto`` so the model decides."""
    params: dict[str, str] = {}
    chosen_size = size if size in BUILTIN_IMAGE_SIZES else config.get("size")
    if chosen_size and chosen_size != "auto":
        params["size"] = chosen_size
    chosen_quality = (
        quality if quality in BUILTIN_IMAGE_QUALITIES else config.get("quality")
    )
    if chosen_quality and chosen_quality != "auto":
        params["quality"] = chosen_quality
    return params


async def image_bytes_from_response(response: Any) -> tuple[bytes, str | None]:
    """The first generated image as bytes plus its revised prompt, if any.

    Providers return base64 (``b64_json``) or a short-lived URL; both are
    accepted so the tool works across LiteLLM image backends.
    """
    data = list(getattr(response, "data", None) or [])
    if not data:
        raise ValueError(NO_IMAGE_MESSAGE)
    first = data[0]
    revised = getattr(first, "revised_prompt", None)
    encoded = getattr(first, "b64_json", None)
    if encoded:
        return base64.b64decode(encoded), revised
    url = getattr(first, "url", None)
    if url:
        async with httpx.AsyncClient(timeout=60) as client:
            fetched = await client.get(url)
            fetched.raise_for_status()
            return fetched.content, revised
    raise ValueError(NO_IMAGE_MESSAGE)


def usage_meta_from_response(
    response: Any, *, provider_type: str, model: str
) -> dict[str, Any]:
    """Tool-result ``_meta`` describing the image model call.

    Keys follow the OpenTelemetry GenAI semantic conventions. Token counts are
    included only when the provider reported them (gpt-image-1 does, DALL-E
    does not).
    """
    meta: dict[str, Any] = {
        "gen_ai.operation.name": "generate_content",
        "gen_ai.provider.name": _OTEL_PROVIDER_NAMES.get(provider_type, provider_type),
        "gen_ai.request.model": model,
    }
    response_model = getattr(response, "model", None)
    if isinstance(response_model, str) and response_model:
        meta["gen_ai.response.model"] = response_model
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if isinstance(input_tokens, int) and not isinstance(input_tokens, bool):
        meta["gen_ai.usage.input_tokens"] = input_tokens
    if isinstance(output_tokens, int) and not isinstance(output_tokens, bool):
        meta["gen_ai.usage.output_tokens"] = output_tokens
    return meta


DROPPABLE_PARAMS = frozenset({"response_format", "size", "quality", "n"})


async def _generate_dropping_unsupported_params(call_kwargs: dict[str, Any]) -> Any:
    """Call the image model, dropping parameters it rejects as unsupported.

    Models differ in what they accept: gpt-image-1 rejects ``response_format``
    because it always returns base64, dall-e-2 rejects ``quality``. LiteLLM
    names one rejected parameter per error, so drop it and retry; the
    caller's remaining choices survive and ``image_bytes_from_response``
    handles both base64 and URL payloads.
    """
    for _ in range(len(DROPPABLE_PARAMS)):
        try:
            return await litellm_transport.aimage_generation(**call_kwargs)
        except Exception as exc:
            param = litellm_transport.unsupported_param(exc)
            if param not in DROPPABLE_PARAMS or param not in call_kwargs:
                raise
            logger.info(
                "[ImageGeneration] %s: dropping unsupported parameter %s",
                call_kwargs["model"],
                param,
            )
            call_kwargs.pop(param)
    return await litellm_transport.aimage_generation(**call_kwargs)


async def generate_with_litellm(
    *,
    route: str,
    provider_kwargs: dict[str, Any],
    prompt: str,
    params: dict[str, str],
    provider_type: str,
    model: str | None = None,
) -> CallToolResult:
    """Call the image model and shape its answer as an MCP tool result.

    ``model`` is the configured model name for the usage metadata; it defaults
    to the route with its provider prefix removed.
    """
    call_kwargs: dict[str, Any] = {
        "model": route,
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json",
        **params,
        **provider_kwargs,
    }
    try:
        response = await _generate_dropping_unsupported_params(call_kwargs)
        image, revised = await image_bytes_from_response(response)
    except ValueError:
        raise
    except Exception as exc:
        logger.exception("[ImageGeneration] %s: provider call failed", route)
        litellm_transport.raise_public_litellm_error(
            exc,
            provider_type=provider_type,
            is_unavailable=litellm_transport.is_provider_unavailable_error,
            raise_unavailable=litellm_transport.raise_provider_unavailable,
        )
    text = "Image generated and shown to the user."
    if revised:
        text += f" The model interpreted the prompt as: {revised}"
    return CallToolResult(
        content=[
            TextContent(type="text", text=text),
            ImageContent(
                type="image",
                data=base64.b64encode(image).decode("ascii"),
                mimeType=DEFAULT_MIME_TYPE,
            ),
        ],
        _meta=usage_meta_from_response(
            response,
            provider_type=provider_type,
            model=model or route.removeprefix(f"{provider_type}/"),
        ),
    )


@mcp.tool(title="Generate image")
async def generate_image(
    prompt: str,
    ctx: Context,
    size: str | None = None,
    quality: str | None = None,
) -> CallToolResult:
    """Generate an image from a text description.

    The image is shown to the user directly. Describe the subject, style and
    composition in the prompt. ``size`` is one of "1024x1024", "1536x1024"
    (landscape) or "1024x1536" (portrait); ``quality`` is "low", "medium" or
    "high". Leave both out to use the organisation's defaults. For diagrams
    or vector graphics, write code instead of calling this tool.
    """
    server_id = mcp_server_id_from_token(bearer_from_ctx(ctx))
    async with internal_tool_context(ctx) as tool_ctx:
        container = tool_ctx.container
        server = await container.mcp_server_repo().one(id=server_id)
        if (
            server.tenant_id != tool_ctx.user.tenant_id
            or not is_builtin_provider(server.http_auth_type)
            or not server.provider_config
        ):
            raise ValueError(NOT_CONFIGURED_MESSAGE)
        try:
            config = validate_builtin_provider_config(server.provider_config)
        except ValueError:
            raise ValueError(NOT_CONFIGURED_MESSAGE) from None
        provider = await load_active_litellm_provider(
            session=container.session(),
            provider_id=UUID(config["model_provider_id"]),
            tenant_id=tool_ctx.user.tenant_id,
        )
        resolver = provider.create_credential_resolver(container.encryption_service())
        provider_kwargs = build_litellm_provider_kwargs(resolver)
        route = resolve_model_route(
            model_name=config["model"], provider_type=provider.provider_type
        )
    # The provider call runs outside the request-scoped DB transaction.
    return await generate_with_litellm(
        route=route,
        provider_kwargs=provider_kwargs,
        prompt=prompt,
        params=resolve_request_params(config, size, quality),
        provider_type=provider.provider_type,
        model=config["model"],
    )


__all__ = [
    "IMAGE_GENERATION_SERVER_NAME",
    "generate_image",
    "generate_with_litellm",
    "image_bytes_from_response",
    "mcp",
    "resolve_request_params",
    "usage_meta_from_response",
]
