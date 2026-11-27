"""File persistence keeps its read-back inside the write transaction, and the
original-download selection serves what ``original_available`` promises."""

from contextlib import asynccontextmanager
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.files import file_service as module
from eneo.files.file_models import FileContentVariant, FileOwner, FileType
from eneo.files.file_repo import FileContentReferenceRecord
from eneo.files.file_service import FileOriginalNotFoundError, FileService
from eneo.main.exceptions import UnauthorizedException
from eneo.object_content.content import ContentAccessClass, StorageKind
from tests.fixtures import TEST_USER


def _service_with_explicit_transactions() -> tuple[FileService, dict[str, bool]]:
    """A service on a session with autobegin off, as outside a request scope."""
    state = {"in_transaction": False}
    session = MagicMock()
    session.in_transaction.side_effect = lambda: state["in_transaction"]

    @asynccontextmanager
    async def begin():
        state["in_transaction"] = True
        try:
            yield
        finally:
            state["in_transaction"] = False

    session.begin = begin
    service = FileService.__new__(FileService)
    service.user = SimpleNamespace(id=uuid4())
    service.repo = SimpleNamespace(session=session)
    return service, state


async def test_generated_image_is_read_back_inside_the_write_transaction(monkeypatch):
    service, state = _service_with_explicit_transactions()
    file_id = uuid4()
    seen: list[bool] = []

    async def get_file_by_id(requested):
        seen.append(state["in_transaction"])
        assert requested == file_id
        return SimpleNamespace(
            file_type=FileType.IMAGE, model_dump=lambda: {"id": file_id}
        )

    async def get_content_references(file_ids):
        seen.append(state["in_transaction"])
        assert file_ids == [file_id]
        return [_reference("generated_artifact")]

    service.repo.get_content_references = get_content_references
    service._object_content = SimpleNamespace(object_store_configured=False)

    monkeypatch.setattr(
        service, "_persist_prepared_file", AsyncMock(return_value=file_id)
    )
    monkeypatch.setattr(service, "get_file_by_id", get_file_by_id)
    monkeypatch.setattr(module, "File", lambda **fields: SimpleNamespace(**fields))

    saved = await service.save_image_from_bytes(
        b"img", name="a.png", mimetype="image/png"
    )

    assert seen == [True, True]
    assert saved.id == file_id and saved.blob == b"img"
    # The stored artifact is the image's original, so the file can be handed
    # to another tool by reference in the same answer.
    assert saved.original_available is True
    assert state["in_transaction"] is False


@pytest.mark.parametrize(
    ("file_type", "stored", "available"),
    [
        (FileType.TEXT, ["original", "extracted_text"], True),
        (FileType.TEXT, ["extracted_text"], False),
    ],
)
async def test_generated_document_advertises_its_stored_original(
    monkeypatch, file_type, stored, available
):
    service, _ = _service_with_explicit_transactions()
    file_id = uuid4()
    monkeypatch.setattr(
        service,
        "get_file_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                file_type=file_type, model_dump=lambda: {"id": file_id}
            )
        ),
    )
    service.repo.get_content_references = AsyncMock(
        return_value=[_reference(variant) for variant in stored]
    )
    service._object_content = SimpleNamespace(object_store_configured=False)
    monkeypatch.setattr(module, "File", lambda **fields: SimpleNamespace(**fields))

    saved = await service._generated_file(file_id, b"csv")

    assert saved.original_available is available


def _reference(variant):
    return FileContentReferenceRecord(
        file_id=uuid4(),
        content_id=uuid4(),
        variant=FileContentVariant(variant),
        ordinal=0,
        page_number=None,
        width=None,
        height=None,
        duration_ms=None,
        sha256=sha256(b"x").digest(),
        size_bytes=1,
        media_type="image/png",
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        storage_kind=StorageKind.POSTGRES_INLINE,
    )


