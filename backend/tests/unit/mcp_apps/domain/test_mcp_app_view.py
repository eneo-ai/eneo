"""A view is identified by its HTML together with its render policy, a tool
declares it under ``_meta.ui`` (or the earlier flat key), and a tool that
lists only ``app`` as visibility is kept from the model."""

from eneo.mcp_apps.domain.mcp_app_view import (
    get_ui_resource_uri,
    is_model_visible,
    view_content_hash,
)


def test_same_html_with_a_wider_policy_is_another_view():
    narrow = view_content_hash("<html></html>", {"csp": {"connectDomains": []}})
    wide = view_content_hash(
        "<html></html>", {"csp": {"connectDomains": ["https://collect.example"]}}
    )

    assert narrow != wide


def test_policy_key_order_does_not_change_the_view():
    first = view_content_hash("<html></html>", {"a": 1, "b": 2})
    second = view_content_hash("<html></html>", {"b": 2, "a": 1})

    assert first == second


def test_no_policy_and_empty_policy_are_the_same_view():
    assert view_content_hash("<html></html>", None) == view_content_hash(
        "<html></html>", {}
    )


def test_flat_resource_key_is_read_and_the_nested_one_wins():
    assert get_ui_resource_uri({"ui/resourceUri": "ui://a/flat"}) == "ui://a/flat"
    assert (
        get_ui_resource_uri(
            {"ui": {"resourceUri": "ui://a/nested"}, "ui/resourceUri": "ui://a/flat"}
        )
        == "ui://a/nested"
    )


def test_resource_outside_the_ui_scheme_is_not_a_view():
    assert get_ui_resource_uri({"ui": {"resourceUri": "https://a.example/x"}}) is None


def test_only_a_tool_listing_app_alone_is_kept_from_the_model():
    assert is_model_visible(None)
    assert is_model_visible({"ui": {"resourceUri": "ui://a/b"}})
    assert is_model_visible({"ui": {"visibility": ["model", "app"]}})
    assert not is_model_visible({"ui": {"visibility": ["app"]}})
