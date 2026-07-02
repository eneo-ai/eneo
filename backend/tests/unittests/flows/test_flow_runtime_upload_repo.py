from __future__ import annotations

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from eneo.flows.principal import FlowPrincipal


@pytest.mark.asyncio
async def test_list_bound_file_ids_for_owner_can_lock_rows_for_binding() -> None:
    file_id = uuid4()
    session = AsyncMock()
    session.in_transaction = Mock(return_value=True)
    session.scalars.return_value = [file_id]
    repo = FlowRuntimeUploadRepository(session=session)

    result = await repo.list_bound_file_ids_for_owner(
        file_ids=[file_id],
        flow_id=uuid4(),
        tenant_id=uuid4(),
        principal=FlowPrincipal(
            principal_type=PrincipalType.USER,
            principal_user_id=uuid4(),
        ),
        lock_for_binding=True,
    )

    assert result == {file_id}
    stmt = session.scalars.await_args.args[0]
    compiled = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "FOR KEY SHARE OF flow_runtime_uploaded_files" in compiled


@pytest.mark.asyncio
async def test_list_bound_file_ids_for_owner_requires_transaction_for_binding_lock() -> (
    None
):
    session = AsyncMock()
    session.in_transaction = Mock(return_value=False)
    repo = FlowRuntimeUploadRepository(session=session)

    with pytest.raises(RuntimeError, match="active transaction"):
        await repo.list_bound_file_ids_for_owner(
            file_ids=[uuid4()],
            flow_id=uuid4(),
            tenant_id=uuid4(),
            principal=FlowPrincipal(
                principal_type=PrincipalType.USER,
                principal_user_id=uuid4(),
            ),
            lock_for_binding=True,
        )

    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_bound_file_ids_for_owner_skips_lock_by_default() -> None:
    session = AsyncMock()
    session.scalars.return_value = []
    repo = FlowRuntimeUploadRepository(session=session)

    await repo.list_bound_file_ids_for_owner(
        file_ids=[uuid4()],
        flow_id=uuid4(),
        tenant_id=uuid4(),
        principal=FlowPrincipal(
            principal_type=PrincipalType.SERVICE_KEY,
            principal_service_id=uuid4(),
        ),
    )

    stmt = session.scalars.await_args.args[0]
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR SHARE" not in compiled
    assert "FOR KEY SHARE" not in compiled
