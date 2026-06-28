"""
Integration tests for tenant-scoped template handling during model migration.

Templates (assistant_templates / app_templates) carry their own ``tenant_id``
and a ``deleted_at`` soft-delete marker. Both the migration impact count and
the actual rebind must therefore:

  1. only touch templates owned by the acting tenant (never another tenant's),
  2. ignore soft-deleted templates.

These tests lock in that behaviour for both the usage service (which feeds the
"N resources will be affected" preview) and the migration service (which does
the real rebind).
"""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from eneo.database.tables.app_template_table import AppTemplates
from eneo.database.tables.assistant_template_table import AssistantTemplates

_SOFT_DELETED_AT = datetime(2020, 1, 1, tzinfo=timezone.utc)


async def _add_assistant_template(
    session,
    *,
    name: str,
    completion_model_id: UUID,
    tenant_id: UUID,
    deleted: bool = False,
) -> AssistantTemplates:
    template = AssistantTemplates(
        name=name,
        description="desc",
        category="general",
        completion_model_id=completion_model_id,
        tenant_id=tenant_id,
        deleted_at=_SOFT_DELETED_AT if deleted else None,
    )
    session.add(template)
    await session.flush()
    return template


async def _add_app_template(
    session,
    *,
    name: str,
    completion_model_id: UUID,
    tenant_id: UUID,
    deleted: bool = False,
) -> AppTemplates:
    template = AppTemplates(
        name=name,
        description="desc",
        category="general",
        input_type="text",
        completion_model_id=completion_model_id,
        tenant_id=tenant_id,
        deleted_at=_SOFT_DELETED_AT if deleted else None,
    )
    session.add(template)
    await session.flush()
    return template


@pytest.mark.integration
@pytest.mark.asyncio
class TestMigrationTemplateTenantScope:
    """Tenant + soft-delete scoping for templates in migration & usage count."""

    async def test_migration_only_rebinds_acting_tenants_templates(
        self,
        db_container,
        completion_model_factory,
        tenant_factory,
        admin_user,
    ):
        """A tenant's migration must not rebind another tenant's templates."""
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(
                session, "gpt-3.5-turbo", provider="openai"
            )
            new_model = await completion_model_factory(
                session, "gpt-4", provider="openai"
            )
            other_tenant = await tenant_factory(session, name="Other Tenant")

            mine_assistant = await _add_assistant_template(
                session,
                name="Mine (assistant)",
                completion_model_id=old_model.id,
                tenant_id=admin_user.tenant_id,
            )
            theirs_assistant = await _add_assistant_template(
                session,
                name="Theirs (assistant)",
                completion_model_id=old_model.id,
                tenant_id=other_tenant.id,
            )
            mine_app = await _add_app_template(
                session,
                name="Mine (app)",
                completion_model_id=old_model.id,
                tenant_id=admin_user.tenant_id,
            )
            theirs_app = await _add_app_template(
                session,
                name="Theirs (app)",
                completion_model_id=old_model.id,
                tenant_id=other_tenant.id,
            )

            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["assistant_templates", "app_templates"],
                user=admin_user,
                confirm_migration=True,
            )

            assert result.success is True
            assert result.details["assistant_templates"] == 1
            assert result.details["app_templates"] == 1
            assert result.migrated_count == 2

            # Acting tenant's templates were rebound...
            assert (
                await _model_of(session, AssistantTemplates, mine_assistant.id)
                == new_model.id
            )
            assert await _model_of(session, AppTemplates, mine_app.id) == new_model.id
            # ...the other tenant's were left untouched.
            assert (
                await _model_of(session, AssistantTemplates, theirs_assistant.id)
                == old_model.id
            )
            assert await _model_of(session, AppTemplates, theirs_app.id) == old_model.id

    async def test_migration_excludes_soft_deleted_templates(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Soft-deleted templates must not be counted or rebound."""
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(
                session, "gpt-3.5-turbo", provider="openai"
            )
            new_model = await completion_model_factory(
                session, "gpt-4", provider="openai"
            )

            active = await _add_assistant_template(
                session,
                name="Active",
                completion_model_id=old_model.id,
                tenant_id=admin_user.tenant_id,
            )
            deleted = await _add_assistant_template(
                session,
                name="Deleted",
                completion_model_id=old_model.id,
                tenant_id=admin_user.tenant_id,
                deleted=True,
            )

            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["assistant_templates"],
                user=admin_user,
                confirm_migration=True,
            )

            assert result.success is True
            assert result.details["assistant_templates"] == 1
            assert (
                await _model_of(session, AssistantTemplates, active.id) == new_model.id
            )
            # The soft-deleted template still points at the old model.
            assert (
                await _model_of(session, AssistantTemplates, deleted.id) == old_model.id
            )

    async def test_usage_count_scopes_templates_to_tenant_and_excludes_deleted(
        self,
        db_container,
        completion_model_factory,
        tenant_factory,
        admin_user,
    ):
        """The impact preview total counts only own-tenant, non-deleted templates."""
        async with db_container() as container:
            session = container.session()

            model = await completion_model_factory(
                session, "gpt-3.5-turbo", provider="openai"
            )
            other_tenant = await tenant_factory(session, name="Other Tenant")

            # Counted: own-tenant, active (one assistant template + one app template).
            await _add_assistant_template(
                session,
                name="Mine active (assistant)",
                completion_model_id=model.id,
                tenant_id=admin_user.tenant_id,
            )
            await _add_app_template(
                session,
                name="Mine active (app)",
                completion_model_id=model.id,
                tenant_id=admin_user.tenant_id,
            )
            # Not counted: another tenant's template.
            await _add_assistant_template(
                session,
                name="Theirs (assistant)",
                completion_model_id=model.id,
                tenant_id=other_tenant.id,
            )
            # Not counted: own-tenant but soft-deleted.
            await _add_assistant_template(
                session,
                name="Mine deleted (assistant)",
                completion_model_id=model.id,
                tenant_id=admin_user.tenant_id,
                deleted=True,
            )

            usage_service = container.completion_model_usage_service()
            response = await usage_service.get_model_usage_details(
                model_id=model.id,
                tenant_id=admin_user.tenant_id,
                limit=100,
            )

            assert response is not None
            # Only the two own-tenant, active templates contribute.
            assert response.total == 2
            counted_types = sorted(item.entity_type for item in response.items)
            assert counted_types == ["app_template", "assistant_template"]


async def _model_of(session, table, entity_id: UUID) -> UUID:
    """Return the completion_model_id currently stored for a template row."""
    stmt = select(table.completion_model_id).where(table.id == entity_id)
    return (await session.execute(stmt)).scalar_one()