class TestOriginalContent:
    """The original-download route serves what ``original_available`` promises."""

    def test_generated_artifact_is_an_image_original(self):
        artifact = _reference("generated_artifact")
        assert FileService._original_content([artifact], [], FileType.IMAGE) is artifact

    def test_stored_original_wins_over_the_artifact(self):
        original, artifact = _reference("original"), _reference("generated_artifact")
        assert (
            FileService._original_content([artifact, original], [], FileType.IMAGE)
            is original
        )

    def test_text_file_without_original_is_not_served(self):
        with pytest.raises(FileOriginalNotFoundError):
            FileService._original_content(
                [_reference("extracted_text")], [], FileType.TEXT
            )


def _text_metadata():
    from datetime import UTC, datetime

    from eneo.files.file_models import FileMetadata

    now = datetime.now(UTC)
    return FileMetadata(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="report.pdf",
        mimetype="application/pdf",
        file_type=FileType.TEXT,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
        parent_file_id=None,
    )


def _original_reference(metadata, storage_kind):
    return FileContentReferenceRecord(
        file_id=metadata.id,
        content_id=uuid4(),
        variant=FileContentVariant.ORIGINAL,
        ordinal=0,
        page_number=None,
        width=None,
        height=None,
        duration_ms=None,
        sha256=sha256(b"%PDF").digest(),
        size_bytes=4,
        media_type="application/pdf",
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        storage_kind=storage_kind,
    )


async def _project(metadata, references, *, object_store_configured):
    repository = AsyncMock()
    repository.get_content_references.return_value = list(references)
    repository.get_legacy_infos.return_value = []
    repository.get_legacy_content.return_value = []
    object_content = AsyncMock()
    object_content.object_store_configured = object_store_configured
    object_content.read_content_bytes.return_value = {}
    service = FileService(
        user=None,
        repo=repository,
        protocol=AsyncMock(),
        object_content=object_content,
    )
    return (await service._project_public_files([metadata]))[0]


@pytest.mark.parametrize(
    ("storage_kind", "object_store_configured", "expected"),
    [
        (StorageKind.POSTGRES_INLINE, False, True),
        (StorageKind.POSTGRES_INLINE, True, True),
        (StorageKind.OBJECT_STORE, True, True),
        (StorageKind.OBJECT_STORE, False, False),
    ],
)
async def test_download_reference_follows_original_readability(
    storage_kind, object_store_configured, expected
):
    """``has_download_reference`` and the loader's ``original_available`` share
    one rule: inline originals are always servable, object-store originals
    only while a store is connected. The chat UI reads this flag to show the
    files tool, so it must never advertise bytes the deployment cannot serve."""
    metadata = _text_metadata()
    public = await _project(
        metadata,
        [_original_reference(metadata, storage_kind)],
        object_store_configured=object_store_configured,
    )
    assert public.has_download_reference is expected


async def test_generated_document_records_the_version_it_was_edited_from():
    service, _ = _service_with_explicit_transactions()
    service.user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    service.repo.add_metadata = AsyncMock(side_effect=lambda create: create)
    captured = SimpleNamespace(
        prepared=SimpleNamespace(
            name="Plan.md", file_type=FileType.TEXT, display_media_type="text/markdown"
        )
    )
    base = uuid4()

    created = await service._add_metadata(captured, revises_file_id=base)

    assert created.revises_file_id == base
    assert created.parent_file_id is None


def _service_key(*, service_principal_id, tenant_id) -> ApiKeyV2InDB:
    return ApiKeyV2InDB(
        id=uuid4(),
        tenant_id=tenant_id,
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        service_principal_id=service_principal_id,
        key_prefix=ApiKeyType.SK.value,
        key_suffix="12345678",
        key_type=ApiKeyType.SK,
        name="Invoice reader",
        permission=ApiKeyPermission.WRITE,
        scope_type=ApiKeyScopeType.TENANT,
        state=ApiKeyState.ACTIVE,
        key_hash="hash",
        hash_version="hmac_sha256",
    )


