from collections.abc import Iterator

import pytest

from eneo.main.config import Settings, get_settings, set_settings


@pytest.fixture(scope="module")
def installed_settings(test_settings: Settings) -> Iterator[Settings]:
    original = get_settings()
    set_settings(test_settings)
    try:
        yield test_settings
        assert get_settings() is test_settings
    finally:
        set_settings(original)


def test_unit_settings_cleanup_restores_outer_settings(installed_settings: Settings):
    replacement = installed_settings.model_copy(update={"redis_port": 6380})
    set_settings(replacement)
    assert get_settings() is replacement
