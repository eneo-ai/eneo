from typing import Annotated

from fastapi import Depends

from eneo.flows.application.feature_gate import require_flows_enabled
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container


async def require_flow_feature(
    container: Annotated[
        Container, Depends(get_container(with_user=True, with_module_user=True))
    ],
) -> None:
    await require_flows_enabled(
        container.feature_flag_service(), container.user().tenant_id
    )
