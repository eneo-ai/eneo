import pytest
from pydantic import ValidationError

from eneo.whats_new.whats_new_models import WhatsNewSeenUpdate


@pytest.mark.parametrize("version", ["2.2.0", "10.0.1", "2.3.0-rc.1", "3.0.0-beta"])
def test_accepts_release_versions_as_written_in_releases_json(version: str):
    assert WhatsNewSeenUpdate(version=version).version == version


@pytest.mark.parametrize("version", ["v2.2.0", "2.2", "latest", "", "2.2.0 "])
def test_rejects_versions_that_cannot_match_a_release(version: str):
    with pytest.raises(ValidationError):
        WhatsNewSeenUpdate(version=version)
