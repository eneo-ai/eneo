from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest

from eneo.object_content.content import (
    CapturedContent,
    ContentAccessClass,
    ContentIntent,
    StorageKind,
    content_request_fingerprint,
)


def _content() -> CapturedContent:
    return CapturedContent(
        file=BytesIO(b"content"),
        sha256=b"a" * 32,
        size_bytes=7,
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        part_sha256=(b"b" * 32,),
        part_size_bytes=7,
    )


def _intent() -> ContentIntent:
    return ContentIntent(
        tenant_id=uuid4(),
        created_by_user_id=uuid4(),
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        idempotency_key="request-1",
        producer_receipt="file:owner-id:original:0",
        minimum_retain_until=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )


def _legacy_object_store_fingerprint(
    intent: ContentIntent,
    content: CapturedContent,
) -> bytes:
    """Reproduce the persisted object-store request-v1 encoding."""
    fingerprint = sha256()
    fingerprint.update(b"eneo-object-content-request-v1\0")
    created_by = (
        b"" if intent.created_by_user_id is None else intent.created_by_user_id.bytes
    )
    minimum_retain_until = (
        b""
        if intent.minimum_retain_until is None
        else intent.minimum_retain_until.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .encode()
    )
    fields = (
        intent.producer_receipt.encode(),
        created_by,
        intent.access_class.value.encode(),
        minimum_retain_until,
        content.sha256,
        content.size_bytes.to_bytes(8, "big", signed=False),
        content.declared_media_type.encode(),
        content.verified_media_type.encode(),
    )
    for field in fields:
        fingerprint.update(len(field).to_bytes(8, "big", signed=False))
        fingerprint.update(field)
    return fingerprint.digest()


def test_request_fingerprint_binds_owner_intent_and_canonical_facts() -> None:
    intent = _intent()
    content = _content()
    baseline = content_request_fingerprint(
        intent,
        content,
        StorageKind.OBJECT_STORE,
    )

    assert len(baseline) == 32
    assert baseline == _legacy_object_store_fingerprint(intent, content)
    assert (
        content_request_fingerprint(intent, content, StorageKind.OBJECT_STORE)
        == baseline
    )
    assert (
        content_request_fingerprint(
            intent,
            content,
            StorageKind.POSTGRES_INLINE,
        )
        != baseline
    )
    assert (
        content_request_fingerprint(
            replace(intent, producer_receipt="file:other-owner:original:0"),
            content,
            StorageKind.OBJECT_STORE,
        )
        != baseline
    )
    assert (
        content_request_fingerprint(
            intent,
            replace(content, sha256=b"c" * 32),
            StorageKind.OBJECT_STORE,
        )
        != baseline
    )
    assert (
        content_request_fingerprint(
            replace(intent, access_class=ContentAccessClass.PUBLIC_IMMUTABLE),
            content,
            StorageKind.OBJECT_STORE,
        )
        != baseline
    )
    assert (
        content_request_fingerprint(
            replace(intent, created_by_user_id=uuid4()),
            content,
            StorageKind.OBJECT_STORE,
        )
        != baseline
    )
    assert (
        content_request_fingerprint(
            replace(
                intent,
                minimum_retain_until=datetime(2027, 1, 2, tzinfo=timezone.utc),
            ),
            content,
            StorageKind.OBJECT_STORE,
        )
        != baseline
    )
    assert (
        content_request_fingerprint(
            replace(
                intent,
                minimum_retain_until=datetime(
                    2027,
                    1,
                    1,
                    1,
                    tzinfo=timezone(timedelta(hours=1)),
                ),
            ),
            content,
            StorageKind.OBJECT_STORE,
        )
        == baseline
    )


@pytest.mark.parametrize("value", ["", "x" * 256])
def test_intent_rejects_unbounded_idempotency_keys(value: str) -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        replace(_intent(), idempotency_key=value)


def test_intent_rejects_naive_retention_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        replace(_intent(), minimum_retain_until=datetime(2027, 1, 1))
