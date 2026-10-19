"""Knowledge selections only carry identifiers that are safe inside Graph URLs."""

import pytest
from pydantic import ValidationError

from eneo.integration.presentation.models import IntegrationKnowledgePublic
from eneo.integration.presentation.validation import https_url_or_none
from eneo.spaces.api.space_models import (
    CreateSpaceIntegrationKnowledge,
    CreateSpaceIntegrationKnowledgeBatchItem,
    CreateSpaceIntegrationKnowledgeBatchRequest,
    UpdateIntegrationKnowledgeRequest,
    UpdateIntegrationKnowledgeWrapperRequest,
)

_BASE = {"name": "Policies", "url": "https://contoso.sharepoint.com/sites/x"}


def _create(**fields):
    return CreateSpaceIntegrationKnowledge(
        embedding_model={"id": "00000000-0000-0000-0000-000000000001"},
        **_BASE,
        **fields,
    )


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"key": "contoso.sharepoint.com,8f2e-1,c5a1"}, id="site-id"),
        pytest.param(
            {"key": "b!AbCd-_12=", "resource_type": "onedrive"}, id="drive-id"
        ),
        pytest.param(
            {"folder_id": "01ABCDEF", "selected_item_type": "folder"}, id="folder"
        ),
        pytest.param({"folder_id": ".01ABC.DEF."}, id="folder-id-dots-inside"),
        pytest.param(
            {"key": "~712020:1f3a9c2e-5b7d", "selected_item_type": "personal"},
            id="confluence-personal-space",
        ),
        pytest.param(
            {"key": "DOCS", "selected_item_type": "global"}, id="confluence-space"
        ),
        pytest.param({"folder_path": "/Shared Documents/Policies (2024)/"}, id="path"),
        pytest.param({"folder_path": ""}, id="empty-path"),
        pytest.param({"selected_item_type": "site_root"}, id="site-root"),
    ],
)
def test_graph_shaped_selections_are_accepted(fields):
    assert _create(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"key": "site/../other"}, id="key-slash"),
        pytest.param({"key": "~712020:../other"}, id="personal-key-traversal"),
        pytest.param({"key": "site?$select=id"}, id="key-query"),
        pytest.param({"folder_id": "~712020:1f3a"}, id="folder-id-confluence-chars"),
        pytest.param({"key": "x" * 513}, id="key-too-long"),
        pytest.param({"folder_id": "01A?$select=id"}, id="folder-id-query"),
        pytest.param({"folder_id": "01A B"}, id="folder-id-space"),
        pytest.param({"folder_id": "."}, id="folder-id-dot"),
        pytest.param({"folder_id": ".."}, id="folder-id-dotdot"),
        pytest.param({"key": ".."}, id="key-dotdot"),
        pytest.param({"folder_path": "/a/../b"}, id="path-dotdot"),
        pytest.param({"folder_path": "/a/./b"}, id="path-dot"),
        pytest.param({"folder_path": "a/b"}, id="path-relative"),
        pytest.param({"folder_path": "/a//b"}, id="path-empty-segment"),
        pytest.param({"folder_path": "/a\x00b"}, id="path-control-char"),
        pytest.param({"folder_path": "/" + "a" * 2048}, id="path-too-long"),
        pytest.param({"selected_item_type": "Site Root"}, id="item-type-chars"),
        pytest.param({"selected_item_type": "a" * 33}, id="item-type-too-long"),
        pytest.param({"resource_type": "teams"}, id="unknown-resource-type"),
    ],
)
def test_unsafe_selections_are_rejected(fields):
    with pytest.raises(ValidationError):
        _create(**fields)


def test_batch_items_share_the_same_constraints():
    with pytest.raises(ValidationError):
        CreateSpaceIntegrationKnowledgeBatchItem(folder_path="/a/../b", **_BASE)
    assert CreateSpaceIntegrationKnowledgeBatchItem(folder_id="01ABC", **_BASE)


@pytest.mark.parametrize(
    "url",
    [
        "https://contoso.sharepoint.com/sites/x/Shared%20Documents/Policies",
        "https://contoso-my.sharepoint.com/personal/anna_contoso_se/Documents",
        "https://contoso.atlassian.net/wiki/spaces/DOCS",
        # The import dialog sends "" for an item Graph gave no web URL.
        "",
    ],
)
def test_https_links_are_accepted(url):
    created = CreateSpaceIntegrationKnowledge(
        name="Policies",
        url=url,
        embedding_model={"id": "00000000-0000-0000-0000-000000000001"},
    )
    assert created.url == url
    assert CreateSpaceIntegrationKnowledgeBatchItem(name="Policies", url=url).url == url


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("javascript:alert(document.cookie)", id="javascript"),
        pytest.param("data:text/html,<script>alert(1)</script>", id="data"),
        pytest.param("http://contoso.sharepoint.com/sites/x", id="http"),
        pytest.param("//evil.example/sites/x", id="scheme-relative"),
        pytest.param("/sites/x", id="relative"),
        pytest.param("https:///sites/x", id="no-host"),
        pytest.param("https://user:pass@evil.example/x", id="user-info"),
        pytest.param(" https://contoso.sharepoint.com/sites/x", id="leading-space"),
        pytest.param("https://contoso.sharepoint.com/a\nb", id="control-character"),
    ],
)
def test_links_that_are_not_https_are_rejected(url):
    with pytest.raises(ValidationError):
        CreateSpaceIntegrationKnowledge(
            name="Policies",
            url=url,
            embedding_model={"id": "00000000-0000-0000-0000-000000000001"},
        )
    with pytest.raises(ValidationError):
        CreateSpaceIntegrationKnowledgeBatchItem(name="Policies", url=url)


