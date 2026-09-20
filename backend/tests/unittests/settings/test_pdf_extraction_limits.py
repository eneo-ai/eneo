import pytest
from pydantic import ValidationError

from eneo.main.config import Settings


def test_pdf_extraction_limit_defaults():
    settings = Settings()

    assert settings.flow_pdf_max_pages == 500
    assert settings.flow_pdf_max_extracted_bytes == 32 * 1024 * 1024
    assert settings.flow_pdf_extraction_timeout_seconds == 120


@pytest.mark.parametrize(
    "name",
    [
        "flow_pdf_max_pages",
        "flow_pdf_max_extracted_bytes",
        "flow_pdf_extraction_timeout_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_pdf_extraction_limits_must_be_positive(name, value):
    with pytest.raises(ValidationError, match=name):
        Settings(**{name: value})
