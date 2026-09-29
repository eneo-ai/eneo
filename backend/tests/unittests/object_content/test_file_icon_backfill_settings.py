from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError

from eneo.object_content.file_icon_backfill import FileIconBackfillSettings


def test_file_icon_backfill_settings_use_measured_safe_defaults() -> None:
    settings = FileIconBackfillSettings()

    assert settings.batch_rows == 200
    assert settings.batch_bytes == 128 * 1024 * 1024


def test_file_icon_backfill_template_matches_runtime_defaults() -> None:
    template = dotenv_values(Path(__file__).resolve().parents[3] / ".env.template")
    batch_rows = template["FILE_ICON_BACKFILL_BATCH_ROWS"]
    batch_bytes = template["FILE_ICON_BACKFILL_BATCH_BYTES"]
    settings = FileIconBackfillSettings()

    assert batch_rows is not None
    assert batch_bytes is not None
    assert int(batch_rows) == settings.batch_rows
    assert int(batch_bytes) == settings.batch_bytes


def test_file_icon_backfill_settings_use_the_operator_runbook_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FILE_ICON_BACKFILL_AUTO_INLINE_MAX_BYTES", "4096")
    monkeypatch.setenv("FILE_ICON_BACKFILL_INLINE_CAPACITY_ACK", "8192")
    monkeypatch.setenv("FILE_ICON_BACKFILL_BATCH_ROWS", "25")
    monkeypatch.setenv("FILE_ICON_BACKFILL_BATCH_BYTES", "1048576")
    monkeypatch.setenv("FILE_ICON_BACKFILL_LEASE_SECONDS", "600")
    monkeypatch.setenv("FILE_ICON_BACKFILL_RESUME_REVISION", "3")
    monkeypatch.setenv("FILE_ICON_BACKFILL_MAX_ATTEMPTS", "4")

    settings = FileIconBackfillSettings()

    assert settings.auto_inline_max_bytes == 4096
    assert settings.inline_capacity_ack == 8192
    assert settings.batch_rows == 25
    assert settings.batch_bytes == 1_048_576
    assert settings.lease_seconds == 600
    assert settings.resume_revision == 3
    assert settings.max_attempts == 4


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("batch_rows", 0),
        ("batch_rows", 1001),
        ("batch_bytes", 0),
        ("lease_seconds", 0),
        ("inline_capacity_ack", -1),
        ("resume_revision", -1),
        ("max_attempts", 0),
    ),
)
def test_file_icon_backfill_settings_reject_unsafe_bounds(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        FileIconBackfillSettings(**{field: value})
