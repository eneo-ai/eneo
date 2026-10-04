"""Flow, flow-managed assistant and template file deletion are audited in the deleting transaction.

A deletion commits only together with its audit row: when the audit insert fails the
deletion rolls back, and a successful deletion has its row without any worker, also
when configurable audit logging is switched off.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa

from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.flow_tables import Flows, FlowTemplateAssets
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
)
from tests.integration.flows.test_flow_template_attachment_persistence import (
    _create_template_download_fixture,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@dataclass(frozen=True)
class Deletion:
    path: str
    token: str
    action: ActionType
    entity_id: UUID
    actor_id: UUID
    still_present: Callable[[], Awaitable[bool]]


async def _flow_with_assistant(client, db_container, admin_user):
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id, name="Att radera", description=None, steps=[]
        )
        assistant, _ = await service.create_flow_assistant(
            flow_id=flow.id, name="hjälpare"
        )
    return token, flow.id, assistant.id


def _row_present(db_container, query: Any) -> Callable[[], Awaitable[bool]]:
    async def present() -> bool:
        async with db_container() as container:
            return await container.session().scalar(query) is not None

    return present


async def _flow_deletion(client, db_container, admin_user) -> Deletion:
    token, flow_id, _assistant_id = await _flow_with_assistant(
        client, db_container, admin_user
    )
    return Deletion(
        path=f"/api/v1/flows/{flow_id}/",
        token=token,
        action=ActionType.FLOW_DELETED,
        entity_id=flow_id,
        actor_id=admin_user.id,
        still_present=_row_present(
            db_container,
            sa.select(Flows.id).where(Flows.id == flow_id, Flows.deleted_at.is_(None)),
        ),
    )


async def _assistant_deletion(client, db_container, admin_user) -> Deletion:
    token, flow_id, assistant_id = await _flow_with_assistant(
        client, db_container, admin_user
    )
    return Deletion(
        path=f"/api/v1/flows/{flow_id}/assistants/{assistant_id}/",
        token=token,
        action=ActionType.ASSISTANT_DELETED,
        entity_id=assistant_id,
        actor_id=admin_user.id,
        still_present=_row_present(
            db_container, sa.select(Assistants.id).where(Assistants.id == assistant_id)
        ),
    )


async def _template_file_deletion(client, db_container, admin_user) -> Deletion:
    (
        token,
        flow_id,
        asset_id,
        file_id,
        user_id,
        _tenant_id,
    ) = await _create_template_download_fixture(db_container)
    return Deletion(
        path=f"/api/v1/flows/{flow_id}/template-files/{asset_id}/",
        token=token,
        action=ActionType.FILE_DELETED,
        entity_id=file_id,
        actor_id=user_id,
        still_present=_row_present(
            db_container,
            sa.select(FlowTemplateAssets.id).where(
                FlowTemplateAssets.id == asset_id,
                FlowTemplateAssets.deleted_at.is_(None),
            ),
        ),
    )


_DELETIONS = {
    "flow": _flow_deletion,
    "flow_assistant": _assistant_deletion,
    "template_file": _template_file_deletion,
}


@asynccontextmanager
async def _audit_insert_refused(
    db_container, action: ActionType
) -> AsyncIterator[None]:
    async with db_container() as container:
        await container.session().execute(
            sa.text(
                "CREATE OR REPLACE FUNCTION s2a_refuse_audit_insert() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "RAISE EXCEPTION 'audit insert refused for test'; END $$"
            )
        )
        await container.session().execute(
            sa.text(
                "CREATE TRIGGER s2a_refuse_audit_insert BEFORE INSERT ON audit_logs "
                f"FOR EACH ROW WHEN (NEW.action = '{action.value}') "
                "EXECUTE FUNCTION s2a_refuse_audit_insert()"
            )
        )
    try:
        yield
    finally:
        async with db_container() as container:
            await container.session().execute(
                sa.text("DROP TRIGGER IF EXISTS s2a_refuse_audit_insert ON audit_logs")
            )
            await container.session().execute(
                sa.text("DROP FUNCTION IF EXISTS s2a_refuse_audit_insert()")
            )


async def _audit_rows(db_container, deletion: Deletion) -> list[Any]:
    async with db_container() as container:
        return list(
            (
                await container.session().execute(
                    sa.select(AuditLogTable.actor_id, AuditLogTable.log_metadata).where(
                        AuditLogTable.action == deletion.action.value,
                        AuditLogTable.entity_id == deletion.entity_id,
                    )
                )
            ).all()
        )


@asynccontextmanager
async def _configurable_audit_switched_off(db_container) -> AsyncIterator[None]:
    statement = "UPDATE global_feature_flags SET enabled = :enabled WHERE name = :name"
    params = {"name": "audit_logging_enabled"}
    async with db_container() as container:
        await container.session().execute(
            sa.text(statement), {**params, "enabled": False}
        )
    try:
        yield
    finally:
        async with db_container() as container:
            await container.session().execute(
                sa.text(statement), {**params, "enabled": True}
            )


@pytest.mark.parametrize("kind", sorted(_DELETIONS))
async def test_a_deletion_commits_with_its_audit_row_and_no_worker(
    client, db_container, admin_user, patch_auth_service_jwt, kind
):
    deletion = await _DELETIONS[kind](client, db_container, admin_user)

    async with _configurable_audit_switched_off(db_container):
        response = await client.delete(
            deletion.path, headers={"Authorization": f"Bearer {deletion.token}"}
        )

    assert response.status_code == 204, response.text
    assert not await deletion.still_present()
    rows = await _audit_rows(db_container, deletion)
    assert [row.actor_id for row in rows] == [deletion.actor_id]
    assert rows[0].log_metadata["actor"]["id"] == str(deletion.actor_id)


@pytest.mark.parametrize("kind", sorted(_DELETIONS))
async def test_a_deletion_whose_audit_row_cannot_be_written_is_rolled_back(
    client, db_container, admin_user, patch_auth_service_jwt, kind
):
    deletion = await _DELETIONS[kind](client, db_container, admin_user)

    async with _audit_insert_refused(db_container, deletion.action):
        with pytest.raises(Exception, match="audit insert refused for test"):
            await client.delete(
                deletion.path, headers={"Authorization": f"Bearer {deletion.token}"}
            )

    assert await deletion.still_present()
    assert await _audit_rows(db_container, deletion) == []
