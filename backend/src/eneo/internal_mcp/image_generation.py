# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server: image generation through a tenant model provider.

The built-in image provider is an ordinary ``mcp_servers`` row with
``http_auth_type = "internal"`` whose endpoint is this loopback server. Its
``image_model_id`` names the catalog image model to call; the ask path mints
a scoped token that carries the row id, so the tool reads its configuration
from a row the caller cannot choose and uses the credentials of the model's
provider, which the tenant already manages under model providers. Every
provider is reached through the same OpenAI Images API shaped call (LiteLLM
adapts the few that differ), so a vLLM endpoint on a local GPU and OpenAI
take the identical path.

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
from typing import Any, Awaitable, Callable

import httpx
from litellm.exceptions import BadRequestError
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from eneo.files.file_models import FileType
from eneo.image_models.domain.image_model import (
    AUTO_IMAGE_OPTION,
    IMAGE_QUALITIES,
    IMAGE_SIZES,
)
from eneo.internal_mcp.constants import IMAGE_GENERATION_SERVER_NAME
from eneo.internal_mcp.file_references import resolve_reference_file
from eneo.internal_mcp.foundation import (
    bearer_from_ctx,
    internal_tool_context,
    mcp_server_id_from_token,
)
from eneo.main.config import get_settings
from eneo.mcp_servers.domain.entities.mcp_server import is_builtin_provider
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
    "administrator to check the built-in provider's image model."
)
NO_IMAGE_MESSAGE = "The image model returned no image."
NOT_AN_IMAGE_MESSAGE = (
    "'{name}' is not an image. reference_images accepts only the url of "
    'entries with "kind": "image".'
)
TOO_MANY_REFERENCES_MESSAGE = "At most {limit} reference images per call."
REFERENCE_TOO_LARGE_MESSAGE = (
    "'{name}' is too large to use as a reference image ({limit} bytes max)."
)
EDIT_UNSUPPORTED_MESSAGE = (
    "The configured image model cannot use reference images. Call "
    "generate_image again without reference_images to create a new image "
    "from the description, or tell the user this image cannot be edited "
    "with the organisation's image model."
)
EDIT_REJECTED_MESSAGE = (
    "The image model rejected the reference image request. Call "
    "generate_image again without reference_images to create a new image "
    "from the description, or tell the user this image could not be edited."
)
DEFAULT_MIME_TYPE = "image/png"

# OpenTelemetry GenAI semantic-convention values for ``gen_ai.provider.name``
# where they differ from eneo's provider type.
_OTEL_PROVIDER_NAMES = {"azure": "azure.ai.openai"}


def resolve_request_params(
    *,
    default_size: str,
    default_quality: str,
    size: str | None,
    quality: str | None,
) -> dict[str, str]:
    """Size and quality for one call: the caller's valid choice, else the
    model's default, and nothing at all for ``auto`` so the model decides."""
    params: dict[str, str] = {}
    chosen_size = size if size in IMAGE_SIZES else default_size
    if chosen_size and chosen_size != AUTO_IMAGE_OPTION:
        params["size"] = chosen_size
    chosen_quality = quality if quality in IMAGE_QUALITIES else default_quality
    if chosen_quality and chosen_quality != AUTO_IMAGE_OPTION:
        params["quality"] = chosen_quality
    return params


async def image_bytes_from_response(
    response: Any, *, timeout: float = 60
) -> tuple[bytes, str | None]:
    """The first generated image as bytes plus its revised prompt, if any.

    Providers return base64 (``b64_json``) or a short-lived URL; both are
    accepted so the tool works across LiteLLM image backends. ``timeout``
    bounds the URL fetch.
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
        async with httpx.AsyncClient(timeout=timeout) as client:
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


async def _call_dropping_unsupported_params(
    call: Callable[..., Awaitable[Any]], call_kwargs: dict[str, Any]
) -> Any:
    """Call the image model, dropping parameters it rejects as unsupported.

    Models differ in what they accept: gpt-image-1 rejects ``response_format``
    because it always returns base64, dall-e-2 rejects ``quality``. Each error
    names a rejected parameter, so drop it and retry; the caller's remaining
    choices survive and ``image_bytes_from_response`` handles both base64 and
    URL payloads.
    """
    for _ in range(len(DROPPABLE_PARAMS)):
        try:
            return await call(**call_kwargs)
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
    return await call(**call_kwargs)


def _edit_unsupported(exc: BaseException) -> bool:
    """LiteLLM has no image-edit transformation for the route's provider."""
    return isinstance(exc, ValueError) and "image edit is not supported" in str(exc)


