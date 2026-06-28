from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List
from uuid import UUID

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.domain.entities.oauth_token import OauthToken

if TYPE_CHECKING:
    from eneo.integration.infrastructure.oauth_token_service import OauthTokenService


class BasePreviewService(ABC):
    def __init__(self, oauth_token_service: "OauthTokenService") -> None:
        super().__init__()
        self.oauth_token_service = oauth_token_service

    @abstractmethod
    async def get_preview_info(
        self,
        token: OauthToken,
    ) -> List[IntegrationPreview]:
        pass

    async def token_refresh_callback(self, token_id: UUID) -> dict[str, str]:
        token = await self.oauth_token_service.refresh_and_update_token(
            token_id=token_id
        )
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
        }
