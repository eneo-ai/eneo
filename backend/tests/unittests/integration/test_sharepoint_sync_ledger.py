"""What a sync keeps between its passes.

Items a pass could not finish are retried by the next delta, set aside when
they keep failing, and never on their own a reason to start over with a full
sync. A full sync makes the next delta walk its folders again."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    MissingDownloadUrlError,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_content_service as content_service_module,
)
from eneo.integration.infrastructure.content_service import (
    sharepoint_scope as scope_rules,
)
from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
)
from eneo.integration.infrastructure.content_service.sharepoint_results import (
    FAILURES_IN_A_ROW_TO_STOP,
    DeltaBaselineUnavailable,
    SyncAccessDenied,
    SyncDownloadsUnavailable,
    SyncItemsFailed,
    SyncStoppedEarly,
)
from eneo.integration.infrastructure.content_service.sharepoint_sync_ledger import (
    COUNT_INTERVAL_SECONDS,
    SET_ASIDE_AFTER,
    SET_ASIDE_SECONDS,
    FailedItem,
    decode_failed_items,
    encode_failed_items,
)
from eneo.integration.infrastructure.content_service.utils import ExtractionResult
from tests.unittests.integration.infrastructure.content_service.helpers import (
    delta_file,
    http_error,
    mock_graph_client,
    org_token_provider,
    real_integration_knowledge,
)

_CLIENT = "eneo.integration.infrastructure.content_service.sharepoint_content_service.SharePointContentClient"


NOW = 1_800_000_000
HOUR = 3600


class FakeLedger:
    """The knowledge row's ``sync_failed_items`` as the repository reads and
    writes it, and the walk generation."""

    def __init__(self, repo) -> None:
        self.stored: object = None
        self.generation = 0

        async def read(id):
            return self.stored

        async def write(id, **fields):
            if "sync_failed_items" in fields:
                self.stored = fields["sync_failed_items"]

        repo.get_sync_failed_items = AsyncMock(side_effect=read)
        repo.update_sync_state = AsyncMock(side_effect=write)

    @property
    def failed(self) -> dict[str, FailedItem]:
        return decode_failed_items(self.stored)

    @failed.setter
    def failed(self, items: dict[str, FailedItem]) -> None:
        self.stored = encode_failed_items(items)

    def counted(self) -> dict[str, int]:
        return {item_id: item.counted for item_id, item in self.failed.items()}

    async def current(self, knowledge_id):
        return self.generation

    async def advance(self, knowledge_id):
        self.generation += 1


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
        "org_token_provider": org_token_provider(),
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


def _failed(counted: int, *, at: int = NOW - HOUR) -> FailedItem:
    return FailedItem(counted, at)


@pytest.fixture
def ledger(mock_dependencies):
    return FakeLedger(mock_dependencies["integration_knowledge_repo"])


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def service(mock_dependencies, ledger, clock):
    service = SharePointContentService(**mock_dependencies, walk_generations=ledger)
    service._clock = lambda: clock["now"]
    return service


def _knowledge(mock_dependencies, oauth_token, **fields):
    ik = real_integration_knowledge(**fields)
    mock_dependencies["oauth_token_repo"].one.return_value = oauth_token
    mock_dependencies["integration_knowledge_repo"].one.return_value = ik
    repo = mock_dependencies["info_blob_service"].repo
    repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
        return_value=[]
    )
    repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(return_value=[])
    if isinstance(mock_dependencies["change_key_service"], AsyncMock):
        mock_dependencies["change_key_service"].should_process.return_value = True
    return ik


def _root_file(item_id: str) -> dict:
    return {
        **delta_file(item_id, f"{item_id}.docx"),
        "parentReference": {"driveId": "drive-456", "siteId": "site-123"},
    }


async def _metadata(*, drive_id, item_id):
    return _root_file(item_id)


def _extract_failing(*failing: str):
    async def extract(*, drive_id, item_id):
        if item_id in failing:
            raise http_error(502, "Bad Gateway")
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
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        clock,
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        changes = [delta_file("bad", "bad.docx"), delta_file("good", "good.docx")]
        after_failed_passes = []
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
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
                after_failed_passes.append((ik.delta_token, ledger.counted()))
                clock["now"] += COUNT_INTERVAL_SECONDS
            await _committed(sqlite_session, service, run)

        assert after_failed_passes == [
            ("token-1", {"bad": 1}),
            ("token-1", {"bad": 2}),
        ]
        assert ik.delta_token == "token-2"
        assert ik.last_sync_status == "success"
        assert ledger.failed == {
            "bad": FailedItem(SET_ASIDE_AFTER, clock["now"], set_aside_at=clock["now"])
        }
        (set_aside,) = [
            detail
            for detail in _last_log(mock_dependencies).metadata["skipped_details"]
            if detail.get("code") == "set_aside"
        ]
        assert set_aside["file"] == "bad.docx"
        assert set_aside["params"]["attempts"] == SET_ASIDE_AFTER
        assert "HTTP 502" in set_aside["params"]["detail"]
        assert set_aside["retry"] is True

    async def test_an_item_that_succeeds_again_starts_its_count_over(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        ledger.failed = {"flaky": _failed(SET_ASIDE_AFTER - 1)}
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="updated")),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("flaky", "flaky.docx")], "token-2")
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

    async def test_an_unreadable_record_never_sets_an_item_aside(
        self, mock_dependencies, mock_oauth_token
    ):
        """Without the counts of earlier passes the token stays, as before."""
        mock_dependencies[
            "integration_knowledge_repo"
        ].get_sync_failed_items.side_effect = RuntimeError("database error")
        service = SharePointContentService(**mock_dependencies)
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("bad", "bad.docx")], "token-2")
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


class TestFailedItem:
    def test_a_failure_counts_once_per_interval(self):
        item = FailedItem.first_failure(NOW)

        assert item.after_failure(NOW + COUNT_INTERVAL_SECONDS - 1) == item
        assert item.after_failure(NOW + COUNT_INTERVAL_SECONDS) == FailedItem(
            2, NOW + COUNT_INTERVAL_SECONDS
        )

    def test_the_last_counted_failure_sets_it_aside(self):
        item = FailedItem(SET_ASIDE_AFTER - 1, NOW - COUNT_INTERVAL_SECONDS)

        assert item.after_failure(NOW) == FailedItem(
            SET_ASIDE_AFTER, NOW, set_aside_at=NOW
        )
        assert not item.after_failure(NOW).due(NOW + SET_ASIDE_SECONDS - 1)
        assert item.after_failure(NOW).due(NOW + SET_ASIDE_SECONDS)

    def test_a_set_aside_item_failing_again_starts_another_cool_off(self):
        item = FailedItem(SET_ASIDE_AFTER, NOW, set_aside_at=NOW)
        later = NOW + SET_ASIDE_SECONDS

        assert item.after_failure(later) == FailedItem(
            SET_ASIDE_AFTER, NOW, set_aside_at=later
        )

    @pytest.mark.parametrize(
        "item",
        [FailedItem(1, NOW), FailedItem(3, NOW, set_aside_at=NOW + 5)],
    )
    def test_the_stored_form_round_trips(self, item):
        assert FailedItem.decode(item.encode()) == item


class TestPacing:
    async def test_a_burst_of_failed_passes_counts_once(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        clock,
    ):
        """Notifications during an outage replay the pass every few minutes;
        only one failure per half hour counts toward the cap."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("bad", "bad.docx")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("bad")
                ),
            )
            for _ in range(SET_ASIDE_AFTER * 2):
                with pytest.raises(SyncItemsFailed):
                    await _committed(
                        sqlite_session,
                        service,
                        lambda: service.process_delta_changes(
                            token_id=mock_oauth_token.id,
                            integration_knowledge_id=ik.id,
                        ),
                    )
                clock["now"] += 4 * 60

        assert ik.delta_token == "token-1"
        assert ledger.failed == {"bad": FailedItem(1, NOW)}


