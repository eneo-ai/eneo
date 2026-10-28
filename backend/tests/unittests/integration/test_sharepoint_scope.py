"""Folder scope paths: a Graph path is decoded once, a name never."""

from urllib.parse import quote

import pytest

from eneo.integration.infrastructure.content_service import (
    sharepoint_scope as scope_rules,
)


def _graph_path(*segments: str) -> str:
    """A parentReference.path as Graph sends it: every segment percent-encoded."""
    return "/drives/d/root:/" + "/".join(quote(segment) for segment in segments)


def _child_of(*segments: str) -> dict:
    return {
        "id": "child",
        "parentReference": {"id": "parent", "path": _graph_path(*segments)},
    }


@pytest.mark.parametrize(
    "folder_name", ["Budget 50%AB", "100% klart", "Årsmöte 2026", "Plain"]
)
def test_files_under_a_folder_stay_in_its_scope_whatever_its_name(folder_name):
    scope_path = scope_rules.folder_path_from_item(
        {"name": folder_name, "parentReference": {"path": _graph_path("Ekonomi")}}
    )

    assert scope_path == f"/Ekonomi/{folder_name}"
    assert scope_rules.is_item_in_folder_scope(
        _child_of("Ekonomi", folder_name, "Sub"),
        "scope-id",
        scope_folder_path=scope_path,
        selected_item_type="folder",
    )
    assert not scope_rules.is_item_in_folder_scope(
        _child_of("Ekonomi", f"{folder_name} (kopia)"),
        "scope-id",
        scope_folder_path=scope_path,
        selected_item_type="folder",
    )


def test_a_parent_path_with_a_percent_is_decoded_once():
    scope_path = scope_rules.folder_path_from_item(
        {"name": "Q1", "parentReference": {"path": _graph_path("Budget 50%AB")}}
    )

    assert scope_path == "/Budget 50%AB/Q1"


def test_a_scope_path_stored_encoded_still_matches():
    """Stored before scope paths were stored decoded; refreshed by the next pass."""
    assert scope_rules.is_item_in_folder_scope(
        _child_of("Möten och protokoll", "2026"),
        "scope-id",
        scope_folder_path="/M%C3%B6ten%20och%20protokoll",
        selected_item_type="folder",
    )


def test_an_ancestor_with_a_percent_in_its_name_is_recognised():
    ancestor = {
        "name": "Budget 50%AB",
        "folder": {},
        "parentReference": {"path": _graph_path("Ekonomi")},
    }

    assert scope_rules.is_ancestor_of_scope(ancestor, "/Ekonomi/Budget 50%AB/Q1")
    assert not scope_rules.is_ancestor_of_scope(ancestor, "/Ekonomi/Budget 50%AB")
