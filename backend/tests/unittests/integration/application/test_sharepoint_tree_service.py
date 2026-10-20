from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import aiohttp
import pytest

from eneo.integration.application.sharepoint_tree_service import (
    SharePointTreeService,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    CREDENTIALS_INVALID_MESSAGE,
    SharePointCredentialsInvalidError,
)
from eneo.integration.infrastructure.graph_errors import NO_SITE_ACCESS_MESSAGE
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


class TestUserFacingFailures:
    async def test_refused_credentials_surface_as_the_stable_message(self, service):
        connection = MagicMock()
        connection.integration.integration_type = "sharepoint"
        service.user_integration_service.get_authorized_integration.return_value = (
            connection
        )
        service.sharepoint_auth_router.get_token_for_integration.side_effect = (
            SharePointCredentialsInvalidError("AADSTS7000215: bad secret")
        )

        with pytest.raises(BadRequestException) as exc_info:
            await service.get_folder_tree(
                user_integration_id=uuid4(), space_id=uuid4(), site_id="site-1"
            )

        assert str(exc_info.value) == CREDENTIALS_INVALID_MESSAGE
        assert "AADSTS" not in str(exc_info.value)
        # The same code an import or a sync answers with.
        assert getattr(exc_info.value, "code", None) == "sharepoint_credentials_invalid"

    @pytest.mark.parametrize(
        "status, expected",
        [
            (403, NO_SITE_ACCESS_MESSAGE),
            (401, CREDENTIALS_INVALID_MESSAGE),
            (500, "Failed to fetch SharePoint folder tree: boom"),
        ],
    )
    async def test_graph_status_maps_to_a_message_people_can_act_on(
        self, service, monkeypatch, status, expected
    ):
        service._connect = AsyncMock(return_value=(MagicMock(), AsyncMock(), None))
        graph_error = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=status, message="boom"
        )
        infra = MagicMock()

        async def failing_tree(**_):
            try:
                raise graph_error
            except aiohttp.ClientResponseError as e:
                raise ValueError("boom") from e

        infra.get_folder_tree = failing_tree
        monkeypatch.setattr(
            "eneo.integration.infrastructure.preview_service.sharepoint_tree_service."
            "SharePointTreeService",
            MagicMock(return_value=infra),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await service.get_folder_tree(
                user_integration_id=uuid4(), space_id=uuid4(), site_id="site-1"
            )

        assert str(exc_info.value) == expected
        assert getattr(exc_info.value, "code", None) == (
            "sharepoint_credentials_invalid"
            if expected == CREDENTIALS_INVALID_MESSAGE
            else None
        )

    async def test_other_failures_are_shown_without_urls_or_hosts(
        self, service, monkeypatch
    ):
        service._connect = AsyncMock(return_value=(MagicMock(), AsyncMock(), None))
        infra = MagicMock()
        infra.get_folder_tree = AsyncMock(
            side_effect=ValueError(
                "Graph call https://graph.microsoft.com/v1.0/drives/x?token=secret "
                "failed after Error 111 connecting to redis.internal:6379"
            )
        )
        monkeypatch.setattr(
            "eneo.integration.infrastructure.preview_service.sharepoint_tree_service."
            "SharePointTreeService",
            MagicMock(return_value=infra),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await service.get_folder_tree(
                user_integration_id=uuid4(), space_id=uuid4(), site_id="site-1"
            )

        message = str(exc_info.value)
        assert message.startswith("Failed to fetch SharePoint folder tree: Graph call")
        assert "secret" not in message
        assert "redis.internal" not in message

    async def test_organisation_connections_get_a_token_provider(self, service):
        connection = MagicMock()
        connection.integration.integration_type = "sharepoint"
        service.user_integration_service.get_authorized_integration.return_value = (
            connection
        )
        provider = AsyncMock()
        service.sharepoint_auth_router.access_token_provider_for = MagicMock(
            return_value=provider
        )

        _, _, access_token_provider = await service._connect(uuid4(), uuid4())

        assert access_token_provider is provider
        service.sharepoint_auth_router.access_token_provider_for.assert_called_once_with(
            connection
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
        service._connect = AsyncMock(return_value=(token, callback, None))
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
        service._connect = AsyncMock(return_value=(MagicMock(), AsyncMock(), None))
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

    @pytest.mark.parametrize("method", ["get_folder_tree", "search_library"])
    async def test_fallback_detail_never_carries_the_request_url(
        self, service, monkeypatch, method
    ):
        service._connect = AsyncMock(return_value=(MagicMock(), AsyncMock(), None))
        infra = MagicMock()
        failing = AsyncMock(
            side_effect=ValueError(
                "Download failed: https://contoso.sharepoint.com/d?tempauth=secret"
            )
        )
        infra.get_folder_tree = infra.search_library = failing
        monkeypatch.setattr(
            "eneo.integration.infrastructure.preview_service.sharepoint_tree_service."
            "SharePointTreeService",
            MagicMock(return_value=infra),
        )

        with pytest.raises(BadRequestException) as exc_info:
            await getattr(service, method)(
                user_integration_id=uuid4(), space_id=uuid4(), site_id="s1"
            )

        detail = str(exc_info.value)
        assert detail.endswith("Download failed: https://contoso.sharepoint.com/d")
        assert "tempauth" not in detail