class TestOutages:
    """Failures that say something is down count toward nobody's cap."""

    async def test_an_outage_over_several_passes_sets_nothing_aside(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        clock,
    ):
        """An embedding provider down for a first import and two quiet passes
        an hour apart: the import fails visibly and every file comes back."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token=None)
        files = [_root_file(f"f-{index}") for index in range(5)]
        upsert = AsyncMock(side_effect=RuntimeError("embedding provider unavailable"))

        def delta():
            return service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", upsert),
        ):
            client = mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=files),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
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
            client.get_delta_changes = AsyncMock(return_value=([], "token-2"))
            client.get_file_metadata = AsyncMock(side_effect=_metadata)
            for _ in range(SET_ASIDE_AFTER + 1):
                clock["now"] += HOUR
                with pytest.raises(SyncItemsFailed):
                    await _committed(sqlite_session, service, delta)
            assert ik.delta_token == "delta-token"
            assert ik.last_sync_status == "error"
            assert ledger.counted() == dict.fromkeys((file["id"] for file in files), 0)

            upsert.side_effect = None
            upsert.return_value = "added"
            upsert.reset_mock()
            await _committed(sqlite_session, service, delta)

        assert upsert.await_count == len(files)
        assert ik.delta_token == "token-2"
        assert ik.last_sync_status == "success"
        assert ledger.failed == {}

    async def test_most_of_a_pass_failing_counts_for_nobody(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        changes = [delta_file(f"item-{index}", f"{index}.docx") for index in range(4)]
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("item-0", "item-1", "item-2")
                ),
            )
            with pytest.raises(SyncItemsFailed):
                await _committed(
                    sqlite_session,
                    service,
                    lambda: service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    ),
                )

        assert ledger.counted() == {"item-0": 0, "item-1": 0, "item-2": 0}

    async def test_many_failures_alike_count_for_nobody_among_many_successes(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        changes = [delta_file(f"item-{index}", f"{index}.docx") for index in range(40)]
        failing = {f"item-{index}" for index in range(0, 40, 3)}
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing(*failing)
                ),
            )
            with pytest.raises(SyncItemsFailed):
                await _committed(
                    sqlite_session,
                    service,
                    lambda: service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    ),
                )

        assert ledger.counted() == dict.fromkeys(failing, 0)


class TestStoppingEarly:
    async def test_a_delta_stops_after_too_many_failures_in_a_row(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        changes = [delta_file(f"item-{index}", f"{index}.docx") for index in range(30)]
        extraction = AsyncMock(side_effect=http_error(503, "Service Unavailable"))
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=extraction,
            )
            with pytest.raises(SyncStoppedEarly, match="Stopped after 10 files"):
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert extraction.await_count == FAILURES_IN_A_ROW_TO_STOP
        assert ik.delta_token == "token-1"
        assert ik.last_sync_status == "error"

    async def test_a_full_sync_stopped_early_leaves_the_next_sync_a_full_one(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        """The files it did not reach are recorded nowhere."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token=None)
        files = [_root_file(f"f-{index}") for index in range(30)]
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=files),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=http_error(503, "Service Unavailable")
                ),
            )
            with pytest.raises(SyncStoppedEarly):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.delta_token is None

    async def test_failures_between_successes_do_not_stop_the_pass(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        changes = [delta_file(f"item-{index}", f"{index}.docx") for index in range(30)]
        failing = {f"item-{index}" for index in range(30) if index % 4}
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            client = mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing(*failing)
                ),
            )
            with pytest.raises(SyncItemsFailed) as failure:
                await service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert not isinstance(failure.value, SyncStoppedEarly)
        assert client.get_file_extraction_by_id.await_count == 30


