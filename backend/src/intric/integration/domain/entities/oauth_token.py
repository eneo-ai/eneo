from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from typing_extensions import override

from intric.base.base_entity import Entity
from intric.integration.infrastructure.content_service.types import OAuthResource
from intric.main.exceptions import InternalServerException

if TYPE_CHECKING:
    from intric.integration.domain.entities.user_integration import UserIntegration
    from intric.integration.presentation.models import IntegrationType


class OauthToken(Entity):
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: "IntegrationType",
        user_integration: "UserIntegration",
        id: Optional[UUID] = None,
        resources: list[OAuthResource] | None = None,
        created_at: Optional["datetime"] = None,
        updated_at: Optional["datetime"] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.resources = resources or []
        self.user_integration = user_integration

    @property
    def is_confluence(self) -> bool:
        return self.token_type.is_confluence

    @property
    def is_sharepoint(self) -> bool:
        return self.token_type.is_sharepoint


class ConfluenceToken(OauthToken):
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: "IntegrationType",
        user_integration: "UserIntegration",
        id: Optional[UUID] = None,
        resources: list[OAuthResource] | None = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(
            id=id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            user_integration=user_integration,
            resources=resources,
            created_at=created_at,
            updated_at=updated_at,
        )

    @property
    def cloud_id(self) -> str:
        try:
            resource = self.resources[0]
            cloud_id = resource.get("id")
            if not cloud_id:
                raise InternalServerException()
            return cloud_id
        except IndexError:
            raise InternalServerException()

    @property
    def base_url(self) -> str:
        return f"https://api.atlassian.com/ex/confluence/{self.cloud_id}"

    @property
    def base_web_url(self) -> str:
        try:
            instance_url = self.resources[0].get("url")
            if not instance_url:
                raise InternalServerException()
            base_web_url = f"{instance_url}/wiki"
            return base_web_url
        except IndexError:
            raise InternalServerException()

    @property
    @override
    def is_confluence(self) -> bool:
        return True


class SharePointToken(OauthToken):
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: "IntegrationType",
        user_integration: "UserIntegration",
        id: Optional[UUID] = None,
        resources: list[OAuthResource] | None = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(
            id=id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            user_integration=user_integration,
            resources=resources,
            created_at=created_at,
            updated_at=updated_at,
        )

    @property
    def base_url(self) -> str:
        return "https://graph.microsoft.com"

    @property
    def base_site_id(self) -> str:
        try:
            site_id = self.resources[0].get("id")
            if not site_id:
                raise InternalServerException("graph site id not found")
            return site_id
        except IndexError:
            raise InternalServerException("graph site id not found")
