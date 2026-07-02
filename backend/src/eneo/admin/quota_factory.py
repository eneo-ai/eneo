from typing import Annotated

from fastapi import Depends

from eneo.admin.quota_service import QuotaService
from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.server.dependencies.get_repository import get_repository
from eneo.users.user import UserInDB


async def get_quota_service(
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    info_blob_repo: Annotated[
        InfoBlobRepository,
        Depends(get_repository(InfoBlobRepository)),
    ],
) -> QuotaService:
    return QuotaService(user, info_blob_repo=info_blob_repo)
