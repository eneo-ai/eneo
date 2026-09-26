import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eneo.flows.flow_input_limits import (
    DEFAULT_MAX_AUDIO_FILES_PER_RUN,
    apply_flow_input_limits_patch,
    effective_flow_input_limit,
    effective_max_files_per_run,
    effective_runtime_max_files,
    effective_runtime_upload_policy,
    resolve_flow_input_limits,
    validate_flow_input_limits_object,
)
from eneo.main.exceptions import BadRequestException


def _app_settings(upload: int, transcription: int) -> SimpleNamespace:
    return SimpleNamespace(
        session_file_maximum_bytes=upload,
        session_audio_maximum_bytes=transcription,
    )


def test_resolve_defaults_when_tenant_settings_missing() -> None:
    limits = resolve_flow_input_limits(
        None,
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )

    assert limits.file_max_size_bytes == 10_000_000
    assert limits.audio_max_size_bytes == 25_000_000


def test_resolve_uses_tenant_overrides() -> None:
    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "file_max_size_bytes": 12_000_000,
                "audio_max_size_bytes": 32_000_000,
            }
        },
        defaults=_app_settings(upload=20_000_000, transcription=40_000_000),
    )

    assert limits.file_max_size_bytes == 12_000_000
    assert limits.audio_max_size_bytes == 32_000_000


def test_resolve_caps_tenant_overrides_at_upload_admission() -> None:
    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "file_max_size_bytes": 30_000_000,
                "audio_max_size_bytes": 40_000_000,
            }
        },
        defaults=_app_settings(upload=20_000_000, transcription=25_000_000),
    )

    assert limits.file_max_size_bytes == 20_000_000
    assert limits.audio_max_size_bytes == 25_000_000


def test_resolve_rejects_malformed_settings() -> None:
    with pytest.raises(BadRequestException, match="file_max_size_bytes"):
        resolve_flow_input_limits(
            {
                "input_limits": {
                    "file_max_size_bytes": "oops",
                    "audio_max_size_bytes": -123,
                }
            },
            defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
        )


def test_resolve_rejects_boolean_limit_values() -> None:
    with pytest.raises(BadRequestException, match="file_max_size_bytes"):
        resolve_flow_input_limits(
            {
                "input_limits": {
                    "file_max_size_bytes": True,
                    "audio_max_size_bytes": False,
                }
            },
            defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
        )


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


def test_validate_accepts_all_known_input_limit_fields() -> None:
    payload = {
        "file_max_size_bytes": 10_000_000,
        "audio_max_size_bytes": 25_000_000,
        "max_files_per_run": 50,
        "audio_max_files_per_run": 10,
    }

    assert validate_flow_input_limits_object(payload) == payload


def test_validate_rejects_unknown_input_limit_field() -> None:
    with pytest.raises(
        BadRequestException,
        match="flow_settings.input_limits contains unknown fields: unknown",
    ):
        validate_flow_input_limits_object({"unknown": 1})


def test_validate_rejects_unknown_input_limit_field_mixed_with_valid_field() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        validate_flow_input_limits_object(
            {"file_max_size_bytes": 10_000_000, "typo": 1}
        )

    message = str(exc_info.value)
    assert "typo" in message
    assert "file_max_size_bytes" not in message


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


def test_resolve_defaults_includes_file_count_fields() -> None:
    limits = resolve_flow_input_limits(
        None,
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )

    assert limits.max_files_per_run == 1000
    assert limits.audio_max_files_per_run == DEFAULT_MAX_AUDIO_FILES_PER_RUN


def test_resolve_uses_tenant_file_count_overrides() -> None:
    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "max_files_per_run": 50,
                "audio_max_files_per_run": 20,
            }
        },
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )

    assert limits.max_files_per_run == 50
    assert limits.audio_max_files_per_run == 20


def test_resolve_treats_null_counts_as_finite_defaults() -> None:
    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "max_files_per_run": None,
                "audio_max_files_per_run": None,
            }
        },
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )

    assert limits.max_files_per_run == 1000
    assert limits.audio_max_files_per_run == DEFAULT_MAX_AUDIO_FILES_PER_RUN


def test_resolve_rejects_malformed_file_count() -> None:
    with pytest.raises(BadRequestException, match="max_files_per_run"):
        resolve_flow_input_limits(
            {
                "input_limits": {
                    "max_files_per_run": "not-a-number",
                    "audio_max_files_per_run": True,
                }
            },
            defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
        )


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


def test_effective_runtime_max_files_uses_stricter_step_or_tenant_limit() -> None:
    limits = resolve_flow_input_limits(
        {
            "input_limits": {
                "max_files_per_run": 5,
                "audio_max_files_per_run": 3,
            }
        },
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )

    assert (
        effective_runtime_max_files(
            input_type="document", step_max_files=None, limits=limits
        )
        == 5
    )
    assert (
        effective_runtime_max_files(
            input_type="document", step_max_files=2, limits=limits
        )
        == 2
    )
    assert (
        effective_runtime_max_files(
            input_type="document", step_max_files=10, limits=limits
        )
        == 5
    )
    assert (
        effective_runtime_max_files(
            input_type="audio", step_max_files=10, limits=limits
        )
        == 3
    )


