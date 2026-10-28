import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from eneo.main.config import Settings, get_settings

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
    assert settings.show_web_search is False
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


def test_development_cookie_allowed_on_localhost():
    settings = _settings(
        browser_session_enabled=True,
        environment="development",
        public_origin="http://localhost:3101",
    )

    assert settings.browser_session_enabled is True


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
    names |= {"SHOW_WEB_SEARCH", "SHOW_HELP_CENTER"}
    for template in (
        REPO_ROOT / "backend/.env.template",
        REPO_ROOT / "docs/deployment/env_backend.template",
    ):
        declared = set(
            re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]+)=", template.read_text())
        )
        assert names <= declared, template
