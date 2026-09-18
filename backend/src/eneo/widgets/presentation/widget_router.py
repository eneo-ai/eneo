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
from eneo.roles.permissions import Permission, validate_permission
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.widgets.application.widget_service import WidgetView
from eneo.widgets.domain.widget import WidgetStatus
from eneo.widgets.domain.widget_template import WidgetTemplate
from eneo.widgets.presentation.widget_models import (
    WidgetApplyTemplate,
    WidgetConflictResponse,
    WidgetCreate,
    WidgetOverviewItem,
    WidgetOverviewPublic,
    WidgetOverviewTotals,
    WidgetPolicyPublic,
    WidgetPolicyUpdate,
    WidgetPreviewToken,
    WidgetPublic,
    WidgetTemplateCreate,
    WidgetTemplatePublic,
    WidgetTemplateUpdate,
    WidgetUpdate,
    WidgetUsageDayPublic,
    WidgetUsagePublic,
)

# Mounted under /spaces, /widgets, /admin/widget-policy, /widget-templates
# and /admin/widget-templates respectively.
space_widgets_router = APIRouter()
router = APIRouter()
policy_router = APIRouter()
templates_router = APIRouter()
admin_templates_router = APIRouter()
overview_router = APIRouter()

_CONFLICT_RESPONSE = {
    "model": WidgetConflictResponse,
    "description": "Widget changed since it was read. Reload before saving.",
}

_ContainerWithUser = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]


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
    template = None
    if body.template_id is not None:
        template = await container.widget_template_service().get_template(
            body.template_id
        )
    view = await service.create_widget(
        space_id=space_id,
        target_id=body.target_id,
        name=body.name,
        language=body.language,
        template=template,
    )
    await _audit(
        container,
        action=ActionType.WIDGET_CREATED,
        view=view,
        description=f"Created widget '{view.widget.name}'",
        changes={"new": _widget_snapshot(view)},
    )
    return assembler.from_view(view)