async def generate_with_litellm(
    *,
    route: str,
    provider_kwargs: dict[str, Any],
    prompt: str,
    params: dict[str, str],
    provider_type: str,
    model: str | None = None,
    reference_images: list[bytes] | None = None,
) -> CallToolResult:
    """Call the image model and shape its answer as an MCP tool result.

    With ``reference_images`` the call is an edit (OpenAI ``images.edit``
    contract: the prompt describes the change, the images are the input);
    without them it is a generation. ``model`` is the configured model name
    for the usage metadata; it defaults to the route with its provider prefix
    removed.
    """
    timeout = get_settings().image_generation_timeout_seconds
    call_kwargs: dict[str, Any] = {
        "model": route,
        "prompt": prompt,
        "n": 1,
        "timeout": timeout,
        **params,
        **provider_kwargs,
    }
    if reference_images:
        # Raw bytes, not (name, bytes) tuples: LiteLLM wraps each image into
        # the multipart field itself and sniffs the content type. gpt-image-1
        # rejects ``response_format`` on edits; every edit model returns
        # base64 or a URL by default, both of which are accepted below.
        call_kwargs["image"] = list(reference_images)
        call = litellm_transport.aimage_edit
    else:
        call_kwargs["response_format"] = "b64_json"
        call = litellm_transport.aimage_generation
    try:
        response = await _call_dropping_unsupported_params(call, call_kwargs)
        image, revised = await image_bytes_from_response(response, timeout=timeout)
    except ValueError as exc:
        if reference_images and _edit_unsupported(exc):
            logger.info("[ImageGeneration] %s: image edit unsupported", route)
            raise ValueError(EDIT_UNSUPPORTED_MESSAGE) from exc
        raise
    except Exception as exc:
        logger.exception("[ImageGeneration] %s: provider call failed", route)
        if reference_images and isinstance(exc, BadRequestError):
            # The request itself is what the model refused (edits not offered
            # for this model, image format or size): tell the model so it can
            # recover, rather than a generic provider error.
            raise ValueError(EDIT_REJECTED_MESSAGE) from exc
        litellm_transport.raise_public_litellm_error(
            exc,
            provider_type=provider_type,
            is_unavailable=litellm_transport.is_provider_unavailable_error,
            raise_unavailable=litellm_transport.raise_provider_unavailable,
        )
    if reference_images:
        count = len(reference_images)
        plural = "s" if count != 1 else ""
        text = (
            f"Image edited from {count} reference image{plural} and shown to the user."
        )
    else:
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


async def load_reference_images(urls: list[str], tool_ctx: Any) -> list[bytes]:
    """The bytes behind each reference url, verified and capped.

    Each url is resolved like ``read_file`` resolves an attachment (token and
    tenant checks, bytes from the content store). Uploads yield their
    provider-safe model input (downscaled PNG/JPEG/WEBP) and generated images
    their artifact. The count and size caps are the same ones that bound
    images arriving from tool results, so one call cannot move more image
    data than the platform admits in the other direction.
    """
    settings = get_settings()
    if len(urls) > settings.mcp_tool_image_max_count:
        raise ValueError(
            TOO_MANY_REFERENCES_MESSAGE.format(limit=settings.mcp_tool_image_max_count)
        )
    images: list[bytes] = []
    for url in urls:
        file = await resolve_reference_file(
            url, tool_ctx, log_tag="[ImageGeneration] reference"
        )
        if file.file_type != FileType.IMAGE or file.blob is None:
            raise ValueError(NOT_AN_IMAGE_MESSAGE.format(name=file.name))
        if len(file.blob) > settings.mcp_tool_image_max_bytes:
            raise ValueError(
                REFERENCE_TOO_LARGE_MESSAGE.format(
                    name=file.name, limit=settings.mcp_tool_image_max_bytes
                )
            )
        images.append(file.blob)
    return images


@mcp.tool(title="Generate image")
async def generate_image(
    prompt: str,
    ctx: Context,
    size: str | None = None,
    quality: str | None = None,
    reference_images: list[str] | None = None,
) -> CallToolResult:
    """Generate an image from a text description, or edit existing images.

    The image is shown to the user directly. Describe the subject, style and
    composition in the prompt. ``size`` is one of "1024x1024", "1536x1024"
    (landscape) or "1024x1536" (portrait); ``quality`` is "low", "medium" or
    "high". Leave both out to use the organisation's defaults. For diagrams
    or vector graphics, write code instead of calling this tool.

    To edit an image or make a variation of it, pass ``reference_images``:
    the exact "url" values of image entries in the conversation's file
    references (images the user attached, or images generated earlier in the
    conversation). Then the prompt describes the change or the variation
    wanted, and the result is based on those images. Never construct or
    modify the urls, and leave ``reference_images`` out entirely when the
    conversation lists no image reference entry.
    """
    server_id = mcp_server_id_from_token(bearer_from_ctx(ctx))
    async with internal_tool_context(ctx) as tool_ctx:
        container = tool_ctx.container
        server = await container.mcp_server_repo().one(id=server_id)
        if (
            server.tenant_id != tool_ctx.user.tenant_id
            or not is_builtin_provider(server.http_auth_type)
            or not server.is_enabled
            or server.image_model_id is None
        ):
            raise ValueError(NOT_CONFIGURED_MESSAGE)
        # The repo is tenant-bound and hides soft-deleted rows; a disabled
        # model is already skipped at ask time, this is defence in depth.
        model = await container.image_model_repo().one_or_none(server.image_model_id)
        if model is None or not model.is_org_enabled or model.provider_id is None:
            raise ValueError(NOT_CONFIGURED_MESSAGE)
        provider = await load_active_litellm_provider(
            session=container.session(),
            provider_id=model.provider_id,
            tenant_id=tool_ctx.user.tenant_id,
        )
        resolver = provider.create_credential_resolver(container.encryption_service())
        provider_kwargs = build_litellm_provider_kwargs(resolver)
        route = resolve_model_route(
            model_name=model.name, provider_type=provider.provider_type
        )
        params = resolve_request_params(
            default_size=model.default_size,
            default_quality=model.default_quality,
            size=size,
            quality=quality,
        )
        references = (
            await load_reference_images(reference_images, tool_ctx)
            if reference_images
            else []
        )
    # The provider call runs outside the request-scoped DB transaction.
    return await generate_with_litellm(
        route=route,
        provider_kwargs=provider_kwargs,
        prompt=prompt,
        params=params,
        provider_type=provider.provider_type,
        reference_images=references,
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
