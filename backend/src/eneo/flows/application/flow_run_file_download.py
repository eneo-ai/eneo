"""The required record of a download link minted for a file of a Flow run.

Every link to a run's file that a caller asks for gets one
``FILE_SIGNED_URL_MINTED`` row with ``required=True``. The caller
has already checked the file: that the run is visible to it and that the file
belongs to the run, is in its tenant and still has content. The row is written
in the caller's transaction, and the caller builds the link with
``build_signed_download_response`` only after that transaction has committed,
so no link exists without its committed row. The link and its token never go
into the row."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.files.file_models import FileMetadata
    from eneo.files.file_repo import FileRepository
    from eneo.users.user import UserInDB


async def log_run_file_download_minted(
    *,
    audit_service: AuditService,
    file_repo: FileRepository,
    file: FileMetadata,
    actor: UserInDB,
    description: str,
    extra: Mapping[str, object],
) -> None:
    """Write the required row for the requesting user; a failure propagates
    so no link is built."""
    (file_info,) = await file_repo.get_infos_by_ids([file.id])
    row_extra: dict[str, object] = {**extra, "size_bytes": file_info.size}
    await audit_service.log(
        tenant_id=actor.tenant_id,
        user=actor,
        action=ActionType.FILE_SIGNED_URL_MINTED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description=description,
        metadata=AuditMetadata.standard(actor=actor, target=file, extra=row_extra),
        required=True,
    )
