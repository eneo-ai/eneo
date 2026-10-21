from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)


def _knowledge() -> IntegrationKnowledge:
    return IntegrationKnowledge(
        name="Docs",
        user_integration=MagicMock(),
        embedding_model=MagicMock(),
        tenant_id=uuid4(),
        space_id=uuid4(),
    )


def test_a_failure_keeps_the_start_of_the_attempt():
    knowledge = _knowledge()
    started = datetime.now(timezone.utc)
    knowledge.mark_sync_started(started)

    knowledge.mark_sync_failed("Graph 503")

    assert knowledge.last_sync_status == "error"
    assert knowledge.last_sync_error == "Graph 503"
    assert knowledge.last_sync_attempted_at == started
    assert knowledge.last_synced_at is None
