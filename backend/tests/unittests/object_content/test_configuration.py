from uuid import UUID

import pytest
from pydantic import ValidationError

from eneo.object_content.configuration import ObjectContentSettings


def test_object_content_configuration_is_mandatory_and_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ObjectContentSettings(_env_file=None)


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
