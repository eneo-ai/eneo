"""SQL for searching and ordering a run history.

The search reads only metadata a run list already shows: the run label and
the starter's name, through the naming columns `FlowRunStarterRepository`
reads. Accepted input, output and evidence are never part of it.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from eneo.authentication.principal_types import PrincipalType
from eneo.database.tables.flow_tables import FlowRuns
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.database.tables.users_table import Users
from eneo.flows.domain.flow_run_listing import FlowRunListing
from eneo.flows.enums import FLOW_RUN_STATUS_FILTER_ORDER


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def run_search_clause(search: str) -> sa.ColumnElement[bool]:
    """Runs whose label or starter's name contains ``search``, ignoring case.

    A starter is matched only inside the run's own tenant, as the list names
    them."""
    pattern = _like_pattern(search)
    starter_user = (
        sa.select(Users.id)
        .where(Users.id == FlowRuns.principal_user_id)
        .where(Users.tenant_id == FlowRuns.tenant_id)
        .where(
            sa.or_(
                Users.username.ilike(pattern, escape="\\"),
                Users.email.ilike(pattern, escape="\\"),
            )
        )
        .exists()
    )
    starter_service = (
        sa.select(ServicePrincipals.id)
        .where(ServicePrincipals.id == FlowRuns.principal_service_id)
        .where(ServicePrincipals.tenant_id == FlowRuns.tenant_id)
        .where(ServicePrincipals.display_name.ilike(pattern, escape="\\"))
        .exists()
    )
    return sa.or_(
        FlowRuns.run_label.ilike(pattern, escape="\\"),
        sa.and_(FlowRuns.principal_type == PrincipalType.USER.value, starter_user),
        sa.and_(
            FlowRuns.principal_type == PrincipalType.SERVICE_KEY.value,
            starter_service,
        ),
    )


_STATUS_POSITION = sa.case(
    {
        status.value: position
        for position, status in enumerate(FLOW_RUN_STATUS_FILTER_ORDER)
    },
    value=FlowRuns.status,
    else_=len(FLOW_RUN_STATUS_FILTER_ORDER),
)


def run_list_order(listing: FlowRunListing) -> tuple[Any, ...]:
    """The ORDER BY of a run list. Every order ends on creation time and id,
    so a page boundary never splits or repeats a run."""
    descending = listing.order == "desc"

    def directed(column: Any) -> Any:
        return column.desc() if descending else column.asc()

    newest_first = (FlowRuns.created_at.desc(), FlowRuns.id.desc())
    if listing.sort == "started_at":
        started = sa.func.coalesce(FlowRuns.started_at, FlowRuns.created_at)
        return (
            directed(started),
            directed(FlowRuns.created_at),
            directed(FlowRuns.id),
        )
    if listing.sort == "status":
        return (directed(_STATUS_POSITION), *newest_first)
    if listing.sort == "duration":
        duration = FlowRuns.finished_at - sa.func.coalesce(
            FlowRuns.started_at, FlowRuns.created_at
        )
        return (directed(duration).nulls_last(), *newest_first)
    return (directed(FlowRuns.created_at), directed(FlowRuns.id))
