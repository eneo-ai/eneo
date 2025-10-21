from intric.info_blobs.info_blob_repo import InfoBlobRepository
from intric.main.exceptions import QuotaExceededException
from intric.users.user import UserInDB


class QuotaService:
    def __init__(self, user: UserInDB, info_blob_repo: InfoBlobRepository):
        self.user = user
        self.info_blob_repo = info_blob_repo

    def _size_of_text(self, text: str):
        return len(text.encode("utf-8"))

    async def ensure_capacity(self, size_in_bytes: int):
        tenant_limit = self.user.tenant.quota_limit
        if tenant_limit is not None:
            tenant_usage = await self.info_blob_repo.get_total_size_of_tenant(
                self.user.tenant.id
            )
            if tenant_usage + size_in_bytes > tenant_limit:
                raise QuotaExceededException("Tenant quota limit exceeded.")

        if self.user.quota_limit is not None:
            user_usage = await self.info_blob_repo.get_total_size_of_user(self.user.id)
            if user_usage + size_in_bytes > self.user.quota_limit:
                raise QuotaExceededException("User quota limit exceeded.")

    async def add_text(self, text_to_add: str):
        size_of_text = self._size_of_text(text_to_add)
        await self.ensure_capacity(size_of_text)
        return size_of_text
