import os
from uuid import UUID

import pytest
from pydantic import ValidationError

from eneo.object_content.configuration import (
    ObjectContentCoreSettings,
    ObjectContentSettings,
    load_object_content_core_settings,
    load_object_content_settings,
)


def _clear_object_content_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("OBJECT_CONTENT_"):
            monkeypatch.delenv(name, raising=False)


def test_explicit_object_content_settings_are_mandatory_and_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ObjectContentSettings(_env_file=None)


def test_absent_object_store_environment_keeps_inline_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_object_content_environment(monkeypatch)

    assert load_object_content_settings() is None
    assert load_object_content_core_settings().inline_maximum_bytes == 200 * 1024**2


def test_inline_tuning_does_not_require_object_store_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_object_content_environment(monkeypatch)
    monkeypatch.setenv("OBJECT_CONTENT_INLINE_MAXIMUM_BYTES", "2097152")
    monkeypatch.setenv("OBJECT_CONTENT_INLINE_IO_CHUNK_BYTES", "65536")

    assert load_object_content_settings() is None
    assert load_object_content_core_settings() == ObjectContentCoreSettings(
        _env_file=None,
        inline_maximum_bytes=2 * 1024**2,
        inline_io_chunk_bytes=64 * 1024,
    )


def test_partial_object_content_environment_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_object_content_environment(monkeypatch)
    monkeypatch.setenv("OBJECT_CONTENT_ENDPOINT_URL", "https://objects.example.test")

    with pytest.raises(ValidationError):
        load_object_content_settings()


def test_object_content_configuration_accepts_private_reference_endpoint() -> None:
    settings = ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://object-content:8333",
        region="local",
        bucket="eneo-content",
        access_key_id="test-access",
        secret_access_key="test-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        allow_insecure_http=True,
    )

    assert settings.endpoint_url == "http://object-content:8333"
    assert settings.bucket == "eneo-content"
    assert settings.secret_access_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)


def test_rejected_endpoint_credentials_are_not_rendered_by_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep both sentinels short enough that Pydantic cannot hide them through
    # its generic middle-of-value truncation.
    sentinel_username = "s3usr"
    sentinel_password = "p4ss"

    _clear_object_content_environment(monkeypatch)
    monkeypatch.setenv(
        "OBJECT_CONTENT_ENDPOINT_URL",
        f"https://{sentinel_username}:{sentinel_password}@objects.example.test",
    )
    monkeypatch.setenv("OBJECT_CONTENT_REGION", "local")
    monkeypatch.setenv("OBJECT_CONTENT_BUCKET", "eneo-content")
    monkeypatch.setenv("OBJECT_CONTENT_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("OBJECT_CONTENT_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv(
        "OBJECT_CONTENT_DEPLOYMENT_ID",
        "a2d539af-fef0-42aa-a7f8-14376947be2c",
    )

    with pytest.raises(ValidationError) as captured:
        load_object_content_settings()

    rendered = str(captured.value)
    assert sentinel_username not in rendered
    assert sentinel_password not in rendered


def test_binding_claim_covers_the_readiness_request_window() -> None:
    with pytest.raises(ValidationError, match="binding_claim_seconds"):
        ObjectContentSettings(
            _env_file=None,
            endpoint_url="https://objects.example.test",
            region="local",
            bucket="eneo-content",
            access_key_id="test-access",
            secret_access_key="test-secret",
            deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
            readiness_timeout_seconds=10,
            binding_claim_seconds=24,
        )


@pytest.mark.parametrize(
    "endpoint_url",
    ("http://object-content:8333", "HTTP://object-content:8333"),
)
def test_object_content_configuration_rejects_unapproved_plain_http(
    endpoint_url: str,
) -> None:
    with pytest.raises(ValidationError, match="allow_insecure_http"):
        ObjectContentSettings(
            _env_file=None,
            endpoint_url=endpoint_url,
            region="local",
            bucket="eneo-content",
            access_key_id="test-access",
            secret_access_key="test-secret",
            deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        )


def test_deployment_tuning_has_no_hidden_business_ceiling() -> None:
    settings = ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://object-content:8333",
        region="local",
        bucket="eneo-content",
        access_key_id="test-access",
        secret_access_key="test-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        allow_insecure_http=True,
        connect_timeout_seconds=3_600,
        read_timeout_seconds=86_400,
        reconciliation_batch_size=1_000,
        reconciliation_lease_seconds=300_000,
        reconciliation_retry_max_seconds=86_400,
    )

    assert "maximum_size_bytes" not in ObjectContentSettings.model_fields
    assert settings.reconciliation_batch_size == 1_000
    assert settings.reconciliation_retry_max_seconds == 86_400


def test_reconciliation_batch_respects_the_portable_s3_page_bound() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 1000"):
        ObjectContentSettings(
            _env_file=None,
            endpoint_url="http://object-content:8333",
            region="local",
            bucket="eneo-content",
            access_key_id="test-access",
            secret_access_key="test-secret",
            deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
            allow_insecure_http=True,
            reconciliation_batch_size=1_001,
        )


def test_multipart_envelope_respects_the_s3_object_size_bound() -> None:
    gibibyte = 1024**3
    tebibyte = 1024**4
    settings = ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://object-content:8333",
        region="local",
        bucket="eneo-content",
        access_key_id="test-access",
        secret_access_key="test-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        allow_insecure_http=True,
        multipart_part_bytes=5 * gibibyte,
        multipart_threshold_bytes=5 * gibibyte,
    )

    assert settings.maximum_multipart_bytes == 5 * tebibyte


def test_multipart_threshold_cannot_bypass_the_single_put_limit() -> None:
    gibibyte = 1024**3
    with pytest.raises(ValidationError, match="less than or equal to 5368709120"):
        ObjectContentSettings(
            _env_file=None,
            endpoint_url="http://object-content:8333",
            region="local",
            bucket="eneo-content",
            access_key_id="test-access",
            secret_access_key="test-secret",
            deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
            allow_insecure_http=True,
            multipart_threshold_bytes=5 * gibibyte + 1,
        )
