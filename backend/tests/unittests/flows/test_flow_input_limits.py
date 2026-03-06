from types import SimpleNamespace

import pytest

from intric.flows.flow_input_limits import (
    DEFAULT_MAX_AUDIO_FILES_PER_RUN,
    apply_flow_input_limits_patch,
    effective_flow_input_limit,
    effective_max_files_per_run,
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


# --- File count fields ---


def test_resolve_defaults_includes_file_count_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: _app_settings(upload=10_000_000, transcription=25_000_000),
    )

    limits = resolve_flow_input_limits(None)

    assert limits.max_files_per_run is None
    assert limits.audio_max_files_per_run == DEFAULT_MAX_AUDIO_FILES_PER_RUN


def test_resolve_uses_tenant_file_count_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: _app_settings(upload=10_000_000, transcription=25_000_000),
    )

    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "max_files_per_run": 50,
                "audio_max_files_per_run": 20,
            }
        }
    )

    assert limits.max_files_per_run == 50
    assert limits.audio_max_files_per_run == 20


def test_resolve_falls_back_for_malformed_file_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.flow_input_limits.get_settings",
        lambda: _app_settings(upload=10_000_000, transcription=25_000_000),
    )

    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "max_files_per_run": "not-a-number",
                "audio_max_files_per_run": True,
            }
        }
    )

    assert limits.max_files_per_run is None
    assert limits.audio_max_files_per_run == DEFAULT_MAX_AUDIO_FILES_PER_RUN


def test_apply_patch_updates_file_count_fields() -> None:
    current = {
        "input_limits": {
            "file_max_size_bytes": 10_000_000,
        },
    }

    updated = apply_flow_input_limits_patch(current, max_files_per_run=50)

    assert updated["input_limits"]["max_files_per_run"] == 50
    assert updated["input_limits"]["file_max_size_bytes"] == 10_000_000


def test_apply_patch_removes_keys_for_explicit_null() -> None:
    current = {
        "input_limits": {
            "max_files_per_run": 50,
            "audio_max_files_per_run": 20,
        },
    }

    updated = apply_flow_input_limits_patch(
        current, remove_keys={"max_files_per_run", "audio_max_files_per_run"}
    )

    assert "max_files_per_run" not in updated["input_limits"]
    assert "audio_max_files_per_run" not in updated["input_limits"]


def test_apply_patch_rejects_out_of_range_file_count() -> None:
    with pytest.raises(BadRequestException, match="max_files_per_run"):
        apply_flow_input_limits_patch({}, max_files_per_run=0)

    with pytest.raises(BadRequestException, match="audio_max_files_per_run"):
        apply_flow_input_limits_patch({}, audio_max_files_per_run=-1)


def test_effective_max_files_audio_vs_generic() -> None:
    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "max_files_per_run": 100,
                "audio_max_files_per_run": 20,
            }
        },
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )

    assert effective_max_files_per_run(input_type="audio", limits=limits) == 20
    assert effective_max_files_per_run(input_type="document", limits=limits) == 100
    assert effective_max_files_per_run(input_type="file", limits=limits) == 100
