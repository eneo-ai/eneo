import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from eneo.main.config import Settings, get_settings
from eneo.mcp_apps.presentation import mcp_apps_router

REPO_ROOT = Path(__file__).parents[4]
LINKS = (
    "help_center_url",
    "legacy_app_url",
    "accessibility_statement_url",
    "request_integration_form_url",
)


def _settings(**updates: object) -> Settings:
    return Settings.model_validate({**get_settings().model_dump(), **updates})


def test_web_app_settings_default_off():
    settings = _settings()

    assert settings.browser_session_enabled is False
    assert settings.web_app_enabled is False
    assert settings.show_help_center is False


def test_blank_links_are_unset():
    settings = _settings(**{name: "" for name in LINKS})

    assert [getattr(settings, name) for name in LINKS] == [None] * len(LINKS)


def test_field_names_match_web_next_env_names():
    template = (REPO_ROOT / "docs/deployment/env_web_next.template").read_text()
    names = set(re.findall(r"(?m)^([A-Z][A-Z0-9_]+)=", template)) - {"SESSION_SECRET"}

    assert names
    assert {name.lower() for name in names} <= set(Settings.model_fields)


def test_development_cookie_refused_on_public_host():
    with pytest.raises(ValidationError, match="BROWSER_SESSION_ENABLED"):
        _settings(
            browser_session_enabled=True,
            environment="development",
            public_origin="https://eneo.example.se",
        )


@pytest.mark.parametrize("public_origin", [None, ""])
def test_development_cookie_refused_without_public_origin(public_origin: str | None):
    with pytest.raises(ValidationError, match="PUBLIC_ORIGIN"):
        _settings(
            browser_session_enabled=True,
            environment="development",
            public_origin=public_origin,
        )


@pytest.mark.parametrize(
    ("public_origin", "normalized"),
    [
        ("http://localhost:3101", "http://localhost:3101"),
        ("http://127.0.0.1:3101/", "http://127.0.0.1:3101"),
    ],
)
def test_development_cookie_allowed_on_localhost(public_origin: str, normalized: str):
    settings = _settings(
        browser_session_enabled=True,
        environment="development",
        public_origin=public_origin,
    )

    assert settings.browser_session_enabled is True
    assert settings.public_origin == normalized


def test_production_session_allowed():
    settings = _settings(
        browser_session_enabled=True,
        environment="production",
        public_origin="https://eneo.example.se",
    )

    assert settings.browser_session_enabled is True


def test_env_backend_template_lists_web_app_settings():
    names = {"BROWSER_SESSION_ENABLED", "WEB_APP_ENABLED"} | {
        name.upper() for name in LINKS
    }
    names.add("SHOW_HELP_CENTER")
    for template in (
        REPO_ROOT / "backend/.env.template",
        REPO_ROOT / "docs/deployment/env_backend.template",
    ):
        declared = set(
            re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]+)=", template.read_text())
        )
        assert names <= declared, template


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_mcp_content_base_url_is_unset(value: str):
    assert _settings(mcp_app_content_base_url=value).mcp_app_content_base_url is None


@pytest.mark.parametrize(
    "value",
    [
        # A browser would read each of these differently from the backend.
        "https://content.example.com *",
        "https://Bücher.example/",
        "https://content.example.com\\@evil.com/",
        "https://user:secret@content.example.com/",
        "https://content.example.com/views?x=1",
        "https://content.example.com/#views",
        "https://content.example.com?",
        "https://content.example.com#",
        "http://0x7f000001/",
        "http://127.1/",
        "http://0177.0.0.1/",
        "http://[fe80::1%25eth0]/",
        "http://[::ffff:127.0.0.1]/",
        "https://999.1.1.1/",
        "https://-content.example.com/",
        "https://content_views.example.com/",
        "https://content.example.com:port/",
        "https://[::1/",
        "ftp://content.example.com/",
        "content.example.com",
    ],
)
def test_mcp_content_base_url_must_read_the_same_in_a_browser(value: str):
    with pytest.raises(ValidationError, match="mcp_app_content_base_url") as error:
        _settings(mcp_app_content_base_url=value)

    assert value not in str(error.value)


@pytest.mark.parametrize(
    ("value", "stored", "host"),
    [
        # stored as a browser serializes it; host is the Host header it sends
        (
            "https://views.example.com/base",
            "https://views.example.com/base",
            "views.example.com",
        ),
        (" http://localhost:8123 ", "http://localhost:8123", "localhost:8123"),
        (
            "https://Content.Example.com:443/",
            "https://content.example.com/",
            "content.example.com",
        ),
        ("http://127.0.0.1:80/", "http://127.0.0.1/", "127.0.0.1"),
        (
            "http://[0:0:0:0:0:0:0:1]:8123/",
            "http://[::1]:8123/",
            "[::1]:8123",
        ),
        (
            "https://xn--bcher-kva.example",
            "https://xn--bcher-kva.example",
            "xn--bcher-kva.example",
        ),
        ("http://content.test", "http://content.test", "content.test"),
    ],
)
def test_mcp_content_base_url_is_stored_as_a_browser_reads_it(
    value: str, stored: str, host: str
):
    settings = _settings(mcp_app_content_base_url=value)

    assert settings.mcp_app_content_base_url == stored
    # The content endpoint recognises the Host header a browser sends for it.
    request = SimpleNamespace(headers={"host": host})
    with patch.object(mcp_apps_router, "get_settings", return_value=settings):
        assert mcp_apps_router._on_content_origin(request)  # pyright: ignore[reportPrivateUsage, reportArgumentType]


@pytest.mark.parametrize(
    ("content_base_url", "public_origin"),
    [
        ("https://eneo.example.se/views", "https://eneo.example.se"),
        ("https://ENEO.example.se:443/views", "https://eneo.example.se/"),
        ("http://[0:0::1]:8123/views", "http://[::1]:8123"),
    ],
)
def test_mcp_content_origin_must_differ_from_public_origin(
    content_base_url: str, public_origin: str
):
    with pytest.raises(SystemExit):
        _settings(
            mcp_app_content_base_url=content_base_url, public_origin=public_origin
        )


def test_mcp_content_origin_on_another_port_is_another_origin():
    settings = _settings(
        mcp_app_content_base_url="http://localhost:8124",
        public_origin="http://localhost:8123",
    )

    assert settings.mcp_app_content_base_url == "http://localhost:8124"
