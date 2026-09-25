from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.exceptions import QuotaExceededException
from eneo.users.user import UserInDB


def ensure_quota_capacity(
    *,
    tenant_usage: int,
    tenant_limit: int,
    user_usage: int,
    user_limit: int | None,
    size_in_bytes: int,
) -> None:
    if tenant_usage + size_in_bytes > tenant_limit:
        raise QuotaExceededException("Tenant quota limit exceeded.")
    if user_limit is not None and user_usage + size_in_bytes > user_limit:
        raise QuotaExceededException("User quota limit exceeded.")


class QuotaService:
    def __init__(self, user: UserInDB, info_blob_repo: InfoBlobRepository):
        super().__init__()
        self.user = user
        self.info_blob_repo = info_blob_repo

    def _size_of_text(self, text: str) -> int:
        return len(text.encode("utf-8"))

    async def ensure_capacity(self, size_in_bytes: int) -> None:
        tenant_usage = await self.info_blob_repo.get_retained_size_of_tenant(
            self.user.tenant.id
        )
        user_usage = (
            await self.info_blob_repo.get_retained_size_of_user(self.user.id)
            if self.user.quota_limit is not None
            else 0
        )
        ensure_quota_capacity(
            tenant_usage=tenant_usage,
            tenant_limit=self.user.tenant.quota_limit,
            user_usage=user_usage,
            user_limit=self.user.quota_limit,
            size_in_bytes=size_in_bytes,
        )

    async def add_text(self, text_to_add: str) -> int:
        size_of_text = self._size_of_text(text_to_add)
        await self.ensure_capacity(size_of_text)
        return size_of_text
