"""What the web app needs at boot, read from backend settings.

The same values web-next reads from its own environment today (``env.ts``),
under the same env names, so one ``env_backend.env`` configures both. Every
value here is public: links the app renders and the backend version, which
``/version`` already publishes.
"""

from urllib.parse import SplitResult, urlsplit

from fastapi import APIRouter
from pydantic import BaseModel

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.config import Settings, get_settings, serialize_origin
from eneo.main.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Settings field -> the env name an operator sets.
_LINKS = {
    "help_center_url": "HELP_CENTER_URL",
    "legacy_app_url": "LEGACY_APP_URL",
    "accessibility_statement_url": "ACCESSIBILITY_STATEMENT_URL",
    "request_integration_form_url": "REQUEST_INTEGRATION_FORM_URL",
}


class WebRuntimeConfig(BaseModel):
    version: str
    revision: str
    show_web_search: bool
    help_center_url: str | None
    legacy_app_url: str | None
    accessibility_statement_url: str | None
    request_integration_form_url: str | None
    # The separate origin MCP app views are served from; the web app frames it.
    mcp_app_content_origin: str | None


def _http_parts(value: str | None) -> SplitResult | None:
    """The parts of an absolute http(s) URL, so never a script href."""
    if value is None:
        return None
    try:
        parts = urlsplit(value)
        _ = parts.port  # a malformed port raises too
    except ValueError:
        return None
    return parts if parts.scheme in ("http", "https") and parts.hostname else None


def _http_url(value: str | None) -> str | None:
    return value if _http_parts(value) else None


def build_runtime_config(settings: Settings) -> WebRuntimeConfig:
    links = {field: _http_url(getattr(settings, field)) for field in _LINKS}
    if not settings.show_help_center:
        links["help_center_url"] = None
    content_base = settings.mcp_app_content_base_url
    return WebRuntimeConfig(
        version=settings.app_version,
        revision=settings.app_revision,
        show_web_search=settings.show_web_search,
        mcp_app_content_origin=serialize_origin(content_base) if content_base else None,
        **links,
    )


def log_unlinked_runtime_values(settings: Settings) -> None:
    """Name, never quote, the runtime values the web app will not use."""
    config = build_runtime_config(settings)
    # MCP_APP_CONTENT_BASE_URL is not here: settings refuse an invalid one.
    rejected = [
        name
        for field, name in _LINKS.items()
        if getattr(settings, field) is not None
        and _http_url(getattr(settings, field)) is None
    ]
    unlinked = [
        name
        for field, name in _LINKS.items()
        if getattr(config, field) is None and name not in rejected
    ]
    if unlinked:
        logger.info("Web app runtime config: no link for %s", ", ".join(unlinked))
    if rejected:
        logger.warning(
            "Web app runtime config: ignoring %s, not an absolute http(s) URL",
            ", ".join(rejected),
        )


@router.get(
    "/runtime-config",
    tags=["runtime-config"],
    summary="Get the web app runtime config",
    description=(
        "Links, switches and the backend version the web app reads at boot. "
        "Public and never cached."
    ),
    response_model=WebRuntimeConfig,
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason=(
        "The web app reads it before sign-in; it holds only public links, "
        "switches and the version /version already publishes."
    ),
)
async def get_runtime_config() -> WebRuntimeConfig:
    return build_runtime_config(get_settings())