class TestSetAsideCoolOff:
    def _run(self, service, mock_oauth_token, ik):
        return service.process_delta_changes(
            token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
        )

    async def test_a_set_aside_item_waits_out_its_cool_off(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        clock,
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        set_aside = FailedItem(SET_ASIDE_AFTER, NOW, set_aside_at=NOW)
        ledger.failed = {"aside": set_aside}
        clock["now"] = NOW + SET_ASIDE_SECONDS - HOUR
        with patch(_CLIENT) as client_class:
            client = mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
            )
            await _committed(
                sqlite_session,
                service,
                lambda: self._run(service, mock_oauth_token, ik),
            )

        client.get_file_metadata.assert_not_called()
        assert ik.delta_token == "token-2"
        assert ledger.failed == {"aside": set_aside}

    async def test_after_its_cool_off_a_delta_pass_brings_it_back(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        clock,
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        ledger.failed = {"aside": FailedItem(SET_ASIDE_AFTER, NOW, set_aside_at=NOW)}
        clock["now"] = NOW + SET_ASIDE_SECONDS
        upsert = AsyncMock(return_value="added")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", upsert),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
                get_file_metadata=AsyncMock(return_value=_root_file("aside")),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
                ),
            )
            await _committed(
                sqlite_session,
                service,
                lambda: self._run(service, mock_oauth_token, ik),
            )

        upsert.assert_awaited_once()
        assert ik.delta_token == "token-2"
        assert ledger.failed == {}

    async def test_failing_again_it_stays_aside_without_holding_the_token(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        clock,
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        ledger.failed = {"aside": FailedItem(SET_ASIDE_AFTER, NOW, set_aside_at=NOW)}
        retried_at = clock["now"] = NOW + SET_ASIDE_SECONDS
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
                get_file_metadata=AsyncMock(return_value=_root_file("aside")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("aside")
                ),
            )
            await _committed(
                sqlite_session,
                service,
                lambda: self._run(service, mock_oauth_token, ik),
            )

        assert ik.delta_token == "token-2"
        assert ik.last_sync_status == "success"
        assert ledger.failed == {
            "aside": FailedItem(SET_ASIDE_AFTER, NOW, set_aside_at=retried_at)
        }
        (detail,) = _last_log(mock_dependencies).metadata["skipped_details"]
        assert detail["code"] == "set_aside"


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
            client = mock_graph_client(
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
            assert ledger.counted() == {"f-17": 1}
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
            client = mock_graph_client(
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
        assert ledger.counted() == {"b": 1}

    async def test_a_failure_no_delta_can_retry_still_clears_the_token(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        """A site page is only read by a full sync."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
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
                get_page_content=AsyncMock(side_effect=http_error(502, "Bad Gateway")),
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
        ledger.failed = {"gone": _failed(1)}
        delete = mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
                get_file_metadata=AsyncMock(side_effect=http_error(404, "Not Found")),
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


class TestRetriesWhileAccessIsLost:
    async def test_retries_refused_for_the_identity_stay_recorded(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        ledger.failed = {item_id: _failed(1) for item_id in ("x", "y", "z")}

        async def metadata(*, drive_id, item_id):
            return _root_file(item_id)

        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
                get_file_metadata=AsyncMock(side_effect=metadata),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=http_error(403, "Forbidden")
                ),
            )
            with pytest.raises(SyncAccessDenied):
                await _committed(
                    sqlite_session,
                    service,
                    lambda: service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    ),
                )

        assert ik.delta_token == "token-1"
        assert ledger.counted() == {"x": 1, "y": 1, "z": 1}
        mock_dependencies[
            "info_blob_service"
        ].repo.delete_by_sharepoint_item_and_integration_knowledge.assert_not_called()


class TestRefusals:
    """A refusal removes a file's indexed copy only when a later pass confirms it."""

    def _delta(self, service, mock_oauth_token, ik):
        return lambda: service.process_delta_changes(
            token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
        )

    def _indexed(self, mock_dependencies, *item_ids):
        repo = mock_dependencies["info_blob_service"].repo
        repo.get_sharepoint_item_ids_for_integration_knowledge = AsyncMock(
            return_value=[(uuid4(), item_id) for item_id in item_ids]
        )
        repo.delete_by_sharepoint_item_and_integration_knowledge = AsyncMock(
            return_value=[MagicMock(size=0, title="indexed copy")]
        )
        return repo.delete_by_sharepoint_item_and_integration_knowledge

    @pytest.mark.parametrize(
        ("since", "removed"),
        [(COUNT_INTERVAL_SECONDS, True), (COUNT_INTERVAL_SECONDS - 60, False)],
        ids=["confirmed", "too-soon"],
    )
    async def test_a_second_refusal_removes_the_copy(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        since,
        removed,
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        delete = self._indexed(mock_dependencies, "secret")
        ledger.failed = {"secret": FailedItem(0, 0, refused_at=NOW - since)}
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(
                    return_value=([delta_file("secret", "secret.docx")], "token-2")
                ),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=http_error(403, "Forbidden")
                ),
            )
            await _committed(
                sqlite_session, service, self._delta(service, mock_oauth_token, ik)
            )

        assert ik.delta_token == "token-2"
        if removed:
            delete.assert_awaited_once_with(
                sharepoint_item_id="secret", integration_knowledge_id=ik.id
            )
            assert ledger.failed == {}
        else:
            delete.assert_not_called()
            assert ledger.failed == {"secret": FailedItem(0, 0, refused_at=NOW - since)}

    async def test_a_file_read_again_is_forgotten(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        delete = self._indexed(mock_dependencies, "secret")
        ledger.failed = {"secret": FailedItem(0, 0, refused_at=NOW - HOUR)}
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="unchanged")),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
                get_file_metadata=AsyncMock(side_effect=_metadata),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
                ),
            )
            await _committed(
                sqlite_session, service, self._delta(service, mock_oauth_token, ik)
            )

        delete.assert_not_called()
        assert ledger.failed == {}

    async def test_a_refused_retry_counts_toward_the_removal_not_the_identity(
        self,
        service,
        mock_dependencies,
        mock_oauth_token,
        ledger,
        sqlite_session,
        clock,
    ):
        """Three recorded items whose metadata read is refused in a quiet pass:
        recorded, and removed when a later pass is refused them too."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        item_ids = ["x", "y", "z"]
        delete = self._indexed(mock_dependencies, *item_ids)
        ledger.failed = {item_id: _failed(1) for item_id in item_ids}
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([], "token-2")),
                get_file_metadata=AsyncMock(side_effect=http_error(403, "Forbidden")),
            )
            await _committed(
                sqlite_session, service, self._delta(service, mock_oauth_token, ik)
            )
            assert ik.delta_token == "token-2"
            assert ik.last_sync_status == "success"
            delete.assert_not_called()
            assert {item.refused_at for item in ledger.failed.values()} == {NOW}

            clock["now"] += COUNT_INTERVAL_SECONDS
            await _committed(
                sqlite_session, service, self._delta(service, mock_oauth_token, ik)
            )

        removed = sorted(
            call.kwargs["sharepoint_item_id"] for call in delete.await_args_list
        )
        assert removed == item_ids
        assert ledger.failed == {}

    async def test_downloads_all_refused_or_hidden_are_about_the_identity(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        """SharePoint often answers 404 for what it hides from the identity."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        delete = self._indexed(mock_dependencies, "a", "b", "c")
        ledger.failed = {"a": FailedItem(0, 0, refused_at=NOW - HOUR)}
        changes = [delta_file(item_id, f"{item_id}.docx") for item_id in "abc"]
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=[
                        http_error(403, "Forbidden"),
                        http_error(404, "Not Found"),
                        http_error(404, "Not Found"),
                    ]
                ),
            )
            with pytest.raises(SyncAccessDenied, match="HTTP 403 or 404"):
                await _committed(
                    sqlite_session, service, self._delta(service, mock_oauth_token, ik)
                )

        delete.assert_not_called()
        assert ik.delta_token == "token-1"
        assert ledger.failed == {"a": FailedItem(0, 0, refused_at=NOW - HOUR)}


