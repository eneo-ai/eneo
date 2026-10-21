"""Status, timestamp, token and sync-log bookkeeping shared by the content services."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from typing_extensions import Unpack

from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.repositories.integration_knowledge_repo import (
    SyncStateFields,
)
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error

if TYPE_CHECKING:
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeRepository,
    )
    from eneo.integration.domain.repositories.sync_log_repo import (
        SyncLogRepository,
    )
    from eneo.integration.domain.value_objects import SyncMetadata

logger = get_logger(__name__)


def sync_outcome_fields(
    knowledge: "IntegrationKnowledge", *, with_summary: bool = True
) -> SyncStateFields:
    """The columns a finished pass writes; the entity copy carries the values."""
    fields: SyncStateFields = {
        "last_sync_status": knowledge.last_sync_status,
        "last_sync_error": knowledge.last_sync_error,
        "last_synced_at": knowledge.last_synced_at,
        "delta_token": knowledge.delta_token,
    }
    if with_summary:
        fields["last_sync_summary"] = knowledge.last_sync_summary
    return fields


class SyncStateRecorder:
    """Records a pass's start, success and failure on the knowledge row.

    Every write goes through ``update_sync_state`` so a rename committed
    during a long sync survives, and every method here that runs after a
    failure never raises: the worker commits on a soft failure, so what is
    written here is what the UI shows.
    """

    def __init__(
        self,
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        sync_log_repo: "SyncLogRepository | None" = None,
    ) -> None:
        self._knowledge_repo = integration_knowledge_repo
        self._sync_log_repo = sync_log_repo

    async def started(
        self,
        knowledge: "IntegrationKnowledge",
        at: datetime,
        **binding: Unpack[SyncStateFields],
    ) -> None:
        """Move ``last_sync_attempted_at`` and persist the binding the caller resolved."""
        knowledge.mark_sync_started(at)
        binding["last_sync_attempted_at"] = at
        await self._knowledge_repo.update_sync_state(knowledge.id, **binding)

    async def succeeded(
        self,
        knowledge: "IntegrationKnowledge",
        at: datetime,
        *,
        with_summary: bool = True,
    ) -> None:
        """Persist the entity's outcome: status, timestamps, token and (optionally) summary."""
        knowledge.mark_sync_succeeded(at)
        await self._knowledge_repo.update_sync_state(
            knowledge.id, **sync_outcome_fields(knowledge, with_summary=with_summary)
        )

    async def failed(
        self,
        knowledge_id: Optional[UUID],
        failure: Exception,
        *,
        sync_type: str,
        started_at: datetime,
        metadata: "SyncMetadata",
        summary_counts: dict[str, Any] | None = None,
        clear_delta_token: bool = False,
        delta_token: str | None = None,
    ) -> None:
        """Persist the failure before the caller re-raises; never raises itself.

        Each write is attempted on its own so a broken status row still leaves
        a sync log, and neither can replace the exception being recorded.
        ``clear_delta_token`` drops the token when a full sync could not finish
        every item and nothing retries them: a delta from it would never
        re-emit those items, so the next sync must be a full one.
        ``delta_token`` is persisted instead when the next delta pass retries
        them.
        """
        if knowledge_id is None:
            return
        error = user_visible_error(failure)
        failed_at = datetime.now(timezone.utc)
        try:
            knowledge = await self._knowledge_repo.one(id=knowledge_id)
            knowledge.mark_sync_failed(error)
            fields: SyncStateFields = {
                "last_sync_status": knowledge.last_sync_status,
                "last_sync_error": knowledge.last_sync_error,
            }
            if summary_counts is not None:
                knowledge.last_sync_summary = summary_counts
                fields["last_sync_summary"] = summary_counts
            if clear_delta_token:
                knowledge.delta_token = None
                fields["delta_token"] = None
            elif delta_token is not None:
                knowledge.delta_token = delta_token
                fields["delta_token"] = delta_token
            await self._knowledge_repo.update_sync_state(knowledge_id, **fields)
        except Exception:
            logger.error(
                "Could not record sync failure on integration knowledge %s",
                knowledge_id,
                exc_info=True,
            )
        await self.add_log(
            SyncLog(
                integration_knowledge_id=knowledge_id,
                sync_type=sync_type,
                status="error",
                started_at=started_at,
                completed_at=failed_at,
                error_message=error,
                metadata=metadata,
            )
        )

    async def add_log(self, sync_log: SyncLog) -> None:
        """Write the pass's sync log; never raises.

        The status row and the token are already written by the time the log
        is added, so a failing log write must not reach the failure path and
        turn a finished success into an error, nor replace the exception a
        failure record is for.
        """
        if self._sync_log_repo is None:
            return
        try:
            await self._sync_log_repo.add(sync_log)
        except Exception:
            logger.error(
                "Could not write the %s sync log for integration knowledge %s",
                sync_log.status,
                sync_log.integration_knowledge_id,
                exc_info=True,
            )
