from types import SimpleNamespace

import pytest

from intric.flows.flow_input_limits import (
    apply_flow_input_limits_patch,
    effective_flow_input_limit,
    resolve_flow_input_limits,
)
from intric.main.exceptions import BadRequestException


def _app_settings(upload: int, transcription: int) -> SimpleNamespace:
    return SimpleNamespace(
        upload_max_file_size=upload,
        transcription_max_file_size=transcription,
    )


def test_resolve_defaults_when_tenant_settings_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: _app_settings(upload=10_000_000, transcription=25_000_000),
    )

    limits = resolve_flow_input_limits(None)

    assert limits.file_max_size_bytes == 10_000_000
    assert limits.audio_max_size_bytes == 25_000_000


def test_resolve_uses_tenant_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: _app_settings(upload=10_000_000, transcription=25_000_000),
    )

    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "file_max_size_bytes": 12_000_000,
                "audio_max_size_bytes": 32_000_000,
            }
        }
    )

    assert limits.file_max_size_bytes == 12_000_000
    assert limits.audio_max_size_bytes == 32_000_000


def test_resolve_falls_back_for_malformed_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: _app_settings(upload=10_000_000, transcription=25_000_000),
    )

    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "file_max_size_bytes": "oops",
                "audio_max_size_bytes": -123,
            }
        }
    )

    assert limits.file_max_size_bytes == 10_000_000
    assert limits.audio_max_size_bytes == 25_000_000


def test_resolve_falls_back_for_boolean_limit_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: _app_settings(upload=10_000_000, transcription=25_000_000),
    )

    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "file_max_size_bytes": True,
                "audio_max_size_bytes": False,
            }
        }
    )

    assert limits.file_max_size_bytes == 10_000_000
    assert limits.audio_max_size_bytes == 25_000_000


def test_apply_patch_updates_only_requested_fields() -> None:
    current = {
        "input_limits": {
            "file_max_size_bytes": 10_000_000,
            "audio_max_size_bytes": 25_000_000,
        },
        "other": {"preserve": True},
    }

    updated = apply_flow_input_limits_patch(current, audio_max_size_bytes=33_000_000)

    assert updated["input_limits"]["file_max_size_bytes"] == 10_000_000
    assert updated["input_limits"]["audio_max_size_bytes"] == 33_000_000
    assert updated["other"] == {"preserve": True}


def test_apply_patch_rejects_out_of_range() -> None:
    with pytest.raises(BadRequestException, match="audio_max_size_bytes"):
        apply_flow_input_limits_patch({}, audio_max_size_bytes=0)


def test_apply_patch_rejects_boolean_values() -> None:
    with pytest.raises(BadRequestException, match="file_max_size_bytes"):
        apply_flow_input_limits_patch({}, file_max_size_bytes=True)


def test_effective_limit_prefers_audio_for_audio_type() -> None:
    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "file_max_size_bytes": 10_000_000,
                "audio_max_size_bytes": 25_000_000,
            }
        },
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )

    assert effective_flow_input_limit(input_type="audio", limits=limits) == 25_000_000
    assert effective_flow_input_limit(input_type="text", limits=limits) == 10_000_000
