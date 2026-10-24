"""The transcription run the transcript source and words tests start from.

A test module uses the fixture by binding it to a module name:
``source_scenario = transcript_source_support.source_scenario``.
"""

from __future__ import annotations

import pytest

from tests.integration.flows.test_transcript_corrections import _create_scenario


@pytest.fixture
async def source_scenario(
    completion_model_factory, space_factory, assistant_factory, admin_user
):
    from eneo.database.database import sessionmanager
    from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session

    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
            store_source=False,
        )
        yield session, scenario, admin_user
