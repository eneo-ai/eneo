import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from eneo.flows.domain.step_output import build_rejected_output_payload
from eneo.flows.flow_input_limits import (
    FLOW_INPUT_MAX_LIMIT_BYTES,
    resolve_flow_input_limits,
)
from eneo.flows.flow_runtime_policy import default_flow_runtime_policy
from eneo.flows.runtime.structured_output_budget import ensure_structured_output_allowed
from eneo.main.config import Settings
from eneo.main.exceptions import TypedIOValidationException
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import (
    DeploymentPolicy,
    PolicyActor,
    project_upload_limits,
)

DEFAULTS = {
    "task_execution_timeout_seconds": 28800,
    "flow_audio_max_duration_seconds": 18000,
    "flow_audio_max_decoded_bytes": 2147483648,
    "flow_max_inline_text_bytes": 8388608,
    "flow_mapped_step_max_provider_calls_default": 1000,
    "flow_pdf_max_pages": 2000,
    "flow_pdf_max_extracted_bytes": 134217728,
    "flow_pdf_extraction_timeout_seconds": 900,
    "attachment_max_size_bytes": 268435456,
    "attachment_max_files": 100,
    "ai_builder_proposal_timeout_seconds": 300.0,
}


@pytest.fixture
def defaults(monkeypatch):
    for name in DEFAULTS:
        monkeypatch.delenv(name.upper(), raising=False)
    return Settings(_env_file=None)


@pytest.mark.parametrize(("name", "expected"), DEFAULTS.items())
def test_flow_defaults(defaults, name, expected):
    assert getattr(defaults, name) == expected


def test_inline_storage_default(monkeypatch):
    monkeypatch.delenv("OBJECT_CONTENT_INLINE_MAXIMUM_BYTES", raising=False)
    assert ObjectContentCoreSettings().inline_maximum_bytes == 1073741819


def test_invocation_budget_preserves_finalization_reserve(defaults):
    policy = default_flow_runtime_policy(defaults=defaults)
    assert policy.default_step_timeout_seconds == 28740
    assert policy.max_step_timeout_seconds == 28740
    assert policy.hard_ceiling_seconds == 28740


@pytest.mark.parametrize(
    "name",
    [
        "task_execution_timeout_seconds",
        "flow_audio_max_duration_seconds",
        "flow_audio_max_decoded_bytes",
        "flow_max_inline_text_bytes",
        "flow_mapped_step_max_provider_calls_default",
        "ai_builder_proposal_timeout_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_flow_limits_reject_nonpositive_values(name, value):
    with pytest.raises(SystemExit):
        Settings(**{name: value})


@pytest.mark.parametrize("value", [0, -1, 1073741824])
def test_inline_storage_rejects_invalid_sizes(value):
    with pytest.raises(ValidationError):
        ObjectContentCoreSettings(inline_maximum_bytes=value)


def test_migrated_upload_defaults_admit_large_workloads(monkeypatch):
    path = (
        Path(__file__).parents[3]
        / "alembic/versions/202609202000_raise_upload_policy_defaults.py"
    )
    spec = importlib.util.spec_from_file_location("upload_policy_defaults", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    limits_after_migration = {name: new for name, (_, new) in module._LIMITS.items()}
    assert limits_after_migration == {
        "session_file_limit_bytes": 268435456,
        "knowledge_file_limit_bytes": 268435456,
        "transcription_audio_limit_bytes": 1073741819,
    }
    monkeypatch.delenv("OBJECT_CONTENT_INLINE_MAXIMUM_BYTES", raising=False)
    policy = DeploymentPolicy(
        revision=1,
        new_write_storage_target=StorageKind.POSTGRES_INLINE,
        moves_paused=False,
        updated_by_actor=PolicyActor.MIGRATION,
        updated_by_user_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        session_image_limit_bytes=10485760,
        **limits_after_migration,
    )
    projections = {
        item.use_case.value: item.effective_bytes
        for item in project_upload_limits(
            policy,
            inline_maximum_bytes=ObjectContentCoreSettings().inline_maximum_bytes,
            object_store_maximum_bytes=None,
        )
    }
    for use_case in ("session_audio", "knowledge_audio"):
        assert projections[use_case] == 1073741819
        assert projections[use_case] >= 18000 * 128000 // 8
    for use_case in ("session_file", "knowledge_file"):
        assert projections[use_case] == 268435456
    limits = resolve_flow_input_limits(
        None,
        defaults=SimpleNamespace(
            session_file_maximum_bytes=projections["session_file"],
            session_audio_maximum_bytes=projections["session_audio"],
        ),
    )
    assert limits.file_max_size_bytes == 268435456
    assert limits.audio_max_size_bytes == 1073741819
    assert limits.max_files_per_run == 1000
    assert limits.audio_max_files_per_run == 10
    assert FLOW_INPUT_MAX_LIMIT_BYTES == 2147483648


def test_derived_output_bounds(defaults):
    text = "a" * 8388606
    ensure_structured_output_allowed(
        text, ceiling_bytes=defaults.flow_max_inline_text_bytes
    )
    with pytest.raises(TypedIOValidationException):
        ensure_structured_output_allowed(
            text + "a", ceiling_bytes=defaults.flow_max_inline_text_bytes
        )
    payload = build_rejected_output_payload(
        "å" * 4194305, max_inline_bytes=defaults.flow_max_inline_text_bytes
    )
    assert len(payload["rejected_output"].encode("utf-8")) == 8388608
    assert payload["rejected_output_truncated"] is True
