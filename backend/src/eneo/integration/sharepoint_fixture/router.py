from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.integration.infrastructure.preview_service.sharepoint_search import (
    parse_filter_params,
)
from eneo.integration.sharepoint_fixture.models import (
    SharePointFixturePreviewResponse,
    SharePointFixtureScenario,
    SharePointFixtureSearchResponse,
    SharePointFixtureTreeResponse,
)
from eneo.integration.sharepoint_fixture.service import SharePointFixtureService
from eneo.main.config import Settings, get_settings
from eneo.main.exceptions import NotFoundException
from eneo.server.protocol import responses

_fixture_service = SharePointFixtureService()


def require_sharepoint_fixture_mode(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Hide the fixture API unless both explicit safety guards pass."""
    if not settings.sharepoint_fixture_mode_active:
        raise NotFoundException()


router = APIRouter(dependencies=[Depends(require_sharepoint_fixture_mode)])


@router.get(
    "/{scenario}/preview/",
    response_model=SharePointFixturePreviewResponse,
    description=(
        "Return development-only SharePoint preview fixtures. No Microsoft "
        "Graph request is made. Requires SHAREPOINT_FIXTURE_MODE_ENABLED=true."
    ),
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Synthetic fixtures only; require_sharepoint_fixture_mode hides these outside explicitly enabled development mode.",
)
async def get_sharepoint_fixture_preview(
    scenario: SharePointFixtureScenario,
) -> SharePointFixturePreviewResponse:
    return _fixture_service.get_preview(scenario)


@router.get(
    "/{scenario}/tree/",
    response_model=SharePointFixtureTreeResponse,
    description=(
        "Return a development-only SharePoint folder fixture. No Microsoft "
        "Graph request is made. Requires SHAREPOINT_FIXTURE_MODE_ENABLED=true."
    ),
    responses=responses.get_responses([400, 404]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Synthetic fixtures only; require_sharepoint_fixture_mode hides these outside explicitly enabled development mode.",
)
async def get_sharepoint_fixture_tree(
    scenario: SharePointFixtureScenario,
    site_id: Annotated[Optional[str], Query()] = None,
    drive_id: Annotated[Optional[str], Query()] = None,
    folder_id: Annotated[Optional[str], Query()] = None,
    folder_path: Annotated[str, Query()] = "",
) -> SharePointFixtureTreeResponse:
    return _fixture_service.get_tree(
        scenario,
        site_id=site_id,
        drive_id=drive_id,
        folder_id=folder_id,
        folder_path=folder_path,
    )


@router.get(
    "/{scenario}/search/",
    response_model=SharePointFixtureSearchResponse,
    description=(
        "Search a development-only SharePoint fixture by text and column values. "
        "No Microsoft Graph request is made. Requires SHAREPOINT_FIXTURE_MODE_ENABLED=true."
    ),
    responses=responses.get_responses([400, 404]),
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Synthetic fixtures only; require_sharepoint_fixture_mode hides these outside explicitly enabled development mode.",
)
async def search_sharepoint_fixture(
    scenario: SharePointFixtureScenario,
    site_id: Annotated[Optional[str], Query()] = None,
    drive_id: Annotated[Optional[str], Query()] = None,
    q: Annotated[str, Query()] = "",
    filter: Annotated[list[str], Query()] = [],
) -> SharePointFixtureSearchResponse:
    return _fixture_service.get_search(
        scenario,
        site_id=site_id,
        drive_id=drive_id,
        text=q,
        filters=parse_filter_params(filter),
    )
