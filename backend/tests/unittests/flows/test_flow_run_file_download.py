from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileInfo, FileMetadata, FileType
from eneo.flows.application.flow_run_file_download import (
    log_run_file_download_minted,
)
from eneo.users.user import UserInDB


def _user() -> UserInDB:
    return cast(
        UserInDB,
        SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            username="Run Owner",
            email="owner@example.org",
            active_api_key=None,
        ),
    )


def _file(tenant_id: UUID) -> FileMetadata:
    now = datetime.now(timezone.utc)
    return FileMetadata(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="protokoll.docx",
        file_type=FileType.TEXT,
        tenant_id=tenant_id,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
    )


def _file_repo(file: FileMetadata, size: int) -> SimpleNamespace:
    info = FileInfo.model_validate(
        {**file.model_dump(), "size": size, "checksum": "0" * 64}
    )
    return SimpleNamespace(
        get_infos_by_ids=AsyncMock(
            side_effect=lambda ids: [info] if ids == [file.id] else []
        )
    )


@pytest.mark.asyncio
async def test_a_request_user_gets_a_required_row_with_its_own_snapshot() -> None:
    user = _user()
    file = _file(user.tenant_id)
    audit_service = SimpleNamespace(log=AsyncMock())
    extra = {"flow_id": "f", "download_purpose": "flow_run_artifact"}

    await log_run_file_download_minted(
        audit_service=audit_service,
        file_repo=_file_repo(file, 512),
        file=file,
        actor=user,
        description="Minted a download URL",
        extra=extra,
    )

    audit_service.log.assert_awaited_once_with(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.FILE_SIGNED_URL_MINTED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description="Minted a download URL",
        metadata=AuditMetadata.standard(
            actor=user, target=file, extra={**extra, "size_bytes": 512}
        ),
        required=True,
    )


@pytest.mark.asyncio
async def test_an_audit_failure_reaches_the_caller() -> None:
    user = _user()
    file = _file(user.tenant_id)
    audit_service = SimpleNamespace(
        log=AsyncMock(side_effect=RuntimeError("audit store unavailable"))
    )

    with pytest.raises(RuntimeError, match="audit store unavailable"):
        await log_run_file_download_minted(
            audit_service=audit_service,
            file_repo=_file_repo(file, 1),
            file=file,
            actor=user,
            description="Minted a download URL",
            extra={"download_purpose": "flow_run_artifact"},
        )
