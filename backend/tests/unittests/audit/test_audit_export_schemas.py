import pytest
from pydantic import ValidationError

from intric.api.audit.schemas import ExportJobRequest


@pytest.mark.parametrize(
    ("raw_format", "expected"),
    [
        ("csv", "csv"),
        (" JSON ", "json"),
        ("jsonl", "jsonl"),
    ],
)
def test_export_job_request_normalizes_supported_formats(
    raw_format: str, expected: str
) -> None:
    request = ExportJobRequest.model_validate({"format": raw_format})

    assert request.format == expected


def test_export_job_request_rejects_unsupported_format() -> None:
    with pytest.raises(ValidationError):
        ExportJobRequest.model_validate({"format": "xml"})
