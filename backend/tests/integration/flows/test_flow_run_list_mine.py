"""`GET /api/v1/flows/{id}/runs/?mine=true` narrows the run list to the
caller's own runs inside the caller's run visibility."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from tests.integration.module_session_support import (
    enable_module,
    install_module,
    module_login,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass(frozen=True)
class RunHistory:
    admin_token: str
    runs_path: str
    admin_run_ids: set[str]
    colleague_run_id: str


@pytest.fixture
async def history(
    client,
    db_container,
    admin_user,
    user_factory,
    flow_process_auth_headers,
    create_published_compose_text_flow,
) -> RunHistory:
    flow = await create_published_compose_text_flow(client, flow_process_auth_headers)
    async with db_container() as container:
        colleague = await user_factory(container.session())
        colleague_id = colleague.id
        published = await container.flow_repo().get(
            UUID(flow.flow_id), admin_user.tenant_id
        )
        step = published.steps[0]
        run_repo = container.flow_run_repo()

        async def run_by(principal_user_id: UUID) -> str:
            run = await run_repo.create(
                flow_id=UUID(flow.flow_id),
                flow_version=flow.published_version,
                principal_user_id=principal_user_id,
                tenant_id=admin_user.tenant_id,
                input_payload_json={},
                preseed_steps=[
                    {
                        "step_id": step.id,
                        "assistant_id": step.assistant_id,
                        "step_order": 1,
                    }
                ],
            )
            return str(run.id)

        # The colleague's run lands between the admin's, so paging over the
        # admin's own runs has to skip it inside the query.
        first_admin_run = await run_by(admin_user.id)
        colleague_run = await run_by(colleague_id)
        second_admin_run = await run_by(admin_user.id)
    return RunHistory(
        admin_token=flow_process_auth_headers.token,
        runs_path=f"/api/v1/flows/{flow.flow_id}/runs/",
        admin_run_ids={first_admin_run, second_admin_run},
        colleague_run_id=colleague_run,
    )


async def _runs(
    client: AsyncClient, history: RunHistory, headers: Mapping[str, str], **params: Any
) -> dict[str, Any]:
    response = await client.get(history.runs_path, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(page: dict[str, Any]) -> list[str]:
    return [item["id"] for item in page["items"]]


async def test_mine_narrows_an_admins_run_list_to_their_own_runs(
    client: AsyncClient, history: RunHistory
):
    headers = {"Authorization": f"Bearer {history.admin_token}"}

    everything = await _runs(client, history, headers)
    mine = await _runs(client, history, headers, mine=True)

    assert set(_ids(everything)) == {
        *history.admin_run_ids,
        history.colleague_run_id,
    }
    assert set(_ids(mine)) == history.admin_run_ids
    assert _ids(mine) == [
        run_id for run_id in _ids(everything) if run_id in history.admin_run_ids
    ]
    pages = [
        await _runs(client, history, headers, mine=True, limit=1, offset=offset)
        for offset in (0, 1)
    ]
    assert [page["has_more"] for page in pages] == [True, False]
    assert [run_id for page in pages for run_id in _ids(page)] == _ids(mine)


async def test_a_module_session_lists_the_humans_own_runs_with_mine(
    client: AsyncClient, history: RunHistory, db_container, admin_user
):
    module_key = await enable_module(db_container, tenant_id=admin_user.tenant_id)
    secret = await install_module(
        client, admin_token=history.admin_token, module_key=module_key
    )
    module_token = await module_login(
        client,
        service_key=secret,
        user_token=history.admin_token,
        module_key=module_key,
    )
    headers = {"X-API-Key": secret, "Authorization": f"Bearer {module_token}"}

    assert set(_ids(await _runs(client, history, headers))) == {
        *history.admin_run_ids,
        history.colleague_run_id,
    }
    assert set(_ids(await _runs(client, history, headers, mine=True))) == (
        history.admin_run_ids
    )
