from eneo.users.user import UserInDB
from eneo.whats_new.whats_new_models import WhatsNewSeenPublic
from eneo.whats_new.whats_new_repo import WhatsNewRepository


class WhatsNewService:
    def __init__(self, user: UserInDB, repo: WhatsNewRepository) -> None:
        super().__init__()
        self.user = user
        self.repo = repo

    async def get_seen(self) -> WhatsNewSeenPublic:
        return await self.repo.get_seen(self.user.id)

    async def mark_seen(self, version: str) -> WhatsNewSeenPublic:
        return await self.repo.mark_seen(self.user.id, version)
