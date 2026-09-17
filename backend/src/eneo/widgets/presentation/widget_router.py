# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.widgets.application.widget_service import WidgetView
from eneo.widgets.presentation.widget_models import (
    WidgetCreate,
    WidgetPolicyPublic,
    WidgetPolicyUpdate,
    WidgetPreviewToken,
    WidgetPublic,
    WidgetUpdate,
    WidgetUsageDayPublic,
    WidgetUsagePublic,
)

# Mounted under /spaces, /widgets and /admin/widget-policy respectively.
space_widgets_router = APIRouter()
router = APIRouter()
policy_router = APIRouter()

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]


def _widget_snapshot(view: WidgetView) -> dict[str, Any]:
    widget = view.widget
    return {
        "status": widget.status.value,
        "token_generation": widget.token_generation,
        "allowed_origins": list(widget.allowed_origins),
        "limits": widget.limits.model_dump(mode="json"),
        "privacy": widget.privacy.model_dump(mode="json"),
        "bot_protection": widget.bot_protection.value,
    }


async def _audit(
    container: Container,
    *,
    action: ActionType,
    view: WidgetView,
    description: str,
    changes: dict[str, Any] | None = None,
) -> None:
    user = container.user()
    widget = view.widget
    assert widget.id is not None
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.WIDGET,
        entity_id=widget.id,
        description=description,
        metadata=AuditMetadata.standard(
            actor=user,
            target=widget,
            changes=changes,
            extra={"public_id": widget.public_id, "space_id": str(widget.space_id)},
        ),
    )


