import pytest
from opentelemetry.util.http import parse_excluded_urls

from eneo.main.observability import _EXCLUDED_URLS


@pytest.mark.parametrize(
    ("url", "excluded"),
    [
        ("http://h/assets/app-1.js", True),
        ("http://h/healthz", True),
        ("http://h/api/healthz", True),
        ("http://h/api/v1/spaces/", False),
        ("http://h/api/v1/x/assets/y", False),
    ],
)
def test_otel_skips_static_assets_and_health_probes(url: str, excluded: bool):
    assert parse_excluded_urls(_EXCLUDED_URLS).url_disabled(url) is excluded
