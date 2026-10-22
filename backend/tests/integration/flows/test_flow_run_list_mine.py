"""`GET /api/v1/flows/{id}/runs/` narrows the run list to the caller's own
runs with `mine=true`, searches run labels and starter names, orders by start
time, status or duration, and counts the listed runs by status, all inside the
caller's run visibility."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.flow_tables import FlowRuns
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceRoleValue
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
    newest_admin_run_id: str
    colleague_run_id: str
    oldest_admin_run_id: str

    @property
    def all_run_ids(self) -> list[str]:
        """Newest first, as the list orders them: the colleague's run sits
        between the admin's, so paging over the admin's runs has to skip it
        inside the query."""
        return [
            self.newest_admin_run_id,
            self.colleague_run_id,
            self.oldest_admin_run_id,
        ]

    @property
    def admin_run_ids(self) -> list[str]:
        return [self.newest_admin_run_id, self.oldest_admin_run_id]


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
        session = container.session()
        colleague = await user_factory(
            session, username="Kim Colleague", email="kim.colleague@example.com"
        )
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

        oldest_admin_run = await run_by(admin_user.id)
        colleague_run = await run_by(colleague_id)
        newest_admin_run = await run_by(admin_user.id)
        # Inserts in one transaction share now(), so each run gets its own
        # created_at; otherwise the id tie-break would decide the order.
        started = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
        for minutes, run_id in enumerate(
            (oldest_admin_run, colleague_run, newest_admin_run)
        ):
            await session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == UUID(run_id))
                .values(created_at=started + timedelta(minutes=minutes))
            )
        # The oldest run took ten minutes, the colleague's one; the newest
        # waits in the queue, so it has neither a start nor a duration.
        for run_id, values in (
            (
                oldest_admin_run,
                {
                    "run_label": "Case 100% done",
                    "status": "completed",
                    "started_at": started,
                    "finished_at": started + timedelta(minutes=10),
                },
            ),
            (
                colleague_run,
                {
                    "status": "failed",
                    "started_at": started + timedelta(minutes=1),
                    "finished_at": started + timedelta(minutes=2),
                },
            ),
            (newest_admin_run, {"run_label": "case 7"}),
        ):
            await session.execute(
                sa.update(FlowRuns).where(FlowRuns.id == UUID(run_id)).values(**values)
            )
    return RunHistory(
        admin_token=flow_process_auth_headers.token,
        runs_path=f"/api/v1/flows/{flow.flow_id}/runs/",
        newest_admin_run_id=newest_admin_run,
        colleague_run_id=colleague_run,
        oldest_admin_run_id=oldest_admin_run,
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

    assert _ids(await _runs(client, history, headers)) == history.all_run_ids
    assert _ids(await _runs(client, history, headers, mine=True)) == (
        history.admin_run_ids
    )
    pages = [
        await _runs(client, history, headers, mine=True, limit=1, offset=offset)
        for offset in (0, 1)
    ]
    assert [page["has_more"] for page in pages] == [True, False]
    assert [_ids(page) for page in pages] == [
        [history.newest_admin_run_id],
        [history.oldest_admin_run_id],
    ]


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

    assert _ids(await _runs(client, history, headers)) == history.all_run_ids
    assert _ids(await _runs(client, history, headers, mine=True)) == (
        history.admin_run_ids
    )


async def test_search_matches_run_labels_and_starter_names_ignoring_case(
    client: AsyncClient, history: RunHistory
):
    headers = {"Authorization": f"Bearer {history.admin_token}"}

    assert _ids(await _runs(client, history, headers, search="CASE")) == (
        history.admin_run_ids
    )
    assert _ids(await _runs(client, history, headers, search=" kim colleague ")) == [
        history.colleague_run_id
    ]
    assert _ids(await _runs(client, history, headers, search="kim.colleague@")) == [
        history.colleague_run_id
    ]
    # Wildcards are literal text.
    assert _ids(await _runs(client, history, headers, search="100%")) == [
        history.oldest_admin_run_id
    ]
    assert _ids(await _runs(client, history, headers, search="1_0")) == []
    assert _ids(await _runs(client, history, headers, search="   ")) == (
        history.all_run_ids
    )


async def test_search_never_reads_run_content(
    client: AsyncClient, history: RunHistory, db_container
):
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == UUID(history.colleague_run_id))
            .values(input_payload_json={"note": "secret needle"})
        )
    headers = {"Authorization": f"Bearer {history.admin_token}"}

    assert _ids(await _runs(client, history, headers, search="needle")) == []


async def test_runs_sort_by_start_time_status_and_duration(
    client: AsyncClient, history: RunHistory
):
    headers = {"Authorization": f"Bearer {history.admin_token}"}

    # The queued run has not started, so its creation time stands in.
    assert _ids(await _runs(client, history, headers, sort="started_at")) == (
        history.all_run_ids
    )
    assert _ids(
        await _runs(client, history, headers, sort="started_at", order="asc")
    ) == list(reversed(history.all_run_ids))
    # Status follows the capability table's filter order: completed, failed, ..., queued.
    assert _ids(await _runs(client, history, headers, sort="status", order="asc")) == [
        history.oldest_admin_run_id,
        history.colleague_run_id,
        history.newest_admin_run_id,
    ]
    # A run that has not finished comes last in both directions.
    assert _ids(await _runs(client, history, headers, sort="duration")) == [
        history.oldest_admin_run_id,
        history.colleague_run_id,
        history.newest_admin_run_id,
    ]
    assert _ids(
        await _runs(client, history, headers, sort="duration", order="asc")
    ) == [
        history.colleague_run_id,
        history.oldest_admin_run_id,
        history.newest_admin_run_id,
    ]
    pages = [
        await _runs(client, history, headers, sort="duration", limit=1, offset=offset)
        for offset in (0, 1, 2)
    ]
    assert [_ids(page) for page in pages] == [
        [history.oldest_admin_run_id],
        [history.colleague_run_id],
        [history.newest_admin_run_id],
    ]


async def test_status_counts_cover_every_listed_run_without_the_status_filter(
    client: AsyncClient, history: RunHistory
):
    headers = {"Authorization": f"Bearer {history.admin_token}"}
    zero = dict.fromkeys(
        ("queued", "running", "awaiting_review", "completed", "failed", "cancelled"),
        0,
    )

    page = await _runs(client, history, headers, status="failed", limit=1)
    assert _ids(page) == [history.colleague_run_id]
    assert page["status_counts"] == {**zero, "queued": 1, "completed": 1, "failed": 1}
    assert (await _runs(client, history, headers, mine=True))["status_counts"] == {
        **zero,
        "queued": 1,
        "completed": 1,
    }
    assert (await _runs(client, history, headers, search="kim"))["status_counts"] == {
        **zero,
        "failed": 1,
    }


async def test_a_member_lists_searches_and_counts_only_their_own_runs(
    client: AsyncClient, history: RunHistory, db_container, admin_user
):
    async with db_container() as container:
        colleague = await container.user_repo().get_user_by_email(
            "kim.colleague@example.com"
        )
        session = container.session()
        role = Roles(
            name=f"Flow runner {uuid4().hex[:8]}",
            permissions=[Permission.FLOWS.value, Permission.FLOWS_RUN.value],
            tenant_id=admin_user.tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            sa.insert(users_roles_table).values(user_id=colleague.id, role_id=role.id)
        )
        flow_id = UUID(history.runs_path.split("/")[4])
        flow = await container.flow_repo().get(flow_id, admin_user.tenant_id)
        session.add(
            SpacesUsers(
                space_id=flow.space_id,
                user_id=colleague.id,
                role=SpaceRoleValue.EDITOR,
            )
        )
        await session.flush()
        colleague = await container.user_repo().get_user_by_email(
            "kim.colleague@example.com"
        )
        token = container.auth_service().create_access_token_for_user(colleague)
    headers = {"Authorization": f"Bearer {token}"}

    page = await _runs(client, history, headers, search="case")
    assert _ids(page) == []
    assert sum(page["status_counts"].values()) == 0
    page = await _runs(client, history, headers)
    assert _ids(page) == [history.colleague_run_id]
    assert page["status_counts"]["failed"] == 1
    assert sum(page["status_counts"].values()) == 1
