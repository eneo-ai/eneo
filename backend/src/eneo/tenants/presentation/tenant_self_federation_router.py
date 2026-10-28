"""An org admin's door to their own organisation's IdP settings.

Interactive sessions only (an API key is refused with session_auth_required) and
only the caller's tenant: there is no tenant in the path or the body. The
operator registers the IdP through the super-key routes; this door edits the
label, client ID, secret and allowed domains. TenantFederationService owns the
rules, the lock and the always-on audit.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenants.tenant_federation_service import (
    TenantAdminFederationPatch,
    TenantFederationAdminView,
)


def require_federation_enabled(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.federation_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "federation_disabled",
                "message": "Federation is not enabled on this installation.",
            },
        )


router = APIRouter(dependencies=[Depends(require_federation_enabled)])

_REASON = (
    "Organization administration requires the admin permission in an "
    "interactive session; the service reads and writes only the caller's tenant."
)


@router.get(
    "",
    response_model=TenantFederationAdminView,
    summary="Get the organisation's sign-in settings",
    description=(
        "The identity provider the operator registered for the caller's "
        "organisation. The client secret is never returned, only whether it is "
        "set and when it was last replaced."
    ),
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Permission.ADMIN,
    reason=_REASON,
)
async def get_federation(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> TenantFederationAdminView:
    return container.tenant_federation_service().admin_view(container.user().tenant)


@router.patch(
    "",
    response_model=TenantFederationAdminView,
    summary="Change the organisation's sign-in settings",
    description=(
        "Change the label, client ID, client secret or allowed email domains of "
        "the registered identity provider. Send the revision from GET; a save "
        "against an older revision is refused with 409. Operator-owned fields "
        "are refused with 422. Every change is audited."
    ),
    responses=responses.get_responses([400, 403, 404, 409, 503]),
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Permission.ADMIN,
    reason=_REASON,
)
async def patch_federation(
    patch: TenantAdminFederationPatch,
    container: Annotated[
        Container,
        Depends(get_container(with_user=True, transaction_scope="function")),
    ],
) -> TenantFederationAdminView:
    return await container.tenant_federation_service().edit_as_admin(
        container.user(), patch
    )
