"""Builders the SharePoint content service tests share."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import aiohttp

from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)


def size_ledger(repo: AsyncMock, initial: int) -> dict[str, int]:
    """Stand in for the atomic UPDATE: the row's size lives here, not on entities."""
    ledger = {"size": initial}

    async def adjust_size(id, delta):
        ledger["size"] = max(0, ledger["size"] + delta)
        return ledger["size"]

    repo.adjust_size = AsyncMock(side_effect=adjust_size)
    return ledger


def http_error(status: int, message: str) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=status, message=message
    )


def reasons(details):
    """File, text and retry flag of each detail; codes are pinned by their own tests."""
    return [
        {
            "file": detail["file"],
            "reason": detail["reason"],
            **({"retry": True} if detail.get("retry") else {}),
        }
        for detail in details
    ]


def descendant(item_id: str, parent_path: str) -> dict:
    """A file Graph lists under a walked folder, placed by its parent path."""
    return {
        "id": item_id,
        "name": f"{item_id}.docx",
        "file": {},
        "parentReference": {
            "id": "walked",
            "path": f"/drives/drive-1/root:{parent_path}",
        },
    }


def org_token_provider(access_token: str = "tenant-app-access-token") -> AsyncMock:
    provider = AsyncMock()
    provider.get_access_token.return_value = access_token
    provider.access_token_provider = MagicMock(
        return_value=AsyncMock(return_value=access_token)
    )
    return provider


def real_integration_knowledge(**overrides):
    fields = {
        "name": "Docs",
        "user_integration": MagicMock(),
        "embedding_model": MagicMock(),
        "tenant_id": uuid4(),
        "space_id": uuid4(),
        "id": uuid4(),
        "site_id": "site-123",
        "drive_id": "drive-456",
    }
    fields.update(overrides)
    return IntegrationKnowledge(**fields)


def mock_graph_client(mock_client_class, **attrs):
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get_default_drive_id.return_value = "drive-456"
    mock_client.get_drive_root_children.return_value = []
    mock_client.get_site_pages.return_value = {"value": []}
    mock_client.initialize_delta_token.return_value = "delta-token"
    for name, value in attrs.items():
        setattr(mock_client, name, value)
    mock_client_class.return_value = mock_client
    return mock_client


def delta_file(item_id: str, name: str, **extra) -> dict:
    return {
        "id": item_id,
        "name": name,
        "file": {},
        "cTag": f"ctag-{item_id}",
        "webUrl": f"https://x/{name}",
        "parentReference": {"driveId": "drive-456"},
        **extra,
    }
