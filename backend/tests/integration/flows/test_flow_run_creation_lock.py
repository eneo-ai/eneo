"""Run creation beside the locks on the rows a run points to.

Every insert that references a row checks its foreign key with FOR KEY SHARE
on that row. A lock taken FOR UPDATE makes such inserts wait for it to commit;
FOR NO KEY UPDATE does not.

- The tenant's run-creation lock excludes only the next creation.
- A change that keeps a service key's row (a rename) does not hold back a run
  that the key starts: the run records the key in `created_by_api_key_id`.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyUpdateRequest,
)
from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.flow_tables import FlowRuns, Flows
from eneo.flows.domain.flow import FlowRun
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from tests.integration.fixtures.locks import settle, waits_for
from tests.integration.flows.test_flow_run_publication_locking import (
    _create_published_flow_with_two_versions,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _times_out(statement) -> bool:
    try:
        await statement
    except DBAPIError as exc:
        if "lock timeout" in str(exc):
            return True
        raise
    return False


async def test_a_run_creation_lock_excludes_the_next_creation_only(
    setup_database, admin_user
) -> None:
    tenant_id = admin_user.tenant_id
    async with sessionmanager.session() as holder, holder.begin():
        await FlowRunRepository(session=holder).acquire_tenant_run_creation_lock(
            tenant_id=tenant_id
        )

        async with sessionmanager.session() as other, other.begin():
            await other.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
            # A write that references the tenant goes ahead.
            await other.execute(
                sa.text(
                    "INSERT INTO roles (name, permissions, tenant_id) "
                    "VALUES ('run-creation-lock-probe', '{}', :tenant_id)"
                ),
                {"tenant_id": tenant_id},
            )
            await other.rollback()

        async with sessionmanager.session() as other, other.begin():
            await other.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
            # The next run creation waits for this one.
            assert await _times_out(
                FlowRunRepository(session=other).acquire_tenant_run_creation_lock(
                    tenant_id=tenant_id
                )
            )


async def _service_key(db_container, tenant_id: UUID) -> tuple[UUID, UUID]:
    """A service key that may start runs, and its service principal."""
    async with db_container() as container:
        repo = container.api_key_v2_repo()
        principal = await repo.create_service_principal(
            tenant_id=tenant_id,
            display_name="flow runner",
            description=None,
            scope_type=ApiKeyScopeType.TENANT.value,
            scope_id=None,
            created_by_user_id=None,
        )
        key = await repo.create(
            tenant_id=tenant_id,
            service_principal_id=principal.id,
            ownership=ApiKeyOwnership.SERVICE.value,
            scope_type=ApiKeyScopeType.TENANT.value,
            permission=ApiKeyPermission.WRITE.value,
            key_type=ApiKeyType.SK.value,
            key_hash=uuid4().hex,
            hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
            key_prefix=ApiKeyType.SK.value,
            key_suffix=uuid4().hex[-8:],
            name="flow runner",
            state=ApiKeyState.ACTIVE.value,
        )
        return principal.id, key.id


async def _start_run(
    db_container,
    *,
    flow_id: UUID,
    flow_version: int,
    principal_id: UUID,
    key_id: UUID,
    tenant_id: UUID,
    pid: asyncio.Future[int],
) -> FlowRun:
    """Create and commit a run the service key starts, as run creation does
    for the key's request."""
    async with db_container() as container:
        pid.set_result(
            await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
        )
        return await container.flow_run_repo().create(
            flow_id=flow_id,
            flow_version=flow_version,
            principal_type=PrincipalType.SERVICE_KEY.value,
            principal_service_id=principal_id,
            created_by_api_key_id=key_id,
            runtime_service_permission=ApiKeyPermission.WRITE,
            tenant_id=tenant_id,
            input_payload_json={"question": "started during a rename"},
            preseed_steps=[],
        )


async def test_a_run_is_started_while_its_service_key_is_renamed(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    tenant_id = admin_user.tenant_id
    async with db_container() as setup:
        flow_id = await _create_published_flow_with_two_versions(
            container=setup,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        flow_version = await setup.session().scalar(
            sa.select(Flows.published_version).where(Flows.id == flow_id)
        )
    assert flow_version is not None
    principal_id, key_id = await _service_key(db_container, tenant_id)

    pid = asyncio.get_running_loop().create_future()
    starting: asyncio.Task[FlowRun] | None = None
    try:
        async with db_container() as renaming:
            await renaming.api_key_lifecycle_service().update_key(
                key_id=key_id, request=ApiKeyUpdateRequest(name="renamed runner")
            )
            starting = asyncio.create_task(
                _start_run(
                    db_container,
                    flow_id=flow_id,
                    flow_version=flow_version,
                    principal_id=principal_id,
                    key_id=key_id,
                    tenant_id=tenant_id,
                    pid=pid,
                )
            )
            assert not await waits_for(renaming.session(), starting, pid), (
                "the run waits for the rename of its key"
            )
            run = starting.result()
            async with db_container() as reader:
                started_by = await reader.session().scalar(
                    sa.select(FlowRuns.created_by_api_key_id).where(
                        FlowRuns.id == run.id
                    )
                )
            assert started_by == key_id
    finally:
        # A failure releases the rename first, so the run can finish.
        if starting is not None:
            await settle(starting)

    async with db_container() as reader:
        name = await reader.session().scalar(
            sa.select(ApiKeysV2.name).where(ApiKeysV2.id == key_id)
        )
    assert name == "renamed runner"
