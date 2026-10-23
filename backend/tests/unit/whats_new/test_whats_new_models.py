import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eneo.whats_new.whats_new_models import (
    WhatsNewVersionUpdate,
    can_record_release,
    release_order_key,
)


@pytest.mark.parametrize(
    ("submitted", "installed", "allowed"),
    [
        ("2.3.0", "2.3.0-rc.1", False),
        ("2.3.0-rc.2", "2.3.0-rc.1", False),
        ("2.3.0-rc.1", "2.3.0-rc.1", True),
        ("2.3.0-rc.0", "2.3.0-rc.1", True),
        ("2.3.0-rc.10", "v2.3.0-rc.2", False),
        ("2.3.0", "2.3.0", True),
        ("2.3.0", "DEV", True),
    ],
)
def test_rc_backend_does_not_pre_record_a_later_release(
    submitted: str, installed: str, allowed: bool
):
    assert can_record_release(submitted, installed) is allowed


PACKAGE = Path(__file__).resolve().parents[4] / "frontend" / "packages" / "whats-new"


def test_release_order_matches_the_shared_cross_runtime_contract():
    versions: list[str] = json.loads(
        (PACKAGE / "version-order.cases.json").read_text()
    )["ordered"]
    for version in versions:
        assert WhatsNewVersionUpdate(version=version).version == version
    for older, newer in zip(versions, versions[1:]):
        assert release_order_key(older) < release_order_key(newer)


@pytest.mark.parametrize("version", ["2.2.0", "10.0.1", "2.3.0-rc.1", "3.0.0-beta"])
def test_accepts_release_versions_as_written_in_releases_json(version: str):
    assert WhatsNewVersionUpdate(version=version).version == version


@pytest.mark.parametrize("version", ["v2.2.0", "2.2", "latest", "", "2.2.0 "])
def test_rejects_versions_that_cannot_match_a_release(version: str):
    with pytest.raises(ValidationError):
        WhatsNewVersionUpdate(version=version)


def test_version_pattern_matches_the_release_notes_schema():
    """The backend accepts exactly the release ids releases.json may contain."""
    from eneo.whats_new.whats_new_models import RELEASE_VERSION_PATTERN

    schema_path = PACKAGE / "releases.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_pattern = schema["$defs"]["release"]["properties"]["version"]["pattern"]
    # The schema uses a non-capturing-free form; normalise both to compare intent.
    assert schema_pattern.replace("(-", "(?:-") == RELEASE_VERSION_PATTERN


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ("development", True),
        ("local", True),
        ("DEV ", True),
        ("test", False),
        ("staging", False),
        ("production", False),
    ],
)
def test_is_development_follows_the_environment_setting(
    environment: str, expected: bool
):
    from eneo.main.config import Settings

    assert Settings(environment=environment).is_development is expected  # type: ignore[call-arg]
