"""Relative paths and skipped-file lists for an imported item's documents."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.info_blobs.info_blob import InfoBlobInDBNoText, SourceMetadataEntry
from eneo.integration.application.integration_documents import (
    document_url_anchor,
    relative_document_path,
)
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.skip_reasons import classify_skip_reason
from eneo.integration.presentation import models as presentation
from eneo.integration.presentation.assemblers.integration_documents_assembler import (
    document_items,
    ordered_by_relative_path,
    skipped_documents,
)

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
            "folder_path stored decoded keeps a literal percent in a name",
            "https://contoso.sharepoint.com/sites/KS-ny/Delade%20dokument/Ekonomi/Budget%2050%25AB/Q1/KS-1.pdf",
            dict(
                item_url=FOLDER,
                folder_path="/Ekonomi/Budget 50%AB",
                resource_type="site",
            ),
            "Q1",
        ),
        (
            "folder_path stored encoded, before the sync refreshed it",
            "https://contoso.sharepoint.com/sites/KS-ny/Delade%20dokument/Ekonomi/Budget%2050%25AB/Q1/KS-1.pdf",
            dict(
                item_url=FOLDER,
                folder_path="/Ekonomi/Budget%2050%25AB",
                resource_type="site",
            ),
            "Q1",
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


def _user_integration(integration_type: str) -> MagicMock:
    user_integration = MagicMock()
    user_integration.tenant_integration.integration.integration_type = integration_type
    return user_integration


def _item(integration_type: str = "sharepoint", **overrides) -> IntegrationKnowledge:
    fields = dict(
        name="Protokoll",
        user_integration=_user_integration(integration_type),
        embedding_model=MagicMock(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        url=FOLDER,
        folder_path="/Protokoll",
        selected_item_type="folder",
    )
    fields.update(overrides)
    return IntegrationKnowledge(**fields)


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
    item = _item()
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


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "http://contoso.sharepoint.com/x"]
)
def test_documents_only_link_to_https(url):
    items = document_items([_blob(url=url)], _item())

    assert items[0].url is None


def test_confluence_pages_have_no_relative_path():
    item = _item(
        "confluence",
        url="https://contoso.atlassian.net/wiki/spaces/KS",
        folder_path=None,
        selected_item_type=None,
    )
    page = _blob(url="https://contoso.atlassian.net/wiki/spaces/KS/pages/123/Rutiner")

    assert [entry.relative_path for entry in document_items([page], item)] == [""]


@pytest.mark.parametrize(
    "url, expected",
    [
        (f"{FOLDER}/", FOLDER),
        (FOLDER, FOLDER),
        ("/", None),
        ("", None),
        (None, None),
    ],
)
def test_document_url_anchor_is_the_item_url_without_a_trailing_slash(url, expected):
    assert document_url_anchor(_item(url=url)) == expected


def test_ordered_by_relative_path_sorts_the_page_on_the_decoded_path():
    item = _item()
    # The query hands the page over in percent-encoded order: %C3%85 (Å)
    # before every plain letter.
    page = document_items(
        [
            _blob(url=f"{FOLDER}/%C3%85rsm%C3%B6te/b.pdf", title="b.pdf"),
            _blob(url=f"{FOLDER}/%C3%85rsm%C3%B6te/a.pdf", title="a.pdf"),
            _blob(url=f"{FOLDER}/Bilagor/c.pdf", title="c.pdf"),
            _blob(url=f"{FOLDER}/d.pdf", title="d.pdf"),
        ],
        item,
    )

    ascending = ordered_by_relative_path(page)
    descending = ordered_by_relative_path(page, descending=True)

    assert [(entry.relative_path, entry.title) for entry in ascending] == [
        ("", "d.pdf"),
        ("Bilagor", "c.pdf"),
        ("Årsmöte", "a.pdf"),
        ("Årsmöte", "b.pdf"),
    ]
    assert [entry.title for entry in descending] == ["b.pdf", "a.pdf", "c.pdf", "d.pdf"]


def test_skipped_documents_without_a_sync_log_is_empty():
    assert skipped_documents(None).model_dump() == {
        "items": [],
        "total": 0,
        "truncated": False,
        "synced_at": None,
    }


def _served(file: str, reason: str) -> dict:
    """A skipped document as the API serves it: classified from its text."""
    code, params, retry = classify_skip_reason(reason)
    return {
        "file": file,
        "reason": reason,
        "code": code,
        "params": params,
        "retry": retry,
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
                    _served("scan.pdf", "No text layer"),
                    _served("old.xyz", "Unsupported format"),
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
                "items": [_served("a.pdf", "r")],
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


@pytest.mark.parametrize(
    "metadata, total, truncated",
    [
        ({"skipped_details": None, "skipped_total": None}, 0, False),
        ({"skipped_details": "a.pdf", "skipped_total": "abc"}, 0, False),
        ({"skipped_details": [], "skipped_total": [], "skipped_items": 4}, 4, False),
        ({"skipped_truncated": "maybe", "skipped_total": 3}, 3, False),
    ],
    ids=["nulls", "text", "list-for-count", "text-for-flag"],
)
def test_skipped_documents_of_a_row_another_release_wrote(metadata, total, truncated):
    """The Skipped view read the stored JSON as it came and failed with a 500."""
    log = SyncLog(
        integration_knowledge_id=uuid4(),
        sync_type="full",
        status="success",
        started_at=datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
        metadata=metadata,
    )

    served = skipped_documents(log)

    assert (served.items, served.total, served.truncated) == ([], total, truncated)


def test_served_sync_log_tolerates_a_skipped_item_without_a_name():
    """Older syncs stored an unnamed item as a null file."""
    log = presentation.SyncLog(
        id=uuid4(),
        integration_knowledge_id=uuid4(),
        sync_type="full",
        status="success",
        metadata={
            "skipped_details": [
                {"file": None, "reason": "Missing item id"},
                {
                    "file": "a.pdf",
                    "reason": f"Download failed: {FOLDER}/a.pdf?tempauth=x",
                },
            ]
        },
        started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )

    assert log.metadata == {
        "skipped_details": [
            {
                "file": "",
                "reason": "Missing item id",
                "code": "missing_item_id",
                "params": {},
            },
            {
                "file": "a.pdf",
                "reason": f"Download failed: {FOLDER}/a.pdf",
                "code": "error",
                "params": {"detail": f"Download failed: {FOLDER}/a.pdf"},
            },
        ]
    }
