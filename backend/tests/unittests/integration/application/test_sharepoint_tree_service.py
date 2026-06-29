from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.integration.application.sharepoint_tree_service import (
    SharePointTreeService,
)
from intric.main.exceptions import BadRequestException, NotFoundException


@pytest.fixture
def service():
    return SharePointTreeService(
        user_integration_repo=AsyncMock(),
        sharepoint_auth_router=AsyncMock(),
        space_repo=AsyncMock(),
    )


class TestGetFolderTreeTypedExceptions:
    async def test_missing_site_and_drive_raises_bad_request(self, service):
        with pytest.raises(BadRequestException):
            await service.get_folder_tree(
                user_integration_id=uuid4(),
                space_id=uuid4(),
                site_id=None,
                drive_id=None,
            )

    async def test_missing_user_integration_raises_not_found(self, service):
        service.user_integration_repo.one.side_effect = Exception("gone")

        with pytest.raises(NotFoundException):
            await service.get_folder_tree(
                user_integration_id=uuid4(),
                space_id=uuid4(),
                site_id="site-1",
            )

    async def test_unauthenticated_integration_raises_bad_request(self, service):
        integration = MagicMock()
        integration.authenticated = False
        service.user_integration_repo.one.return_value = integration

        with pytest.raises(BadRequestException):
            await service.get_folder_tree(
                user_integration_id=uuid4(),
                space_id=uuid4(),
                site_id="site-1",
            )

    async def test_missing_space_raises_not_found(self, service):
        integration = MagicMock()
        integration.authenticated = True
        service.user_integration_repo.one.return_value = integration
        service.space_repo.one.side_effect = Exception("no space")

        with pytest.raises(NotFoundException):
            await service.get_folder_tree(
                user_integration_id=uuid4(),
                space_id=uuid4(),
                site_id="site-1",
            )