@router.post(
    "/{id}/apply-template/",
    response_model=WidgetPublic,
    description=(
        "Copy a template's texts, appearance and language onto the widget."
        " A snapshot: later template edits do not affect the widget."
    ),
    responses={**responses.get_responses([400, 403, 404]), 409: _CONFLICT_RESPONSE},
)
async def apply_widget_template(
    id: UUID, body: WidgetApplyTemplate, container: _ContainerWithUser
):
    service = container.widget_service()
    assembler = container.widget_assembler()
    template = await container.widget_template_service().get_template(body.template_id)
    view = await service.apply_template(id, template, revision=body.revision)
    await _audit(
        container,
        action=ActionType.WIDGET_UPDATED,
        view=view,
        description=f"Applied template '{template.name}' to widget '{view.widget.name}'",
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
    responses={**responses.get_responses([400, 403, 404]), 409: _CONFLICT_RESPONSE},
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
    rows = await container.widget_usage_repo().list_days(
        view.widget.id, days=days, today=container.widget_budget().today()
    )
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
                helpful=row.helpful,
                unhelpful=row.unhelpful,
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
    responses={**responses.get_responses([400, 403, 404]), 409: _CONFLICT_RESPONSE},
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
    responses={**responses.get_responses([400, 403, 404]), 409: _CONFLICT_RESPONSE},
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
    responses={**responses.get_responses([400, 403, 404]), 409: _CONFLICT_RESPONSE},
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


# --- overview --------------------------------------------------------------


@overview_router.get(
    "/",
    response_model=WidgetOverviewPublic,
    description=(
        "Every widget in the organisation with where it lives and its usage"
        " over the last 7 and 30 days. Tenant admins only."
    ),
    responses=responses.get_responses([403]),
)
async def get_widget_overview(container: _ContainerWithUser):
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    rows = await container.widget_overview_repo().list_tenant(
        user.tenant_id, today=container.widget_budget().today()
    )
    items: list[WidgetOverviewItem] = []
    for row in rows:
        items.append(
            WidgetOverviewItem(
                id=row.id,
                public_id=row.public_id,
                name=row.name,
                status=WidgetStatus(row.status),
                space_id=row.space_id,
                space_name=row.space_name,
                target_id=row.target_id,
                assistant_name=row.assistant_name,
                allowed_origins=row.allowed_origins,
                activated_at=row.activated_at,
                paused_at=row.paused_at,
                updated_at=row.updated_at,
                questions_7d=row.questions_7d,
                questions_30d=row.questions_30d,
                input_tokens_30d=row.input_tokens_30d,
                output_tokens_30d=row.output_tokens_30d,
                blocked_30d=row.blocked_30d,
                helpful_30d=row.helpful_30d,
                unhelpful_30d=row.unhelpful_30d,
                last_activity=row.last_activity,
                daily_token_budget=row.daily_token_budget,
                budget_used_today=row.budget_used_today,
            )
        )
    totals = WidgetOverviewTotals(
        widgets=len(items),
        active=sum(1 for i in items if i.status == WidgetStatus.ACTIVE),
        questions_7d=sum(i.questions_7d for i in items),
        questions_30d=sum(i.questions_30d for i in items),
        tokens_30d=sum(i.input_tokens_30d + i.output_tokens_30d for i in items),
        blocked_30d=sum(i.blocked_30d for i in items),
        helpful_30d=sum(i.helpful_30d for i in items),
        unhelpful_30d=sum(i.unhelpful_30d for i in items),
    )
    return WidgetOverviewPublic(items=items, totals=totals)


# --- templates -------------------------------------------------------------


def _template_public(template: WidgetTemplate) -> WidgetTemplatePublic:
    assert template.id is not None
    assert template.created_at is not None and template.updated_at is not None
    return WidgetTemplatePublic(
        id=template.id,
        name=template.name,
        description=template.description,
        texts=template.texts,
        theme=template.theme,
        language=template.language,
        is_default=template.is_default,
        created_by_user_id=template.created_by_user_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _template_snapshot(template: WidgetTemplate) -> dict[str, Any]:
    return {
        "name": template.name,
        "language": template.language.value,
        "is_default": template.is_default,
        "texts": template.texts.model_dump(mode="json"),
        "theme": template.theme.model_dump(mode="json"),
    }


async def _audit_template(
    container: Container,
    *,
    action: ActionType,
    template: WidgetTemplate,
    description: str,
    changes: dict[str, Any] | None = None,
) -> None:
    user = container.user()
    assert template.id is not None
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.WIDGET_TEMPLATE,
        entity_id=template.id,
        description=description,
        metadata=AuditMetadata.standard(actor=user, target=template, changes=changes),
    )


@templates_router.get(
    "/",
    response_model=PaginatedResponse[WidgetTemplatePublic],
    description=(
        "Widget templates of the organisation, default first. Readable by"
        " everyone with the widgets permission."
    ),
    responses=responses.get_responses([403]),
)
async def list_widget_templates(container: _ContainerWithUser):
    templates = await container.widget_template_service().list_templates()
    return protocol.to_paginated_response([_template_public(t) for t in templates])


@admin_templates_router.post(
    "/",
    response_model=WidgetTemplatePublic,
    status_code=201,
    description="Create a widget template. Tenant admins only.",
    responses=responses.get_responses([400, 403]),
)
async def create_widget_template(
    body: WidgetTemplateCreate, container: _ContainerWithUser
):
    template = await container.widget_template_service().create_template(
        name=body.name, language=body.language, is_default=body.is_default
    )
    await _audit_template(
        container,
        action=ActionType.WIDGET_TEMPLATE_CREATED,
        template=template,
        description=f"Created widget template '{template.name}'",
        changes={"new": _template_snapshot(template)},
    )
    return _template_public(template)


@admin_templates_router.get(
    "/{id}/",
    response_model=WidgetTemplatePublic,
    description="A widget template. Tenant admins only.",
    responses=responses.get_responses([403, 404]),
)
async def get_widget_template(id: UUID, container: _ContainerWithUser):
    template = await container.widget_template_service().get_template(id)
    return _template_public(template)


@admin_templates_router.patch(
    "/{id}/",
    response_model=WidgetTemplatePublic,
    description=(
        "Update a widget template. Setting `is_default` clears the previous"
        " default. Existing widgets are never changed."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
async def update_widget_template(
    id: UUID, body: WidgetTemplateUpdate, container: _ContainerWithUser
):
    service = container.widget_template_service()
    before = await service.get_template(id)
    template = await service.update_template(id, body.model_dump(exclude_unset=True))
    await _audit_template(
        container,
        action=ActionType.WIDGET_TEMPLATE_UPDATED,
        template=template,
        description=f"Updated widget template '{template.name}'",
        changes={
            "old": _template_snapshot(before),
            "new": _template_snapshot(template),
        },
    )
    return _template_public(template)


@admin_templates_router.delete(
    "/{id}/",
    status_code=204,
    response_model=None,
    description="Delete a widget template. Widgets created from it are kept.",
    responses=responses.get_responses([403, 404]),
)
async def delete_widget_template(id: UUID, container: _ContainerWithUser) -> None:
    template = await container.widget_template_service().delete_template(id)
    await _audit_template(
        container,
        action=ActionType.WIDGET_TEMPLATE_DELETED,
        template=template,
        description=f"Deleted widget template '{template.name}'",
        changes={"old": _template_snapshot(template)},
    )
