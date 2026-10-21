from typing import Annotated, cast

from fastapi import Depends

from eneo.database.database import AsyncSession
from eneo.flows.application.feature_gate import require_flows_enabled
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container


async def require_flow_feature(
    # Its own session, whose authentication commits before the route's runs:
    # authenticating can write (a legacy key hash is upgraded on first use),
    # and a write held open here would block the route authenticating the
    # same key in its own session.
    container: Annotated[
        Container,
        Depends(
            get_container(with_user=True, with_module_user=True, with_transaction=False)
        ),
    ],
) -> None:
    async with cast(AsyncSession, container.session()).begin():
        await require_flows_enabled(
            container.feature_flag_service(), container.user().tenant_id
        )