def _service_for(user) -> FileService:
    service = FileService.__new__(FileService)
    service.user = user
    return service


def _service_key_user(key: ApiKeyV2InDB):
    """The synthetic user a service key signs in as: its id is the key's id."""
    user = TEST_USER.model_copy(update={"id": key.id})
    user.active_api_key = key
    return user


def test_a_person_owns_the_files_of_their_own_request():
    user = TEST_USER.model_copy()

    owner = _service_for(user)._owner()

    assert owner == FileOwner(
        tenant_id=user.tenant_id,
        owner_type=PrincipalType.USER,
        owner_user_id=user.id,
    )


def test_a_service_key_owns_files_through_its_service_principal():
    principal_id = uuid4()
    key = _service_key(service_principal_id=principal_id, tenant_id=TEST_USER.tenant_id)

    owner = _service_for(_service_key_user(key))._owner()

    assert owner == FileOwner(
        tenant_id=TEST_USER.tenant_id,
        owner_type=PrincipalType.SERVICE_KEY,
        owner_service_id=principal_id,
    )


def test_a_rotated_service_key_is_the_same_owner_as_the_key_it_replaced():
    principal_id = uuid4()
    old_key = _service_key(
        service_principal_id=principal_id, tenant_id=TEST_USER.tenant_id
    )
    new_key = _service_key(
        service_principal_id=principal_id, tenant_id=TEST_USER.tenant_id
    )

    old_owner = _service_for(_service_key_user(old_key))._owner()
    new_owner = _service_for(_service_key_user(new_key))._owner()

    assert old_key.id != new_key.id
    assert old_owner == new_owner


def test_a_service_key_without_a_principal_owns_nothing():
    key = _service_key(service_principal_id=None, tenant_id=TEST_USER.tenant_id)

    with pytest.raises(UnauthorizedException):
        _service_for(_service_key_user(key))._owner()


def test_a_file_belongs_to_one_owner_only():
    tenant_id, user_id, principal_id = uuid4(), uuid4(), uuid4()
    person = FileOwner(
        tenant_id=tenant_id, owner_type=PrincipalType.USER, owner_user_id=user_id
    )
    service = FileOwner(
        tenant_id=tenant_id,
        owner_type=PrincipalType.SERVICE_KEY,
        owner_service_id=principal_id,
    )
    persons_file = SimpleNamespace(
        tenant_id=tenant_id,
        owner_type=PrincipalType.USER,
        owner_user_id=user_id,
        owner_service_id=None,
    )
    services_file = SimpleNamespace(
        tenant_id=tenant_id,
        owner_type=PrincipalType.SERVICE_KEY,
        owner_user_id=None,
        owner_service_id=principal_id,
    )
    other_tenants_file = SimpleNamespace(
        tenant_id=uuid4(),
        owner_type=PrincipalType.USER,
        owner_user_id=user_id,
        owner_service_id=None,
    )

    assert person.matches(persons_file)
    assert not person.matches(services_file)
    assert not person.matches(other_tenants_file)
    assert service.matches(services_file)
    assert not service.matches(persons_file)


@pytest.mark.parametrize(
    "fields",
    [
        {"owner_type": PrincipalType.USER},
        {"owner_type": PrincipalType.SERVICE_KEY},
        {"owner_type": PrincipalType.USER, "owner_service_id": uuid4()},
        {"owner_type": PrincipalType.SERVICE_KEY, "owner_user_id": uuid4()},
        {
            "owner_type": PrincipalType.USER,
            "owner_user_id": uuid4(),
            "owner_service_id": uuid4(),
        },
    ],
    ids=[
        "person without an id",
        "service without an id",
        "person named by a service id",
        "service named by a user id",
        "both ids",
    ],
)
def test_an_owner_must_name_exactly_the_id_of_its_own_type(fields):
    with pytest.raises(ValueError):
        FileOwner(tenant_id=uuid4(), **fields)
