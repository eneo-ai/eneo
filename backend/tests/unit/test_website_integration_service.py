from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.integration.application.website_integration_service import (
    SitemapPage,
    WebsiteIntegrationService,
)
from intric.integration.presentation.models import (
    WebsiteIntegrationConfigCreate,
    WebsiteIntegrationHeader,
    WebsiteIntegrationMarkdownMethod,
    WebsiteIntegrationMarkdownUrlLocation,
)
from intric.main.exceptions import BadRequestException


def _make_service() -> WebsiteIntegrationService:
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[],
    )
    return WebsiteIntegrationService(
        session=AsyncMock(),
        user=user,
        space_service=AsyncMock(),
        job_service=AsyncMock(),
        website_crud_service=AsyncMock(),
        text_processor=AsyncMock(),
        datastore=AsyncMock(),
        info_blob_repo=AsyncMock(),
        aiohttp_session=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_create_config_requires_non_blank_name():
    service = _make_service()
    service._get_or_create_website_tenant_integration = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(id=uuid4())
    )
    service._resolve_owner = AsyncMock(return_value=(uuid4(), service.user.id))  # type: ignore[method-assign]

    with pytest.raises(BadRequestException, match="name is required"):
        await service.create_config(
            owner_type="user",
            payload=WebsiteIntegrationConfigCreate(
                name="   ",
                sitemap_url="https://example.com/sitemap.xml",
                headers=[],
            ),
        )


@pytest.mark.asyncio
async def test_create_config_requires_non_blank_sitemap_url():
    service = _make_service()
    service._get_or_create_website_tenant_integration = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(id=uuid4())
    )
    service._resolve_owner = AsyncMock(return_value=(uuid4(), service.user.id))  # type: ignore[method-assign]

    with pytest.raises(BadRequestException, match="Sitemap URL is required"):
        await service.create_config(
            owner_type="user",
            payload=WebsiteIntegrationConfigCreate(
                name="Marketing",
                sitemap_url="   ",
                headers=[],
            ),
        )


def test_headers_to_dict_strips_keys_and_ignores_blank_entries():
    result = WebsiteIntegrationService._headers_to_dict(
        [
            WebsiteIntegrationHeader(key=" Authorization ", value=" Bearer token "),
            WebsiteIntegrationHeader(key=" ", value="ignored"),
            WebsiteIntegrationHeader(key="api-key", value=" secret "),
        ]
    )

    assert result == {
        "Authorization": "Bearer token",
        "api-key": "secret",
    }


def test_parse_lastmod_supports_zulu_timestamps():
    parsed = WebsiteIntegrationService._parse_lastmod("2026-06-04T12:30:00Z")

    assert parsed == datetime(2026, 6, 4, 12, 30, tzinfo=timezone.utc)


def test_page_needs_sync_uses_lastmod_when_available():
    existing = SimpleNamespace(
        last_synced_at=datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc),
        sitemap_lastmod=datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc),
    )

    assert (
        WebsiteIntegrationService._page_needs_sync(
            existing,
            SitemapPage(
                url="https://example.com/a",
                lastmod=datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc),
            ),
        )
        is True
    )
    assert (
        WebsiteIntegrationService._page_needs_sync(
            existing,
            SitemapPage(
                url="https://example.com/a",
                lastmod=datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc),
            ),
        )
        is False
    )


def test_build_page_content_webhook_config_defaults_when_endpoint_missing():
    config = WebsiteIntegrationService._build_page_content_webhook_config(
        page_content_webhook_url=None,
        page_content_webhook_method=WebsiteIntegrationMarkdownMethod.POST,
        page_content_webhook_url_location=WebsiteIntegrationMarkdownUrlLocation.BODY,
        page_content_webhook_url_param_name="target",
    )

    assert config.endpoint_url is None
    assert config.method == WebsiteIntegrationMarkdownMethod.GET
    assert config.url_location == WebsiteIntegrationMarkdownUrlLocation.QUERY
    assert config.param_name == "url"


def test_build_page_content_webhook_config_rejects_get_with_body():
    with pytest.raises(BadRequestException, match="GET requests must send the URL"):
        WebsiteIntegrationService._build_page_content_webhook_config(
            page_content_webhook_url="https://example.com/markdown",
            page_content_webhook_method=WebsiteIntegrationMarkdownMethod.GET,
            page_content_webhook_url_location=WebsiteIntegrationMarkdownUrlLocation.BODY,
            page_content_webhook_url_param_name="url",
        )


def test_build_page_content_webhook_config_requires_param_name_when_endpoint_is_set():
    with pytest.raises(BadRequestException, match="parameter name is required"):
        WebsiteIntegrationService._build_page_content_webhook_config(
            page_content_webhook_url="https://example.com/markdown",
            page_content_webhook_method=WebsiteIntegrationMarkdownMethod.POST,
            page_content_webhook_url_location=WebsiteIntegrationMarkdownUrlLocation.BODY,
            page_content_webhook_url_param_name=" ",
        )


def test_extract_markdown_response_supports_raw_markdown():
    result = WebsiteIntegrationService._extract_markdown_response("# Hello\n\nBody")

    assert result == "# Hello\n\nBody"


def test_extract_markdown_response_supports_json_markdown_key():
    result = WebsiteIntegrationService._extract_markdown_response(
        '{"markdown":"# Hello"}'
    )

    assert result == "# Hello"


def test_extract_markdown_response_supports_json_content_key():
    result = WebsiteIntegrationService._extract_markdown_response(
        '{"content":"# Hello"}'
    )

    assert result == "# Hello"


