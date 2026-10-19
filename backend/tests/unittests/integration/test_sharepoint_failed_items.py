"""Items a pass could not finish: retried by the next delta, set aside when
they keep failing, and never on their own a reason to start over with a
full sync."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
)
from eneo.integration.infrastructure.content_service.sharepoint_results import (
    DeltaBaselineUnavailable,
    SyncItemsFailed,
)
from eneo.integration.infrastructure.content_service.sharepoint_sync_ledger import (
    SET_ASIDE_AFTER,
)
from eneo.integration.infrastructure.content_service.utils import ExtractionResult
from tests.unittests.integration.test_sharepoint_content_service import (
    _delta_file,
    _http_error,
    _mock_graph_client,
    _org_token_provider,
    _real_integration_knowledge,
)

_CLIENT = "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"


class FakeLedger:
    def __init__(self) -> None:
        self.failed: dict[str, int] = {}

    async def failed_passes(self, knowledge_id):
        return dict(self.failed)

    async def record_failed_passes(self, knowledge_id, passes):
        self.failed.update(passes)

    async def forget(self, knowledge_id, item_ids):
        for item_id in item_ids:
            self.failed.pop(item_id, None)


@pytest.fixture
def ledger():
    return FakeLedger()


@pytest.fixture
def mock_dependencies():
    return {
        "oauth_token_repo": AsyncMock(),
        "user": MagicMock(id=uuid4(), tenant_id=uuid4()),
        "info_blob_service": AsyncMock(),
        "integration_knowledge_repo": AsyncMock(),
        "oauth_token_service": AsyncMock(),
        "session": AsyncMock(),
        "tenant_sharepoint_app_repo": AsyncMock(),
        "org_token_provider": _org_token_provider(),
        "sync_log_repo": AsyncMock(),
        "change_key_service": AsyncMock(),
    }


@pytest.fixture
def mock_oauth_token():
    return MagicMock(
        id=uuid4(), access_token="token", base_url="https://graph.microsoft.com"
    )


@pytest.fixture
def sqlite_session(mock_dependencies):
    """A real session, so post-commit work runs when a pass commits."""
    engine = sa.create_engine("sqlite://")
    session = Session(engine)
    mock_dependencies["session"].sync_session = session
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def service(mock_dependencies, ledger):
    return SharePointContentService(**mock_dependencies, sync_ledger=ledger)


def _knowledge(mock_dependencies, oauth_token, **fields):
    ik = _real_integration_knowledge(**fields)
    mock_dependencies["oauth_token_repo"].one.return_value = oauth_token
    mock_dependencies["integration_knowledge_repo"].one.return_value = ik
    repo = mock_dependencies["info_blob_service"].repo
    repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
        return_value=[]
    )
    repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(return_value=[])
    mock_dependencies["change_key_service"].should_process.return_value = True
    return ik


def _root_file(item_id: str) -> dict:
    return {
        **_delta_file(item_id, f"{item_id}.docx"),
        "parentReference": {"driveId": "drive-456", "siteId": "site-123"},
    }


def _extract_failing(*failing: str):
    async def extract(*, drive_id, item_id):
        if item_id in failing:
            raise _http_error(502, "Bad Gateway")
        return ExtractionResult.ok("Body", "text/plain")

    return extract


async def _committed(session, service, run):
    """One pass in a transaction that commits, as the worker does on a soft failure."""
    session.begin()
    try:
        return await run()
    finally:
        session.commit()
        await asyncio.gather(*service._post_transaction_tasks)


def _last_log(mock_dependencies):
    return mock_dependencies["sync_log_repo"].add.await_args.args[0]


class TestRepeatedFailures:
    async def test_an_item_failing_every_pass_is_set_aside_so_the_token_advances(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        changes = [_delta_file("bad", "bad.docx"), _delta_file("good", "good.docx")]
        after_failed_passes = []
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            _mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("bad")
                ),
            )

            async def run():
                return await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

            for _ in range(SET_ASIDE_AFTER - 1):
                with pytest.raises(SyncItemsFailed):
                    await _committed(sqlite_session, service, run)
                after_failed_passes.append((ik.delta_token, dict(ledger.failed)))
            await _committed(sqlite_session, service, run)

        assert after_failed_passes == [
            ("token-1", {"bad": 1}),
            ("token-1", {"bad": 2}),
        ]
        assert ik.delta_token == "token-2"
        assert ik.last_sync_status == "success"
        assert ledger.failed == {}
        (set_aside,) = [
            detail
            for detail in _last_log(mock_dependencies).metadata["skipped_details"]
            if detail.get("code") == "set_aside"
        ]
        assert set_aside["file"] == "bad.docx"
        assert set_aside["params"]["attempts"] == SET_ASIDE_AFTER
        assert "HTTP 502" in set_aside["params"]["detail"]
        assert "retry" not in set_aside

    async def test_an_item_that_succeeds_again_starts_its_count_over(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        ledger.failed = {"flaky": SET_ASIDE_AFTER - 1}
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="updated")),
        ):
            _mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(
                    return_value=([_delta_file("flaky", "flaky.docx")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
                ),
            )
            await _committed(
                sqlite_session,
                service,
                lambda: service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                ),
            )

        assert ik.delta_token == "token-2"
        assert ledger.failed == {}

    async def test_without_a_ledger_a_failing_item_keeps_the_token_as_before(
        self, mock_dependencies, mock_oauth_token
    ):
        service = SharePointContentService(**mock_dependencies)
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            _mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(
                    return_value=([_delta_file("bad", "bad.docx")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("bad")
                ),
            )
            for _ in range(SET_ASIDE_AFTER + 1):
                with pytest.raises(SyncItemsFailed):
                    await service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    )

        assert ik.delta_token == "token-1"


class TestFullSyncFailures:
    async def test_one_failed_file_keeps_the_baseline_and_the_next_delta_retries_it(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token=None)
        files = [_root_file(f"f-{index}") for index in range(50)]
        upsert = AsyncMock(return_value="added")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", upsert),
        ):
            client = _mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=files),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("f-17")
                ),
            )
            with pytest.raises(SyncItemsFailed):
                await _committed(
                    sqlite_session,
                    service,
                    lambda: service.pull_content(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    ),
                )

            assert ik.delta_token == "delta-token"
            assert ik.last_sync_status == "error"
            assert ledger.failed == {"f-17": 1}
            assert upsert.await_count == 49

            client.get_delta_changes = AsyncMock(return_value=([], "token-2"))
            client.get_file_metadata = AsyncMock(return_value=_root_file("f-17"))
            client.get_file_extraction_by_id = AsyncMock(
                return_value=ExtractionResult.ok("Body", "text/plain")
            )
            await _committed(
                sqlite_session,
                service,
                lambda: service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                ),
            )

        client.get_file_metadata.assert_awaited_once_with(
            drive_id="drive-456", item_id="f-17"
        )
        assert upsert.await_count == 50
        assert ik.delta_token == "token-2"
        assert ik.last_sync_status == "success"
        assert ledger.failed == {}

    async def test_an_existing_token_survives_a_full_sync_with_a_failed_file(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            client = _mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(
                    return_value=[_root_file("a"), _root_file("b")]
                ),
                get_file_extraction_by_id=AsyncMock(side_effect=_extract_failing("b")),
            )
            with pytest.raises(SyncItemsFailed):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        client.initialize_delta_token.assert_not_awaited()
        assert ik.delta_token == "token-1"
        assert ledger.failed == {"b": 1}

    async def test_a_failure_no_delta_can_retry_still_clears_the_token(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        """A site page is only read by a full sync."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            _mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=[_root_file("a")]),
                get_file_extraction_by_id=AsyncMock(side_effect=_extract_failing("a")),
                get_site_pages=AsyncMock(
                    return_value={
                        "value": [
                            {"id": "page-1", "parentReference": {"siteId": "site-123"}}
                        ]
                    }
                ),
                get_page_content=AsyncMock(side_effect=_http_error(502, "Bad Gateway")),
            )
            with pytest.raises(SyncItemsFailed):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.delta_token is None

    async def test_a_retried_item_that_is_gone_is_removed(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        ledger.failed = {"gone": 1}
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge
        with patch(_CLIENT) as client_class:
            _mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
                get_file_metadata=AsyncMock(side_effect=_http_error(404, "Not Found")),
            )
            await _committed(
                sqlite_session,
                service,
                lambda: service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                ),
            )

        delete.assert_awaited_once_with(
            sharepoint_item_id="gone", integration_knowledge_id=ik.id
        )
        assert ik.delta_token == "token-2"
        assert ledger.failed == {}


class TestDeltaBaselineMint:
    async def test_a_full_sync_without_a_token_to_continue_from_is_not_a_success(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token=None)
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            _mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=[_root_file("a")]),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
                ),
                initialize_delta_token=AsyncMock(
                    side_effect=_http_error(503, "Service Unavailable")
                ),
            )
            with pytest.raises(DeltaBaselineUnavailable):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.delta_token is None
        assert ik.last_sync_status == "error"
        assert "change tracking could not be started" in ik.last_sync_error
        assert "503" in ik.last_sync_error
        assert ik.last_sync_summary["files_processed"] == 1
        sync_log = _last_log(mock_dependencies)
        assert sync_log.status == "error"
        assert sync_log.metadata["files_processed"] == 1

    async def test_no_delta_link_is_reported_too(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token=None)
        with patch(_CLIENT) as client_class:
            _mock_graph_client(
                client_class, initialize_delta_token=AsyncMock(return_value=None)
            )
            with pytest.raises(DeltaBaselineUnavailable, match="no delta link"):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )
