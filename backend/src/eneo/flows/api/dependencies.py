"""Request guards for the flows API."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException

from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container

FLOWS_FEATURE_FLAG = "flows_core"


async def require_flows_enabled(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> None:
    """Answer 404 unless the tenant has the ``flows_core`` feature enabled.

    A disabled feature looks like a missing route, so a tenant that was never
    told about flows cannot discover them by probing.
    """
    user = container.user()
    enabled = await container.feature_flag_service().check_is_feature_enabled(
        FLOWS_FEATURE_FLAG, user.tenant_id
    )
    if not enabled:
        raise HTTPException(status_code=404, detail="Not Found")
