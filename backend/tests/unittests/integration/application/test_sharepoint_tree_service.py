from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.application.sharepoint_tree_service import (
    SharePointTreeService,
)
from eneo.main.exceptions import BadRequestException, NotFoundException


@pytest.fixture
def service():
    return SharePointTreeService(
        user_integration_service=AsyncMock(),
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
        service.user_integration_service.get_authorized_integration.side_effect = (
            NotFoundException("gone")
        )

        with pytest.raises(NotFoundException):
            await service.get_folder_tree(
                user_integration_id=uuid4(),
                space_id=uuid4(),
                site_id="site-1",
            )

    async def test_unauthenticated_integration_raises_bad_request(self, service):
        integration = MagicMock()
        service.user_integration_service.get_authorized_integration.side_effect = (
            BadRequestException("not authenticated")
        )
        service.user_integration_service.get_authorized_integration.return_value.integration = integration

        with pytest.raises(BadRequestException):
            await service.get_folder_tree(
                user_integration_id=uuid4(),
                space_id=uuid4(),
                site_id="site-1",
            )

    async def test_missing_space_raises_not_found(self, service):
        integration = MagicMock()
        integration.authenticated = True
        service.user_integration_service.get_authorized_integration.return_value.integration = integration
        service.space_repo.one.side_effect = NotFoundException("no space")

        with pytest.raises(NotFoundException):
            await service.get_folder_tree(
                user_integration_id=uuid4(),
                space_id=uuid4(),
                site_id="site-1",
            )


class TestSearchLibrary:
    async def test_missing_site_and_drive_raises_before_any_authorization(
        self, service
    ):
        with pytest.raises(BadRequestException):
            await service.search_library(
                user_integration_id=uuid4(), space_id=uuid4(), text="larm"
            )
        service.space_repo.one.assert_not_awaited()
        service.user_integration_service.get_authorized_integration.assert_not_awaited()

    async def test_delegates_to_the_library_search_with_the_connection_token(
        self, service, monkeypatch
    ):
        token = MagicMock()
        callback = AsyncMock()
        service._connect = AsyncMock(return_value=(token, callback))
        infra = MagicMock()
        infra.search_library = AsyncMock(return_value={"items": [], "truncated": False})
        monkeypatch.setattr(
            "eneo.integration.infrastructure.preview_service.sharepoint_tree_service."
            "SharePointTreeService",
            MagicMock(return_value=infra),
        )

        result = await service.search_library(
            user_integration_id=uuid4(),
            space_id=uuid4(),
            site_id="s1",
            text="larm",
            filters={"Dokumenttyp": "Rutin"},
        )

        assert result == {"items": [], "truncated": False}
        infra.search_library.assert_awaited_once_with(
            token=token,
            site_id="s1",
            drive_id=None,
            text="larm",
            filters={"Dokumenttyp": "Rutin"},
        )

    async def test_a_failing_search_surfaces_as_a_bad_request(
        self, service, monkeypatch
    ):
        service._connect = AsyncMock(return_value=(MagicMock(), AsyncMock()))
        infra = MagicMock()
        infra.search_library = AsyncMock(
            side_effect=ValueError("Unknown filter column: X")
        )
        monkeypatch.setattr(
            "eneo.integration.infrastructure.preview_service.sharepoint_tree_service."
            "SharePointTreeService",
            MagicMock(return_value=infra),
        )

        with pytest.raises(BadRequestException, match="Unknown filter column: X"):
            await service.search_library(
                user_integration_id=uuid4(), space_id=uuid4(), site_id="s1", text="x"
            )