def test_extract_markdown_response_supports_json_data_key():
    result = WebsiteIntegrationService._extract_markdown_response('{"data":"# Hello"}')

    assert result == "# Hello"


def test_extract_markdown_response_rejects_json_without_supported_keys():
    with pytest.raises(BadRequestException, match="must include one of"):
        WebsiteIntegrationService._extract_markdown_response('{"message":"hello"}')


def test_append_query_param_url_encodes_rendered_url():
    result = WebsiteIntegrationService._append_query_param(
        base_url="https://example.com/render-markdown",
        key="url",
        value="https://foo.example/path?a=1&b=two words",
    )

    assert (
        result
        == "https://example.com/render-markdown?url=https%3A%2F%2Ffoo.example%2Fpath%3Fa%3D1%26b%3Dtwo%20words"
    )


@pytest.mark.asyncio
async def test_create_config_auto_creates_tenant_integration_when_missing():
    service = _make_service()
    owner_space_id = uuid4()
    integration_id = uuid4()

    execute_result = AsyncMock()
    execute_result.scalars.return_value.first.side_effect = [
        None,
        SimpleNamespace(id=integration_id),
    ]
    service.session.execute.return_value = execute_result
    service._resolve_owner = AsyncMock(return_value=(owner_space_id, service.user.id))  # type: ignore[method-assign]

    await service.create_config(
        owner_type="user",
        payload=WebsiteIntegrationConfigCreate(
            name="Marketing",
            sitemap_url="https://example.com/sitemap.xml",
            headers=[],
        ),
    )

    added_objects = [call.args[0] for call in service.session.add.call_args_list]
    assert any(
        getattr(item, "integration_id", None) == integration_id
        and getattr(item, "tenant_id", None) == service.user.tenant_id
        for item in added_objects
    )


@pytest.mark.asyncio
async def test_create_or_reuse_website_reuses_accessible_existing_source():
    service = _make_service()
    space_id = uuid4()
    website_id = uuid4()
    existing_config = SimpleNamespace(
        id=uuid4(),
        website_id=website_id,
        sync_status="complete",
        sitemap_url="https://example.com/sitemap.xml",
        markdown_endpoint_url=None,
        markdown_endpoint_method="get",
        markdown_endpoint_url_location="query",
        markdown_endpoint_url_param_name="url",
        headers={},
        ping_token="token",
        last_sitemap_fetched_at=None,
        last_successful_sync_at=None,
        last_sync_error=None,
        last_sync_queued_at=None,
    )
    existing_website = SimpleNamespace(id=website_id, name="Existing source")

    service._find_accessible_config_for_space = AsyncMock(  # type: ignore[method-assign]
        return_value=existing_config
    )
    service.website_crud_service.get_website.return_value = existing_website

    website = await service.create_or_reuse_sitemap_webhook_integration(
        space_id=space_id,
        name="Marketing",
        url=None,
        embedding_model_id=uuid4(),
        sitemap_url="https://example.com/sitemap.xml",
        page_content_webhook_url=None,
        page_content_webhook_method=WebsiteIntegrationMarkdownMethod.GET,
        page_content_webhook_url_location=WebsiteIntegrationMarkdownUrlLocation.QUERY,
        page_content_webhook_url_param_name="url",
        headers=[],
    )

    assert website is existing_website
    assert website.website_integration_config is existing_config
    assert website.reused_existing is True
    service.website_crud_service.create_website.assert_not_called()


@pytest.mark.asyncio
async def test_create_or_reuse_sitemap_webhook_integration_creates_new_source_and_queues_initial_sync():
    service = _make_service()
    space_id = uuid4()
    website_id = uuid4()
    integration_id = uuid4()
    created_website = SimpleNamespace(
        id=website_id,
        name="Marketing source",
        website_integration_config=None,
        reused_existing=None,
    )

    service._find_accessible_config_for_space = AsyncMock(  # type: ignore[method-assign]
        return_value=None
    )
    service._get_or_create_website_tenant_integration = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(id=integration_id)
    )
    service.website_crud_service.create_website.return_value = created_website
    service.queue_sync = AsyncMock()  # type: ignore[method-assign]

    website = await service.create_or_reuse_sitemap_webhook_integration(
        space_id=space_id,
        name="Marketing",
        url=None,
        embedding_model_id=uuid4(),
        sitemap_url="https://example.com/sitemap.xml",
        page_content_webhook_url="https://example.com/markdown",
        page_content_webhook_method=WebsiteIntegrationMarkdownMethod.POST,
        page_content_webhook_url_location=WebsiteIntegrationMarkdownUrlLocation.BODY,
        page_content_webhook_url_param_name="target",
        headers=[WebsiteIntegrationHeader(key="Authorization", value="Bearer token")],
    )

    service.website_crud_service.create_website.assert_awaited_once()
    service.queue_sync.assert_awaited_once()
    assert website is created_website
    assert website.website_integration_config is not None
    assert website.website_integration_config.website_id == website_id
    assert website.website_integration_config.owner_type == "space"
    assert website.website_integration_config.owner_space_id == space_id
    assert (
        website.website_integration_config.sitemap_url
        == "https://example.com/sitemap.xml"
    )
    assert website.website_integration_config.markdown_endpoint_method == "post"
    assert website.website_integration_config.markdown_endpoint_url_location == "body"
    assert (
        website.website_integration_config.markdown_endpoint_url_param_name == "target"
    )
    assert website.website_integration_config.headers == {
        "Authorization": "Bearer token"
    }
    assert website.reused_existing is False