class TestRecordLimit:
    async def test_a_full_sync_with_more_failures_than_can_be_recorded_starts_over(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        """Above the limit the next sync is a full one, which heals what a delta
        could not retry."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        files = [_root_file(f"f-{index}") for index in range(4)]
        with (
            patch.object(content_service_module, "MAX_FAILED_ITEMS", 3),
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=files),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("f-0", "f-1", "f-2", "f-3")
                ),
            )
            with pytest.raises(SyncItemsFailed):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )

        assert ik.delta_token is None
        assert ledger.failed == {}

    async def test_a_delta_keeps_what_it_recorded_when_the_limit_is_reached(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        ledger.failed = {"old-1": _failed(1), "old-2": _failed(1)}
        changes = [delta_file(f"new-{index}", f"{index}.docx") for index in range(2)]
        with (
            patch.object(content_service_module, "MAX_FAILED_ITEMS", 3),
            patch(_CLIENT) as client_class,
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_metadata=AsyncMock(side_effect=_metadata),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=_extract_failing("old-1", "old-2", "new-0", "new-1")
                ),
            )
            with pytest.raises(SyncItemsFailed):
                await _committed(
                    sqlite_session,
                    service,
                    lambda: service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    ),
                )

        assert ik.delta_token == "token-1"
        assert set(ledger.failed) == {"old-1", "old-2"}


class TestSmallerGaps:
    async def test_no_download_for_any_file_of_a_pass_fails_it(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        """One item without a download is that item's; all of them is SharePoint's."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        changes = [delta_file(f"item-{index}", f"{index}.docx") for index in range(3)]
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=(changes, "token-2")),
                get_file_extraction_by_id=AsyncMock(
                    side_effect=MissingDownloadUrlError("No download URL")
                ),
            )
            with pytest.raises(
                SyncDownloadsUnavailable, match="no download for any of 3 files"
            ):
                await _committed(
                    sqlite_session,
                    service,
                    lambda: service.process_delta_changes(
                        token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                    ),
                )

        assert ik.delta_token == "token-1"
        assert ik.last_sync_status == "error"

    async def test_an_item_the_pass_could_not_place_stays_recorded(
        self, service, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        """Without the scope folder's path the pass decides nothing about it."""
        ik = _knowledge(
            mock_dependencies,
            mock_oauth_token,
            delta_token="token-1",
            selected_item_type="folder",
            folder_id="folder-a",
            folder_path=None,
        )
        ledger.failed = {"x": _failed(1)}
        elsewhere = {
            **delta_file("x", "x.docx"),
            "parentReference": {
                "id": "other",
                "path": "/drives/drive-456/root:/Elsewhere",
            },
        }
        with patch(_CLIENT) as client_class:
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(return_value=([elsewhere], "token-2")),
                get_file_metadata=AsyncMock(side_effect=http_error(404, "Not Found")),
            )
            await _committed(
                sqlite_session,
                service,
                lambda: service.process_delta_changes(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                ),
            )

        assert ledger.failed == {"x": _failed(1)}

    async def test_a_full_sync_fills_the_citation_cache(
        self, service, mock_dependencies, mock_oauth_token, ledger
    ):
        """A delta that later dedups the file then costs no title write."""
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token="token-1")
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
            patch.object(service, "_schedule_post_commit_change_keys") as schedule,
        ):
            mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=[_root_file("a")]),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
                ),
            )
            await service.pull_content(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        scheduled = [key for call in schedule.call_args_list for key in call.args[0]]
        assert [(item_id, key) for _, item_id, key in scheduled] == [
            ("a#citation", service._index.citation_key(_root_file("a")))
        ]


class TestDeltaBaselineMint:
    async def test_a_full_sync_without_a_token_to_continue_from_is_not_a_success(
        self, service, mock_dependencies, mock_oauth_token
    ):
        ik = _knowledge(mock_dependencies, mock_oauth_token, delta_token=None)
        with (
            patch(_CLIENT) as client_class,
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                client_class,
                get_drive_root_children=AsyncMock(return_value=[_root_file("a")]),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
                ),
                initialize_delta_token=AsyncMock(
                    side_effect=http_error(503, "Service Unavailable")
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
            mock_graph_client(
                client_class, initialize_delta_token=AsyncMock(return_value=None)
            )
            with pytest.raises(DeltaBaselineUnavailable, match="no delta link"):
                await service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                )


class FakeChangeKeys:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def should_process(self, *, integration_knowledge_id, item_id, change_key):
        return self.keys.get(item_id) != change_key

    async def update_change_key(self, *, integration_knowledge_id, item_id, change_key):
        self.keys[item_id] = change_key

    async def invalidate_change_key(self, *, integration_knowledge_id, item_id):
        self.keys.pop(item_id, None)


class TestFolderWalkCache:
    SCOPE = {
        "id": "folder-a",
        "name": "A",
        "folder": {"childCount": 1},
        "parentReference": {"path": "/drives/drive-456/root:/Documents"},
    }
    MOVED_BACK = {
        "id": "folder-x",
        "name": "X",
        "folder": {"childCount": 1},
        "parentReference": {
            "id": "folder-a",
            "path": "/drives/drive-456/root:/Documents/A",
        },
    }

    async def test_a_full_sync_has_the_next_delta_walk_its_folders_again(
        self, mock_dependencies, mock_oauth_token, ledger, sqlite_session
    ):
        """The full sync may have removed a folder's files as orphans while the
        folder was elsewhere; moved back under the same parent it must be walked."""
        mock_dependencies["change_key_service"] = FakeChangeKeys()
        service = SharePointContentService(**mock_dependencies, walk_generations=ledger)
        ik = _knowledge(
            mock_dependencies,
            mock_oauth_token,
            delta_token="token-1",
            selected_item_type="folder",
            folder_id="folder-a",
            folder_path="/Documents/A",
        )
        walk = AsyncMock(return_value=[delta_file("x-1", "one.docx")])

        def delta():
            return service.process_delta_changes(
                token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
            )

        with (
            patch(_CLIENT) as client_class,
            patch.object(scope_rules, "enumerate_items", walk),
            patch.object(service._index, "upsert", AsyncMock(return_value="added")),
        ):
            mock_graph_client(
                client_class,
                get_delta_changes=AsyncMock(
                    return_value=([self.MOVED_BACK], "token-2")
                ),
                get_file_metadata=AsyncMock(return_value=self.SCOPE),
                get_file_extraction_by_id=AsyncMock(
                    return_value=ExtractionResult.ok("Body", "text/plain")
                ),
                get_folder_items=AsyncMock(return_value=[]),
            )
            await _committed(sqlite_session, service, delta)
            await _committed(sqlite_session, service, delta)
            walks_before_full_sync = walk.await_count

            await _committed(
                sqlite_session,
                service,
                lambda: service.pull_content(
                    token_id=mock_oauth_token.id, integration_knowledge_id=ik.id
                ),
            )
            walks_by_full_sync = walk.await_count - walks_before_full_sync
            await _committed(sqlite_session, service, delta)

        assert walks_before_full_sync == 1
        assert walk.await_count == walks_before_full_sync + walks_by_full_sync + 1
        assert ledger.generation == 1
