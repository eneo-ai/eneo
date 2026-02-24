from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from intric.websites.presentation.website_router import create_website, get_websites


@pytest.mark.asyncio
async def test_get_websites_deprecated_endpoint_raises_410():
    with pytest.raises(HTTPException) as exc_info:
        await get_websites(for_tenant=False, container=MagicMock())

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == "This endpoint is deprecated"


@pytest.mark.asyncio
async def test_create_website_deprecated_endpoint_raises_410():
    with pytest.raises(HTTPException) as exc_info:
        await create_website(crawl=MagicMock(), container=MagicMock())

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == "This endpoint is deprecated"
