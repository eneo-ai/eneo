"""Who started each run, named for the callers allowed to see that run."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.api.flow_models import FlowRunStartedByPublic
from eneo.flows.domain.flow import FlowRunStatusSnapshot
from eneo.flows.infrastructure.flow_run_starter_repo import (
    FlowRunStarterRepository,
    FlowRunStarterServicePrincipal,
    FlowRunStarterUser,
)
from eneo.flows.principal import FlowPrincipal

if TYPE_CHECKING:
    from eneo.main.container.container import Container


@dataclass(frozen=True, slots=True)
class FlowRunStartedByPresenter:
    """Names the starter of runs the caller has already been allowed to see.

    The run access policy decides which runs a caller sees; this only reads
    names for those runs, inside the caller's tenant. A service key is only
    ever given its own name, even if it were handed a run it did not start.
    """

    repo: FlowRunStarterRepository
    tenant_id: UUID
    caller: FlowPrincipal

    @classmethod
    def from_container(cls, container: "Container") -> "FlowRunStartedByPresenter":
        user = container.user()
        return cls(
            repo=container.flow_run_starter_repo(),
            tenant_id=user.tenant_id,
            caller=FlowPrincipal.from_user(user),
        )

    async def for_runs(
        self, runs: Iterable[FlowRunStatusSnapshot]
    ) -> dict[UUID, FlowRunStartedByPublic]:
        visible = [run for run in runs if self._may_name(run)]
        users = await self.repo.list_users(
            tenant_id=self.tenant_id,
            user_ids=(
                run.principal_user_id
                for run in visible
                if run.principal_type == PrincipalType.USER
                and run.principal_user_id is not None
            ),
        )
        service_principals = await self.repo.list_service_principals(
            tenant_id=self.tenant_id,
            service_principal_ids=(
                run.principal_service_id
                for run in visible
                if run.principal_type == PrincipalType.SERVICE_KEY
                and run.principal_service_id is not None
            ),
        )
        started_by: dict[UUID, FlowRunStartedByPublic] = {}
        for run in visible:
            public = _started_by(
                run, users=users, service_principals=service_principals
            )
            if public is not None:
                started_by[run.id] = public
        return started_by

    async def for_run(
        self, run: FlowRunStatusSnapshot
    ) -> FlowRunStartedByPublic | None:
        return (await self.for_runs((run,))).get(run.id)

    def _may_name(self, run: FlowRunStatusSnapshot) -> bool:
        if run.tenant_id != self.tenant_id:
            return False
        if self.caller.is_service_key:
            return self.caller.matches_run(run)
        return True


def _started_by(
    run: FlowRunStatusSnapshot,
    *,
    users: dict[UUID, FlowRunStarterUser],
    service_principals: dict[UUID, FlowRunStarterServicePrincipal],
) -> FlowRunStartedByPublic | None:
    if run.principal_type == PrincipalType.USER and run.principal_user_id is not None:
        user = users.get(run.principal_user_id)
        username = user.username.strip() if user and user.username else ""
        return FlowRunStartedByPublic(
            principal_type=PrincipalType.USER,
            id=run.principal_user_id,
            display_name=(username or user.email) if user else None,
            email=user.email if user else None,
        )
    if (
        run.principal_type == PrincipalType.SERVICE_KEY
        and run.principal_service_id is not None
    ):
        service_principal = service_principals.get(run.principal_service_id)
        return FlowRunStartedByPublic(
            principal_type=PrincipalType.SERVICE_KEY,
            id=run.principal_service_id,
            display_name=(
                service_principal.display_name if service_principal else None
            ),
        )
    return None


async def started_by_for_runs(
    container: "Container", runs: Sequence[FlowRunStatusSnapshot]
) -> dict[UUID, FlowRunStartedByPublic]:
    return await FlowRunStartedByPresenter.from_container(container).for_runs(runs)


async def started_by_for_run(
    container: "Container", run: FlowRunStatusSnapshot
) -> FlowRunStartedByPublic | None:
    return await FlowRunStartedByPresenter.from_container(container).for_run(run)
