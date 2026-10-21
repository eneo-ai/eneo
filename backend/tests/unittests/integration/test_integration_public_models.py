"""What the integration models serve: stored error text is cleaned on the way
out, and only https links leave the API."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from eneo.integration.domain.skip_reasons import classify_skip_reason
from eneo.integration.domain.sync_progress import IntegrationSyncProgress
from eneo.integration.presentation.models import (
    IntegrationDocumentItem,
    IntegrationKnowledgeMetaData,
    IntegrationKnowledgePublic,
    IntegrationSkippedDocument,
    SyncLog,
)
from eneo.jobs.job_models import Task

SIGNED_URL = (
    "https://contoso.sharepoint.com/sites/KS/_layouts/15/download.aspx"
    "?UniqueId=abc&tempauth=v1.eyJhdWQiOiJ4In0.c2lnbmF0dXJl"
)
# What a sync wrote before it described errors for users.
STORED_HTTP_ERROR = f"403, message='Forbidden', url='{SIGNED_URL}'"
STORED_SQL_ERROR = (
    "(sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class "
    "'asyncpg.exceptions.UniqueViolationError'>: duplicate key\n"
    "[SQL: INSERT INTO info_blobs (title) VALUES ($1)]\n"
    "[parameters: ('Lönelista.xlsx',)]\n"
    "(Background on this error at: https://sqlalche.me/e/20/gkpj)"
)


def test_the_last_sync_error_and_summary_are_served_clean():
    metadata = IntegrationKnowledgeMetaData(
        size=0,
        last_sync_status="error",
        last_sync_error=STORED_HTTP_ERROR,
        last_sync_summary={
            "skipped_items": 1,
            "reconcile_warning": f"Orphan cleanup skipped ({STORED_SQL_ERROR})",
        },
    )

    assert metadata.last_sync_error == "HTTP 403 Forbidden"
    assert metadata.last_sync_summary == {
        "skipped_items": 1,
        "reconcile_warning": "Orphan cleanup skipped (Database error)",
    }
    assert IntegrationKnowledgeMetaData(size=0).last_sync_error is None


def test_a_sync_log_is_served_clean():
    log = SyncLog(
        id=uuid4(),
        integration_knowledge_id=uuid4(),
        sync_type="delta",
        status="error",
        error_message=STORED_SQL_ERROR,
        metadata={
            "skipped_items": 2,
            "skipped_details": [
                {"file": "a.docx", "reason": f"Error: {STORED_HTTP_ERROR}"},
                {"file": "b.zip", "reason": "Unsupported file type (.zip)"},
            ],
            "reconcile_warning": f"Orphan cleanup skipped ({STORED_HTTP_ERROR})",
            "changed_details": [{"file": "c.docx", "change": "added"}],
        },
        started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )

    served = log.model_dump(mode="json")

    assert served["error_message"] == "Database error"
    assert served["skipped_details"] == [
        {
            "file": "a.docx",
            "reason": "Error: HTTP 403 Forbidden",
            "code": "http_error",
            "params": {"status": 403, "message": "Forbidden"},
        },
        {
            "file": "b.zip",
            "reason": "Unsupported file type (.zip)",
            "code": "unsupported_type",
            "params": {"label": ".zip"},
        },
    ]
    assert served["metadata"]["skipped_details"] == served["skipped_details"]
    assert served["metadata"]["reconcile_warning"] == (
        "Orphan cleanup skipped (HTTP 403 Forbidden)"
    )
    assert served["metadata"]["changed_details"] == [
        {"file": "c.docx", "change": "added"}
    ]


@pytest.mark.parametrize(
    "metadata, served",
    [
        ({"trigger": [], "files_processed": 3}, {"files_processed": 3}),
        ({"files_processed": []}, {}),
        ({"skipped_truncated": []}, {}),
        ({"files_processed": 2.5}, {}),
        ({"skipped_details": {"a": 1}}, {}),
        ({"skipped_details": None, "changed_details": []}, {"changed_details": []}),
    ],
    ids=[
        "list-for-text",
        "list-for-count",
        "list-for-flag",
        "fraction-for-count",
        "mapping-for-list",
        "null-list",
    ],
)
def test_a_stored_value_of_another_shape_is_left_out(metadata, served):
    log = SyncLog(
        id=uuid4(),
        integration_knowledge_id=uuid4(),
        sync_type="delta",
        status="success",
        metadata=metadata,
        started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )

    assert log.metadata == served
    assert log.model_dump(mode="json")["skipped_details"] == []


def test_a_sync_log_another_release_wrote_is_served_without_its_unreadable_parts():
    """A null or unexpected value in one stored row failed the whole history."""
    log = SyncLog(
        id=uuid4(),
        integration_knowledge_id=uuid4(),
        sync_type="full",
        status="success",
        metadata={
            "files_processed": 3,
            "recovery": None,
            "trigger": {"source": "webhook"},
            "skipped_items": 1,
            "skipped_details": [
                {"file": "b.zip", "reason": "Unsupported file type (.zip)"},
                "b.zip",
            ],
            "changed_details": [{"file": "c.docx", "change": "renamed"}],
            "written_by_a_newer_release": {"x": 1},
        },
        started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )

    served = log.model_dump(mode="json")

    assert served["metadata"] == {
        "files_processed": 3,
        "skipped_items": 1,
        "changed_details": [],
        "skipped_details": [
            {
                "file": "b.zip",
                "reason": "Unsupported file type (.zip)",
                "code": "unsupported_type",
                "params": {"label": ".zip"},
            }
        ],
    }
    assert served["files_processed"] == 3


def test_skipped_documents_and_progress_reasons_are_served_clean():
    skipped = IntegrationSkippedDocument(
        file="a.docx", reason=f"Could not remove removed: {STORED_SQL_ERROR}"
    )
    progress = IntegrationSyncProgress.model_validate_json(
        IntegrationSyncProgress(
            integration_knowledge_id=uuid4(),
            sync_type="delta",
            phase="processing",
            started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            total=None,
            done=1,
            indexed=0,
            unchanged=0,
            skipped=1,
            deleted=0,
        )
        .model_dump_json()
        .replace(
            '"recent":[]',
            '"recent":[{"name":"a.docx","outcome":"skipped","reason":'
            + f'"Error: {STORED_HTTP_ERROR}"'
            + "}]",
        )
    )

    assert skipped.reason == "Could not remove removed: Database error"
    assert progress.recent[0].reason == "Error: HTTP 403 Forbidden"


def _public(url: str | None) -> IntegrationKnowledgePublic:
    return IntegrationKnowledgePublic(
        id=uuid4(),
        name="Protokoll",
        url=url,
        tenant_id=uuid4(),
        space_id=uuid4(),
        user_integration_id=uuid4(),
        embedding_model=EmbeddingModelPublic(
            id=uuid4(), name="model", is_deprecated=False, open_source=False
        ),
        metadata=IntegrationKnowledgeMetaData(size=0),
        integration_type="sharepoint",
        task=Task.PULL_SHAREPOINT_CONTENT,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://contoso.sharepoint.com/sites/KS/Shared%20Documents/Protokoll",
        "HTTPS://contoso.sharepoint.com/sites/KS",
        "https://contoso.atlassian.net/wiki/spaces/DOCS",
    ],
)
def test_https_links_are_served(url):
    assert _public(url).url == url
    assert _document(url).url == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        None,
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "http://contoso.sharepoint.com/sites/KS",
        "//evil.example/sites/KS",
        "/sites/KS",
        "https:///no-host",
        "https://user:pass@evil.example/sites/KS",
        " https://contoso.sharepoint.com/sites/KS",
    ],
)
def test_anything_but_an_https_link_is_served_as_null(url):
    assert _public(url).url is None
    assert _document(url).url is None


def _document(url: str | None) -> IntegrationDocumentItem:
    return IntegrationDocumentItem(
        id=uuid4(), title="KS-1.pdf", relative_path="", url=url, size=1
    )


@pytest.mark.parametrize(
    "reason",
    [
        "Folder scope path unavailable",
        "Missing item id",
        "Could not remove out-of-scope: database unavailable",
        "Could not remove out-of-scope-subtree: database unavailable",
        "Could not remove removed: database unavailable",
        # Releases before 2.2, for deleted items anywhere in the drive.
        "Could not remove: database unavailable",
    ],
)
def test_a_skip_of_an_item_never_placed_in_scope_is_served_without_its_name(reason):
    """Older syncs named these files, which may lie outside the imported folder."""
    log = SyncLog(
        id=uuid4(),
        integration_knowledge_id=uuid4(),
        sync_type="delta",
        status="success",
        metadata={"skipped_details": [{"file": "Lönelista HR.xlsx", "reason": reason}]},
        started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    metadata = IntegrationKnowledgeMetaData(
        size=0,
        last_sync_summary={
            "skipped_details": [{"file": "Lönelista HR.xlsx", "reason": reason}]
        },
    )

    served = [
        log.model_dump(mode="json")["skipped_details"][0],
        IntegrationSkippedDocument(
            file="Lönelista HR.xlsx", reason=reason
        ).model_dump(),
        metadata.model_dump()["last_sync_summary"]["skipped_details"][0],
    ]

    code, params, _ = classify_skip_reason(reason)
    coded = {"file": "", "reason": reason, "code": code, "params": params}
    assert served == [coded, {**coded, "retry": False}, coded]


def test_a_stored_skip_without_a_file_name_still_has_its_reason_cleaned():
    metadata = IntegrationKnowledgeMetaData(
        size=0,
        last_sync_summary={
            "skipped_details": [
                {
                    "file": None,
                    "reason": f"Could not remove unextractable: {STORED_SQL_ERROR}",
                },
                {"file": "Protokoll.docx", "reason": None},
            ]
        },
    )

    served = metadata.model_dump()["last_sync_summary"]["skipped_details"]

    assert served == [
        {
            "file": "",
            "reason": "Could not remove unextractable: Database error",
            "code": "removal_failed",
            "params": {"what": "unextractable", "detail": "Database error"},
        },
        {
            "file": "Protokoll.docx",
            "reason": "",
            "code": "error",
            "params": {"detail": ""},
        },
    ]


def test_a_skip_of_a_file_in_scope_keeps_its_name():
    skipped = IntegrationSkippedDocument(
        file="Protokoll.docx",
        reason="Could not remove unextractable: database unavailable",
    )

    assert skipped.file == "Protokoll.docx"


def test_a_stored_renewal_error_is_served_without_urls_or_hosts():
    from eneo.integration.presentation.admin_models import SharePointSubscriptionPublic

    served = SharePointSubscriptionPublic(
        id=uuid4(),
        user_integration_id=uuid4(),
        site_id="site",
        subscription_id="sub",
        drive_id="drive",
        expires_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        is_expired=False,
        expires_in_hours=10,
        consecutive_renewal_failures=1,
        last_renewal_error=(
            "Renewal failed: https://kommun.sharepoint.com/download.aspx"
            "?tempauth=SECRET-TOKEN at 10.1.2.3:6379"
        ),
        owner_type="organization",
    )

    assert served.last_renewal_error is not None
    assert "SECRET-TOKEN" not in served.last_renewal_error
    assert "10.1.2.3" not in served.last_renewal_error
    assert "Renewal failed" in served.last_renewal_error
