"""The picker tree shows the library columns a file would be imported with."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.preview_service import (
    sharepoint_tree_service as tree_module,
)
from eneo.integration.infrastructure.preview_service.sharepoint_tree_service import (
    SharePointTreeService,
)

CLIENT_PATCH = f"{tree_module.__name__}.SharePointContentClient"


def _token() -> SharePointToken:
    return SharePointToken(
        id=uuid4(),
        access_token="token",
        refresh_token="refresh",
        token_type=IntegrationType.Sharepoint,
        user_integration=MagicMock(),
    )


def _client(*, columns, items, enabled=True):
    client = MagicMock()
    client.list_item_fields_enabled = enabled
    client.get_list_columns = AsyncMock(return_value=columns)
    client.get_folder_items = AsyncMock(return_value=items)
    client.get_default_drive_id = AsyncMock(return_value="d1")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return client, context


async def test_files_carry_their_admitted_columns_and_folders_do_not():
    client, context = _client(
        columns=[
            {"name": "Dokumenttyp", "displayName": "Dokumenttyp", "choice": {}},
            {"name": "FileLeafRef", "displayName": "Namn", "text": {}},
        ],
        items=[
            {
                "id": "f1",
                "name": "Rutiner",
                "folder": {},
                "listItem": {"fields": {"Dokumenttyp": "Mapp"}},
            },
            {
                "id": "i1",
                "name": "rutin.docx",
                "file": {},
                "listItem": {"fields": {"Dokumenttyp": "Rutin", "FileLeafRef": "x"}},
            },
        ],
    )

    with patch(CLIENT_PATCH, return_value=context):
        result = await SharePointTreeService().get_folder_tree(
            _token(), site_id="s1", drive_id="d1"
        )

    folder, file = result["items"]
    assert folder["source_metadata"] == []
    assert [(e.label, e.value) for e in file["source_metadata"]] == [
        ("Dokumenttyp", "Rutin")
    ]
    client.get_list_columns.assert_awaited_once_with("d1")


async def test_subfolders_without_files_do_not_ask_for_the_columns():
    client, context = _client(
        columns=[{"name": "Dokumenttyp", "displayName": "Dokumenttyp", "choice": {}}],
        items=[{"id": "f2", "name": "Sub", "folder": {}}],
    )

    with patch(CLIENT_PATCH, return_value=context):
        result = await SharePointTreeService().get_folder_tree(
            _token(), site_id="s1", drive_id="d1", folder_id="f1"
        )

    client.get_list_columns.assert_not_awaited()
    assert result["columns"] == []


async def test_unreadable_columns_leave_the_tree_without_properties():
    client, context = _client(
        columns=[],
        items=[
            {"id": "i1", "name": "a.pdf", "file": {}, "listItem": {"fields": {"X": 1}}}
        ],
    )
    client.get_list_columns = AsyncMock(side_effect=RuntimeError("403"))

    with patch(CLIENT_PATCH, return_value=context):
        result = await SharePointTreeService().get_folder_tree(
            _token(), site_id="s1", drive_id="d1"
        )

    assert result["items"][0]["source_metadata"] == []