def test_effective_runtime_upload_policy_exposes_client_timeout_formula() -> None:
    policy = effective_runtime_upload_policy()

    assert policy.min_timeout_seconds == 120
    assert policy.seconds_per_mebibyte == 8
    assert policy.max_timeout_seconds == 600
    assert policy.idle_timeout_seconds == 120


@pytest.mark.parametrize(
    "locale,ceiling_word,unlimited_word",
    [
        ("en", "deployment limit", "unlimited"),
        ("sv", "driftmiljöns gräns", "obegränsat"),
    ],
)
def test_admin_empty_file_limit_copy_names_deployment_ceiling(
    locale, ceiling_word, unlimited_word
):
    messages_path = (
        Path(__file__).resolve().parents[4]
        / "frontend/apps/web/messages"
        / f"{locale}.json"
    )
    messages = json.loads(messages_path.read_text())
    for key in (
        "flow_input_limits_max_files_description",
        "flow_input_limits_unlimited_hint",
    ):
        assert ceiling_word in messages[key].lower()
        assert unlimited_word not in messages[key].lower()


# The longest recording a flow takes: the admin's value on the flow-settings page, below the deployment's flow
# ceiling, and by default the deployment's audio duration.


def _durations(default: int, ceiling: int) -> SimpleNamespace:
    return SimpleNamespace(
        flow_audio_max_duration_seconds=default,
        flow_audio_max_duration_ceiling_seconds=ceiling,
        flow_audio_max_decoded_bytes=2 * 1024**3,
    )


def test_resolve_audio_duration_defaults_to_the_deployment_value(monkeypatch) -> None:
    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings", lambda: _durations(18_000, 28_800)
    )
    limits = resolve_flow_input_limits(
        None, defaults=_app_settings(upload=10_000_000, transcription=25_000_000)
    )
    assert limits.audio_max_duration_seconds == 18_000


def test_resolve_audio_duration_default_stays_under_the_flow_ceiling(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings", lambda: _durations(36_000, 28_800)
    )
    limits = resolve_flow_input_limits(
        None, defaults=_app_settings(upload=10_000_000, transcription=25_000_000)
    )
    assert limits.audio_max_duration_seconds == 28_800


@pytest.mark.parametrize(
    ("tenant", "expected"), [(21_600, 21_600), (3_600, 3_600), (40_000, 28_800)]
)
def test_resolve_uses_the_tenant_audio_duration_up_to_the_flow_ceiling(
    monkeypatch, tenant: int, expected: int
) -> None:
    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings", lambda: _durations(18_000, 28_800)
    )
    limits = resolve_flow_input_limits(
        {"input_limits": {"audio_max_duration_seconds": tenant}},
        defaults=_app_settings(upload=10_000_000, transcription=25_000_000),
    )
    assert limits.audio_max_duration_seconds == expected


def test_apply_patch_sets_and_removes_the_audio_duration() -> None:
    patched = apply_flow_input_limits_patch(None, audio_max_duration_seconds=21_600)
    assert patched["input_limits"] == {"audio_max_duration_seconds": 21_600}
    removed = apply_flow_input_limits_patch(
        patched, remove_keys={"audio_max_duration_seconds"}
    )
    assert removed["input_limits"] == {}


@pytest.mark.parametrize("value", [0, -1, True, 1.5, 59, 24 * 60 * 60 + 1])
def test_the_audio_duration_is_whole_seconds_from_a_minute_to_a_day(value) -> None:
    assert validate_flow_input_limits_object({"audio_max_duration_seconds": 3600}) == {
        "audio_max_duration_seconds": 3600
    }
    with pytest.raises(BadRequestException):
        validate_flow_input_limits_object({"audio_max_duration_seconds": value})


def test_flow_decode_limits_take_the_tenant_duration_and_the_deployment_bytes(
    monkeypatch,
) -> None:
    from eneo.flows.flow_input_limits import FlowInputLimits, flow_audio_decode_limits

    monkeypatch.setattr(
        "eneo.flows.flow_input_limits.get_settings", lambda: _durations(18_000, 28_800)
    )
    limits = FlowInputLimits(
        file_max_size_bytes=1,
        audio_max_size_bytes=1,
        audio_max_duration_seconds=21_600,
    )
    decode = flow_audio_decode_limits(limits)
    assert decode.max_duration_seconds == 21_600
    assert decode.max_decoded_bytes == 2 * 1024**3
    # A limits object built without the field reads the deployment default.
    unset = flow_audio_decode_limits(
        FlowInputLimits(file_max_size_bytes=1, audio_max_size_bytes=1)
    )
    assert unset.max_duration_seconds == 18_000
