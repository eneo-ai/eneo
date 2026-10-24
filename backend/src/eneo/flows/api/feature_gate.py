from fastapi import Request

from eneo.flows.application.feature_gate import require_flows_enabled
from eneo.main.container.container import Container
from eneo.server.dependencies.container import add_request_gate
from eneo.users.user import UserInDB


async def _flows_enabled(container: Container, user: UserInDB) -> None:
    await require_flows_enabled(container.feature_flag_service(), user.tenant_id)


async def require_flow_feature(request: Request) -> None:
    # The route's own authentication runs the gate once the user is known, in
    # its transaction, so a tenant without flows is refused after the
    # credentials and the API key guards and before the request body.
    add_request_gate(request, _flows_enabled)