@space_widgets_router.get(
    "/{space_id}/widgets/",
    response_model=PaginatedResponse[WidgetPublic],
    description="List the widgets configured in a space.",
    responses=responses.get_responses([403, 404]),
)
async def list_space_widgets(space_id: UUID, container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    views = await service.list_widgets(space_id)
    return protocol.to_paginated_response([assembler.from_view(v) for v in views])


@space_widgets_router.post(
    "/{space_id}/widgets/",
    response_model=WidgetPublic,
    status_code=201,
    description=(
        "Create a widget draft for an assistant in the space. Requires the"
        " `widgets` permission and edit rights in the space; activation is a"
        " separate tenant-admin step."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
async def create_space_widget(
    space_id: UUID, body: WidgetCreate, container: _ContainerWithUser
):
    service = container.widget_service()
    assembler = container.widget_assembler()
    view = await service.create_widget(
        space_id=space_id,
        target_id=body.target_id,
        name=body.name,
        language=body.language,
    )
    await _audit(
        container,
        action=ActionType.WIDGET_CREATED,
        view=view,
        description=f"Created widget '{view.widget.name}'",
        changes={"new": _widget_snapshot(view)},
    )
    return assembler.from_view(view)


@router.get(
    "/{id}/",
    response_model=WidgetPublic,
    description="Get a widget's configuration and activation state.",
    responses=responses.get_responses([403, 404]),
)
async def get_widget(id: UUID, container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    return assembler.from_view(await service.get_widget(id))


@router.patch(
    "/{id}/",
    response_model=WidgetPublic,
    description=(
        "Update a widget's configuration. Changes to allowed origins, limits,"
        " privacy or bot protection invalidate outstanding visitor tokens."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
async def update_widget(id: UUID, body: WidgetUpdate, container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    before = await service.get_widget(id)
    changes = body.model_dump(exclude_unset=True)
    view = await service.update_widget(id, changes)
    await _audit(
        container,
        action=ActionType.WIDGET_UPDATED,
        view=view,
        description=f"Updated widget '{view.widget.name}'",
        changes={
            "fields": sorted(changes),
            "old": _widget_snapshot(before),
            "new": _widget_snapshot(view),
        },
    )
    return assembler.from_view(view)


@router.get(
    "/{id}/usage/",
    response_model=WidgetUsagePublic,
    description="Daily usage for a widget: questions, tokens and blocked requests.",
    responses=responses.get_responses([403, 404]),
)
async def get_widget_usage(
    id: UUID,
    container: _ContainerWithUser,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
):
    service = container.widget_service()
    view = await service.get_widget(id)
    assert view.widget.id is not None
    rows = await container.widget_usage_repo().list_days(view.widget.id, days=days)
    used_today = await container.widget_budget().used_today(view.widget)
    return WidgetUsagePublic(
        days=[
            WidgetUsageDayPublic(
                day=row.day,
                questions=row.questions,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                blocked_budget=row.blocked_budget,
                blocked_rate=row.blocked_rate,
            )
            for row in rows
        ],
        budget_used_today=used_today,
        daily_token_budget=view.widget.limits.daily_token_budget,
    )


@router.post(
    "/{id}/preview-token/",
    response_model=WidgetPreviewToken,
    description=(
        "Mint a visitor token for the live preview on the admin page. Admits"
        " the embed page for draft and paused widgets; each call is a fresh"
        " pseudonymous visitor."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
async def create_widget_preview_token(id: UUID, container: _ContainerWithUser):
    service = container.widget_service()
    view = await service.get_widget(id)
    token, expires_in = await service.preview_token(id)
    return WidgetPreviewToken(
        token=token, expires_in=expires_in, public_id=view.widget.public_id
    )


@router.post(
    "/{id}/activate/",
    response_model=WidgetPublic,
    description=(
        "Activate a widget so it serves visitors. Tenant admins only; fails"
        " with the list of blockers when the configuration is incomplete."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
async def activate_widget(id: UUID, container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    view = await service.activate_widget(id)
    await _audit(
        container,
        action=ActionType.WIDGET_ACTIVATED,
        view=view,
        description=f"Activated widget '{view.widget.name}'",
        changes={"new": _widget_snapshot(view)},
    )
    return assembler.from_view(view)


@router.post(
    "/{id}/pause/",
    response_model=WidgetPublic,
    description=(
        "Pause a widget immediately. Visitors get a paused notice and existing"
        " visitor tokens stop validating."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
async def pause_widget(id: UUID, container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    view = await service.pause_widget(id)
    await _audit(
        container,
        action=ActionType.WIDGET_PAUSED,
        view=view,
        description=f"Paused widget '{view.widget.name}'",
        changes={"new": _widget_snapshot(view)},
    )
    return assembler.from_view(view)


@router.post(
    "/{id}/archive/",
    response_model=WidgetPublic,
    description="Archive a widget permanently. Tenant admins only.",
    responses=responses.get_responses([400, 403, 404]),
)
async def archive_widget(id: UUID, container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    view = await service.archive_widget(id)
    await _audit(
        container,
        action=ActionType.WIDGET_ARCHIVED,
        view=view,
        description=f"Archived widget '{view.widget.name}'",
        changes={"new": _widget_snapshot(view)},
    )
    return assembler.from_view(view)


@policy_router.get(
    "/",
    response_model=WidgetPolicyPublic,
    description="Get the tenant's widget policy (defaults apply when unset).",
    responses=responses.get_responses([403]),
)
async def get_widget_policy(container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    return assembler.from_policy(service.read_policy())


@policy_router.patch(
    "/",
    response_model=WidgetPolicyPublic,
    description="Update the tenant's widget policy guardrails.",
    responses=responses.get_responses([400, 403]),
)
async def update_widget_policy(body: WidgetPolicyUpdate, container: _ContainerWithUser):
    service = container.widget_service()
    assembler = container.widget_assembler()
    user = container.user()
    before = service.read_policy()
    policy = await service.update_policy(body.model_dump(exclude_unset=True))
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.WIDGET_POLICY_UPDATED,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description="Updated tenant widget policy",
        metadata=AuditMetadata.standard(
            actor=user,
            target=user.tenant,
            changes={
                "widget_policy": {
                    "old": before.model_dump(mode="json"),
                    "new": policy.model_dump(mode="json"),
                }
            },
        ),
    )
    return assembler.from_policy(policy)
