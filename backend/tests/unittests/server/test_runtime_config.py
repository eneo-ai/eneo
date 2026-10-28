import logging
from collections.abc import Iterator

import httpx
import pytest

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    access_for,
)
from eneo.main.config import Settings, set_settings
from eneo.server import runtime_config_router
from eneo.server.main import get_application
from eneo.server.runtime_config_router import (
    build_runtime_config,
    get_runtime_config,
    log_unlinked_runtime_values,
)

LINKS = (
    "legacy_app_url",
    "accessibility_statement_url",
    "request_integration_form_url",
)


def _settings(base: Settings, **updates: object) -> Settings:
    return Settings.model_validate({**base.model_dump(), **updates})


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def runtime_log() -> Iterator[list[logging.LogRecord]]:
    """What the module logger emits at its configured level.

    SimpleLogger does not propagate to the root handler caplog uses, and the
    level is left as configured so a muted logger fails the test.
    """
    handler = _Records()
    runtime_config_router.logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        runtime_config_router.logger.removeHandler(handler)


def test_defaults(test_settings: Settings):
    config = build_runtime_config(_settings(test_settings))

    assert config.help_center_url is None
    assert config.legacy_app_url is None
    assert config.accessibility_statement_url is None
    assert config.request_integration_form_url is None
    assert config.mcp_app_content_origin is None


@pytest.mark.parametrize("field", LINKS)
@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "data:text/html,<p>x</p>",
        "ftp://files.example.com/statement",
        "/relative/statement",
        "https://",
        "https://example.com:port/",
    ],
)
def test_links_keep_only_http_urls(test_settings: Settings, field: str, value: str):
    config = build_runtime_config(_settings(test_settings, **{field: value}))

    assert getattr(config, field) is None


@pytest.mark.parametrize("field", LINKS)
def test_links_keep_http_and_https_urls(test_settings: Settings, field: str):
    https = build_runtime_config(
        _settings(test_settings, **{field: "https://example.com/a?b=c"})
    )
    http = build_runtime_config(_settings(test_settings, **{field: "http://intra/x"}))

    assert getattr(https, field) == "https://example.com/a?b=c"
    assert getattr(http, field) == "http://intra/x"


def test_help_center_requires_flag(test_settings: Settings):
    url = "https://help.example.com/"

    hidden = build_runtime_config(_settings(test_settings, help_center_url=url))
    shown = build_runtime_config(
        _settings(test_settings, help_center_url=url, show_help_center=True)
    )
    rejected = build_runtime_config(
        _settings(test_settings, help_center_url="javascript:x", show_help_center=True)
    )

    assert hidden.help_center_url is None
    assert shown.help_center_url == url
    assert rejected.help_center_url is None


@pytest.mark.parametrize(
    ("base_url", "origin"),
    [
        ("https://views.example.com/base/path", "https://views.example.com"),
        ("http://localhost:8123/", "http://localhost:8123"),
        ("https://views.example.com:8443/x", "https://views.example.com:8443"),
        ("HTTPS://Views.Example.com", "https://views.example.com"),
        ("https://views.example.com:443/x", "https://views.example.com"),
        ("http://[::1]:8123/x", "http://[::1]:8123"),
        ("", None),
        ("   ", None),
    ],
)
def test_mcp_origin_strips_path(
    test_settings: Settings, base_url: str, origin: str | None
):
    config = build_runtime_config(
        _settings(test_settings, mcp_app_content_base_url=base_url)
    )

    assert config.mcp_app_content_origin == origin


def test_version_and_revision_come_from_settings(test_settings: Settings):
    config = build_runtime_config(
        _settings(
            test_settings,
            app_version="9.8.7",
            app_revision="abc123",
        )
    )

    assert (config.version, config.revision) == ("9.8.7", "abc123")


async def test_endpoint_is_public_and_not_cached(test_settings: Settings):
    set_settings(
        _settings(
            test_settings,
            app_version="1.2.3",
            legacy_app_url="https://legacy.example.com",
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=get_application()), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/runtime-config")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["version"] == "1.2.3"
    assert body["legacy_app_url"] == "https://legacy.example.com"
    assert set(body) == {
        "version",
        "revision",
        "help_center_url",
        "legacy_app_url",
        "accessibility_statement_url",
        "request_integration_form_url",
        "mcp_app_content_origin",
    }


def test_startup_log_names_unlinked_values_without_values(
    test_settings: Settings, runtime_log: list[logging.LogRecord]
):
    settings = _settings(
        test_settings,
        help_center_url="https://help.example.com/secret-path",
        legacy_app_url="javascript:alert(1)",
        accessibility_statement_url="https://a11y.example.com/statement",
    )

    log_unlinked_runtime_values(settings)

    records = {record.levelno: record.getMessage() for record in runtime_log}
    assert set(records) == {logging.INFO, logging.WARNING}
    info, warning = records[logging.INFO], records[logging.WARNING]
    assert "HELP_CENTER_URL" in info
    assert "REQUEST_INTEGRATION_FORM_URL" in info
    assert "ACCESSIBILITY_STATEMENT_URL" not in info
    assert "LEGACY_APP_URL" in warning
    assert "MCP_APP_CONTENT_BASE_URL" not in warning
    for message in (info, warning):
        assert "example.com" not in message
        assert "javascript" not in message
        assert "://" not in message


@pytest.mark.parametrize("blank", ["", "   "])
def test_startup_log_treats_blank_mcp_base_url_as_unset(
    test_settings: Settings, runtime_log: list[logging.LogRecord], blank: str
):
    log_unlinked_runtime_values(
        _settings(test_settings, mcp_app_content_base_url=blank)
    )

    assert [record.levelno for record in runtime_log] == [logging.INFO]


@pytest.mark.parametrize(
    ("flags", "logged"),
    [
        ({}, False),
        # Either flag takes the same branch; the web app flag also needs a build.
        ({"browser_session_enabled": True}, True),
    ],
)
def test_startup_log_runs_only_for_the_browser_platform(
    test_settings: Settings,
    runtime_log: list[logging.LogRecord],
    flags: dict[str, bool],
    logged: bool,
):
    set_settings(_settings(test_settings, **flags))

    get_application()

    assert logged == bool(runtime_log)


def test_endpoint_declared_public():
    policy = access_for(get_runtime_config)

    assert policy is not None
    assert policy.authentication is Authentication.PUBLIC
    assert policy.authorization is Authorization.PUBLIC
    operation = get_application().openapi()["paths"]["/api/v1/runtime-config"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WebRuntimeConfig"
    }
