"""Relative paths and skipped-file lists for an imported item's documents."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.info_blobs.info_blob import InfoBlobInDBNoText, SourceMetadataEntry
from eneo.integration.application.integration_documents import (
    document_items,
    relative_document_path,
    skipped_documents,
)
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.sync_log import SyncLog

SITE = "https://contoso.sharepoint.com/sites/KS"
FOLDER = f"{SITE}/Shared%20Documents/Protokoll"
DRIVE = "https://contoso-my.sharepoint.com/personal/max_contoso_com/Documents"


@pytest.mark.parametrize(
    "case, document_url, item, expected",
    [
        (
            "folder import, nested subfolders",
            f"{FOLDER}/Bilagor/2026/KS-1.pdf",
            dict(item_url=FOLDER, folder_path="/Protokoll", resource_type="site"),
            "Bilagor/2026",
        ),
        (
            "folder import, document directly in the imported folder",
            f"{FOLDER}/KS-1.pdf",
            dict(item_url=FOLDER, folder_path="/Protokoll", resource_type="site"),
            "",
        ),
        (
            "folder import, URL-encoded Swedish letters",
            f"{FOLDER}/%C3%85rsm%C3%B6te/Bilagor/KS-1.pdf",
            dict(item_url=FOLDER, folder_path="/Protokoll", resource_type="site"),
            "Årsmöte/Bilagor",
        ),
        (
            "folder import, item URL stored decoded and with a trailing slash",
            f"{FOLDER}/Bilagor/KS-1.pdf",
            dict(
                item_url=f"{SITE}/Shared Documents/Protokoll/",
                folder_path="/Protokoll",
                resource_type="site",
            ),
            "Bilagor",
        ),
        (
            "site_root import drops the document library",
            f"{SITE}/Shared%20Documents/Protokoll/Bilagor/KS-1.pdf",
            dict(item_url=SITE, folder_path=None, resource_type="site"),
            "Protokoll/Bilagor",
        ),
        (
            "site_root import, document in the library root",
            f"{SITE}/Shared%20Documents/KS-1.pdf",
            dict(item_url=SITE, folder_path=None, resource_type="site"),
            "",
        ),
        (
            "OneDrive drive root keeps every folder below the drive",
            f"{DRIVE}/Projekt/2026/plan.docx",
            dict(item_url=DRIVE, folder_path=None, resource_type="onedrive"),
            "Projekt/2026",
        ),
        (
            "OneDrive folder import",
            f"{DRIVE}/Projekt/2026/plan.docx",
            dict(
                item_url=f"{DRIVE}/Projekt",
                folder_path="/Projekt",
                resource_type="onedrive",
            ),
            "2026",
        ),
        (
            "file import is its own document",
            f"{FOLDER}/KS-1.pdf",
            dict(item_url=f"{FOLDER}/KS-1.pdf", folder_path=None, resource_type="site"),
            "",
        ),
        (
            "renamed site: folder_path is found inside the URL",
            "https://contoso.sharepoint.com/sites/KS-ny/Delade%20dokument/Protokoll/Bilagor/KS-1.pdf",
            dict(item_url=FOLDER, folder_path="/Protokoll", resource_type="site"),
            "Bilagor",
        ),
        (
            "folder_path matches case-insensitively",
            f"{SITE}/Shared%20Documents/protokoll/Bilagor/KS-1.pdf",
            dict(item_url=None, folder_path="/Protokoll/", resource_type="site"),
            "Bilagor",
        ),
        (
            "URL sharing neither anchor keeps its own folders",
            "https://contoso.sharepoint.com/sites/Other/Docs/Arkiv/KS-1.pdf",
            dict(item_url=FOLDER, folder_path="/Protokoll", resource_type="site"),
            "sites/Other/Docs/Arkiv",
        ),
        (
            "no URL",
            None,
            dict(item_url=FOLDER, folder_path="/Protokoll", resource_type="site"),
            "",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and " " in value else None,
)
def test_relative_document_path(case, document_url, item, expected):
    assert relative_document_path(document_url, **item) == expected


def _blob(**overrides) -> InfoBlobInDBNoText:
    fields = dict(
        id=uuid4(),
        url=f"{FOLDER}/Bilagor/KS-1.pdf",
        title="KS-1.pdf",
        embedding_model_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        size=1000,
        integration_knowledge_id=uuid4(),
        source_id=uuid4(),
        version_state="active",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 13, tzinfo=timezone.utc),
        source_metadata=[
            SourceMetadataEntry(name="Status", label="Status", value="Klar")
        ],
    )
    fields.update(overrides)
    return InfoBlobInDBNoText(**fields)


def test_document_items_carry_the_relative_path_and_source_metadata():
    item = IntegrationKnowledge(
        name="Protokoll",
        user_integration=MagicMock(),
        embedding_model=MagicMock(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        url=FOLDER,
        folder_path="/Protokoll",
        selected_item_type="folder",
    )
    first = _blob()
    second = _blob(url=None, title=None, source_metadata=None, updated_at=None)

    items = document_items([first, second], item)

    assert [entry.model_dump(mode="json") for entry in items] == [
        {
            "id": str(first.id),
            "title": "KS-1.pdf",
            "relative_path": "Bilagor",
            "url": first.url,
            "size": 1000,
            "updated_at": "2026-10-13T00:00:00Z",
            "source_metadata": [
                {"name": "Status", "label": "Status", "value": "Klar", "kind": "text"}
            ],
        },
        {
            "id": str(second.id),
            "title": "",
            "relative_path": "",
            "url": None,
            "size": 1000,
            "updated_at": "2026-10-01T00:00:00Z",
            "source_metadata": [],
        },
    ]


def test_skipped_documents_without_a_sync_log_is_empty():
    assert skipped_documents(None).model_dump() == {
        "items": [],
        "total": 0,
        "truncated": False,
        "synced_at": None,
    }


@pytest.mark.parametrize(
    "metadata, completed_at, expected",
    [
        (
            {
                "skipped_details": [
                    {"file": "scan.pdf", "reason": "No text layer"},
                    {"file": "old.xyz", "reason": "Unsupported format"},
                ],
                "skipped_total": 17,
                "skipped_truncated": True,
            },
            datetime(2026, 10, 13, 8, tzinfo=timezone.utc),
            {
                "items": [
                    {"file": "scan.pdf", "reason": "No text layer"},
                    {"file": "old.xyz", "reason": "Unsupported format"},
                ],
                "total": 17,
                "truncated": True,
                "synced_at": datetime(2026, 10, 13, 8, tzinfo=timezone.utc),
            },
        ),
        # Logs written before the cap existed carry only the old counter and
        # no completion time while the sync still runs.
        (
            {"skipped_items": 1, "skipped_details": [{"file": "a.pdf", "reason": "r"}]},
            None,
            {
                "items": [{"file": "a.pdf", "reason": "r"}],
                "total": 1,
                "truncated": False,
                "synced_at": datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
            },
        ),
        (
            {},
            datetime(2026, 10, 13, 8, tzinfo=timezone.utc),
            {
                "items": [],
                "total": 0,
                "truncated": False,
                "synced_at": datetime(2026, 10, 13, 8, tzinfo=timezone.utc),
            },
        ),
    ],
    ids=["capped list", "legacy counter while running", "nothing skipped"],
)
def test_skipped_documents_reads_the_sync_log(metadata, completed_at, expected):
    log = SyncLog(
        integration_knowledge_id=uuid4(),
        sync_type="full",
        status="success" if completed_at else "in_progress",
        started_at=datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
        completed_at=completed_at,
        metadata=metadata,
    )

    assert skipped_documents(log).model_dump() == expected
