"""Knowledge selections only carry identifiers that are safe inside Graph URLs."""

import pytest
from pydantic import ValidationError

from eneo.integration.presentation.models import IntegrationKnowledgePublic
from eneo.integration.presentation.validation import https_url_or_none
from eneo.spaces.api.space_models import (
    CreateSpaceIntegrationKnowledge,
    CreateSpaceIntegrationKnowledgeBatchItem,
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
