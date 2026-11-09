"""The adapter's answers when a bucket could keep deleted bytes.

A real store cannot deny one of these permissions alone, so the error
mapping is tested here against stubbed responses.
"""

from collections.abc import Generator
from uuid import UUID

import pytest
from botocore.stub import Stubber

from eneo.object_content.configuration import ObjectContentSettings
from eneo.object_content.content import ObjectContentConfigurationError
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionService,
    ObjectStoreProbeAuthenticationFailed,
    ObjectStoreProbeKeepsVersions,
)
from eneo.object_content.s3_object_store import (
    ObjectStoreError,
    ObjectStoreKeepsVersionsError,
    ObjectStorePermissionError,
    ObjectStoreUnavailableError,
    S3ObjectStore,
    new_object_key,
)

pytestmark = pytest.mark.asyncio

_PERMISSIONS = {
    "get_bucket_versioning": "s3:GetBucketVersioning",
    "get_object_lock_configuration": "s3:GetBucketObjectLockConfiguration",
    "list_object_versions": "s3:ListBucketVersions",
}


def _settings() -> ObjectContentSettings:
    return ObjectContentSettings(
        _env_file=None,
        endpoint_url="http://object-content:8333",
        region="local",
        bucket="eneo-content",
        access_key_id="test-access",
        secret_access_key="test-secret",
        deployment_id=UUID("a2d539af-fef0-42aa-a7f8-14376947be2c"),
        allow_insecure_http=True,
    )


@pytest.fixture
def store() -> Generator[S3ObjectStore, None, None]:
    store = S3ObjectStore(_settings())
    yield store
    store._client.close()
    store._readiness_client.close()


def _readiness(
    store: S3ObjectStore, *, failing: str | None = None, code: str = "AccessDenied"
) -> Stubber:
    """A plain bucket's answers, up to the read that fails with `code`."""
    stubber = Stubber(store._readiness_client)
    stubber.add_response("list_objects_v2", {"IsTruncated": False, "KeyCount": 0})
    for operation in _PERMISSIONS:
        if operation == failing:
            stubber.add_client_error(operation, service_error_code=code)
            return stubber
        if operation == "get_object_lock_configuration":
            stubber.add_client_error(
                operation, service_error_code="ObjectLockConfigurationNotFoundError"
            )
        elif operation == "get_bucket_versioning":
            stubber.add_response(operation, {})
        else:
            stubber.add_response(operation, {"IsTruncated": False})
    return stubber


@pytest.mark.parametrize("operation", list(_PERMISSIONS))
async def test_a_missing_permission_is_named(
    store: S3ObjectStore, operation: str
) -> None:
    with _readiness(store, failing=operation):
        with pytest.raises(ObjectStorePermissionError) as refused:
            await store.check_ready()
    assert _PERMISSIONS[operation] in str(refused.value)


async def test_a_bucket_without_versioning_or_lock_is_ready(
    store: S3ObjectStore,
) -> None:
    """No Object Lock configuration is an answer, not an error. Mutant: the
    missing configuration refuses the store."""
    with _readiness(store):
        await store.check_ready()


async def test_a_store_that_cannot_answer_is_refused(store: S3ObjectStore) -> None:
    with _readiness(store, failing="list_object_versions", code="NotImplemented"):
        with pytest.raises(ObjectStoreKeepsVersionsError):
            await store.check_ready()


async def test_a_delete_with_versions_beyond_one_page_is_unconfirmed(
    store: S3ObjectStore,
) -> None:
    """Each retried delete adds a delete marker; an old version may be on a
    later page. Mutant: only the first page is read."""
    key = new_object_key(_settings())
    stubber = Stubber(store._client)
    stubber.add_response("delete_object", {})
    stubber.add_client_error(
        "head_object", service_error_code="404", http_status_code=404
    )
    stubber.add_response(
        "list_object_versions",
        {
            "IsTruncated": True,
            "DeleteMarkers": [{"Key": key, "VersionId": "marker", "IsLatest": True}],
        },
    )
    with stubber, pytest.raises(ObjectStoreUnavailableError):
        await store.delete_and_confirm(key)


def _deleted_then_listed(store: S3ObjectStore, listing: dict[str, object]) -> Stubber:
    stubber = Stubber(store._client)
    stubber.add_response("delete_object", {})
    stubber.add_client_error(
        "head_object", service_error_code="404", http_status_code=404
    )
    stubber.add_response("list_object_versions", listing)
    return stubber


@pytest.mark.parametrize(
    "listing",
    [{}, {"IsTruncated": False, "Versions": [{"VersionId": "kept"}]}],
    ids=["no-completion-flag", "version-without-key"],
)
async def test_a_delete_with_an_unreadable_version_listing_is_unconfirmed(
    store: S3ObjectStore, listing: dict[str, object]
) -> None:
    """A listing that does not say it is complete, or a version it does not
    name, cannot show that no version is left. Mutant: only a version named
    with the key, or a page marked as cut short, keeps the delete open."""
    with (
        _deleted_then_listed(store, listing),
        pytest.raises(ObjectStoreUnavailableError),
    ):
        await store.delete_and_confirm(new_object_key(_settings()))


async def test_a_delete_with_a_complete_empty_listing_is_confirmed(
    store: S3ObjectStore,
) -> None:
    with _deleted_then_listed(store, {"IsTruncated": False}):
        await store.delete_and_confirm(new_object_key(_settings()))


def _caused(error: ObjectContentConfigurationError, cause: ObjectStoreError):
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("cause", "reported"),
    [
        (
            ObjectStorePermissionError("needs s3:GetBucketVersioning"),
            ObjectStoreProbeAuthenticationFailed,
        ),
        (
            ObjectStoreKeepsVersionsError("versioning enabled"),
            ObjectStoreProbeKeepsVersions,
        ),
    ],
    ids=["permission", "versions"],
)
@pytest.mark.parametrize("wrapped", [False, True], ids=["store", "binding"])
async def test_the_connection_test_reports_why_a_bucket_is_refused(
    cause: ObjectStoreError, reported: type[Exception], wrapped: bool
) -> None:
    """Mutant: a refused bucket is reported as bound to another installation."""
    error: Exception = (
        _caused(ObjectContentConfigurationError(str(cause)), cause)
        if wrapped
        else cause
    )
    with pytest.raises(reported):
        ObjectStoreConnectionService._raise_probe_error(error)