def test_the_link_stays_a_plain_string_in_the_api_schema():
    for model in (
        CreateSpaceIntegrationKnowledge,
        CreateSpaceIntegrationKnowledgeBatchItem,
    ):
        assert model.model_json_schema()["properties"]["url"] == {
            "title": "Url",
            "type": "string",
        }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(
            "https://contoso.sharepoint.com/sites/KS/Doc.pdf",
            "https://contoso.sharepoint.com/sites/KS/Doc.pdf",
            id="https",
        ),
        pytest.param(
            "HTTPS://contoso.sharepoint.com/",
            "HTTPS://contoso.sharepoint.com/",
            id="scheme-case",
        ),
        pytest.param("http://contoso.sharepoint.com/sites/KS", None, id="http"),
        pytest.param("javascript:alert(1)", None, id="javascript"),
        pytest.param("data:text/html,<script>", None, id="data"),
        pytest.param("https://user@contoso.sharepoint.com/", None, id="user-info"),
        pytest.param("https:///sites/KS", None, id="no-host"),
        pytest.param("https://contoso.sharepoint.com/a b", None, id="whitespace"),
        pytest.param("/sites/KS/Doc.pdf", None, id="relative"),
        pytest.param("", None, id="empty"),
        pytest.param(None, None, id="none"),
    ],
)
def test_only_absolute_https_urls_are_served_as_links(value, expected):
    assert https_url_or_none(value) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://contoso.sharepoint.com/sites/KS",
            "https://contoso.sharepoint.com/sites/KS",
        ),
        ("javascript:alert(1)", None),
        ("http://contoso.sharepoint.com/sites/KS", None),
    ],
)
def test_knowledge_items_only_link_to_https(url, expected):
    knowledge = IntegrationKnowledgePublic.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "Policies",
            "url": url,
            "tenant_id": "00000000-0000-0000-0000-000000000002",
            "space_id": "00000000-0000-0000-0000-000000000003",
            "user_integration_id": "00000000-0000-0000-0000-000000000004",
            "embedding_model": {
                "id": "00000000-0000-0000-0000-000000000005",
                "name": "text-embedding-3-small",
                "is_deprecated": False,
                "open_source": False,
            },
            "metadata": {"size": 0},
            "integration_type": "sharepoint",
            "task": "pull_sharepoint_content",
        }
    )

    assert knowledge.url == expected


@pytest.mark.parametrize("name", ["", "   ", "x" * 256])
@pytest.mark.parametrize(
    "model",
    [
        CreateSpaceIntegrationKnowledge,
        UpdateIntegrationKnowledgeRequest,
        UpdateIntegrationKnowledgeWrapperRequest,
    ],
)
def test_a_knowledge_name_is_neither_blank_nor_overlong(model, name):
    fields = {
        "embedding_model": {"id": "00000000-0000-0000-0000-000000000001"},
        "url": "https://contoso.sharepoint.com/sites/x",
        "name": name,
    }
    with pytest.raises(ValidationError) as error:
        model(**fields)
    assert [problem["loc"] for problem in error.value.errors()] == [("name",)]


def test_a_knowledge_name_is_stored_without_surrounding_whitespace():
    assert UpdateIntegrationKnowledgeRequest(name="  Protokoll  ").name == "Protokoll"
    assert UpdateIntegrationKnowledgeRequest(name="x" * 255).name == "x" * 255


def test_a_batch_wrapper_name_may_be_blank_but_not_overlong():
    request = {
        "embedding_model": {"id": "00000000-0000-0000-0000-000000000001"},
        "items": [_BASE],
    }
    assert CreateSpaceIntegrationKnowledgeBatchRequest(**request, wrapper_name="")
    with pytest.raises(ValidationError):
        CreateSpaceIntegrationKnowledgeBatchRequest(**request, wrapper_name="x" * 256)


@pytest.mark.parametrize("name", ["", "   ", "x" * 256])
def test_a_batch_item_name_is_checked_per_item_not_per_request(name):
    """A SharePoint name may exceed 255 characters; it fails its item only."""
    assert CreateSpaceIntegrationKnowledgeBatchItem(**{**_BASE, "name": name})


def test_a_batch_item_name_beyond_any_sharepoint_name_is_a_malformed_body():
    with pytest.raises(ValidationError):
        CreateSpaceIntegrationKnowledgeBatchItem(**{**_BASE, "name": "x" * 2049})
