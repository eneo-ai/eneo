from typing import TYPE_CHECKING, Optional
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from intric.main.exceptions import (
    NotFoundException,
    BadRequestException,
    NameCollisionException,
)
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from uuid import UUID
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.templates.app_template.api.app_template_models import AppTemplateCreate
    from intric.templates.app_template.app_template import AppTemplate
    from intric.templates.app_template.app_template_factory import (
        AppTemplateFactory,
    )
    from intric.templates.app_template.app_template_repo import (
        AppTemplateRepository,
    )
    from intric.templates.app_template.api.app_template_models import AppTemplateUpdate
    from intric.feature_flag.feature_flag_service import FeatureFlagService


class AppTemplateService:
    def __init__(
        self,
        factory: "AppTemplateFactory",
        repo: "AppTemplateRepository",
        feature_flag_service: "FeatureFlagService",
        session: "AsyncSession",
        user: "UserInDB",
    ) -> None:
        self.factory = factory
        self.repo = repo
        self.feature_flag_service = feature_flag_service
        self.session = session
        self.user = user

    async def get_app_template(
        self, app_template_id: "UUID", tenant_id: Optional["UUID"] = None
    ) -> "AppTemplate":
        """Get template by ID.

        Time complexity: O(log n) using primary key and composite index
        """
        app_template = await self.repo.get_by_id(
            app_template_id=app_template_id,
            tenant_id=tenant_id
        )

        if app_template is None:
            raise NotFoundException("Template not found")

        return app_template

    async def get_app_templates(
        self, tenant_id: "UUID"
    ) -> list["AppTemplate"]:
        """Get templates for gallery (tenant + global).

        Feature flag gated - returns empty list if disabled.
        """
        is_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="using_templates",
            tenant_id=tenant_id
        )
        if not is_enabled:
            return []

        return await self.repo.get_app_template_list(tenant_id=tenant_id)

    @validate_permissions(Permission.ADMIN)
    async def create_template(
        self,
        data: "AppTemplateCreate",
        tenant_id: "UUID",
    ) -> "AppTemplate":
        """Create tenant-scoped template with snapshot.

        Business logic:
        - Feature flag must be enabled
        - Name must be unique within tenant
        - Original state saved to snapshot
        - Admin only (enforced via decorator)

        Time complexity: O(log n) for feature check + duplicate check + insert
        """
        # Check feature flag enabled for tenant
        is_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="using_templates",
            tenant_id=tenant_id
        )
        if not is_enabled:
            raise BadRequestException(
                "Templates feature is not enabled for this tenant. Enable in settings first."
            )

        # Check duplicate name within tenant
        duplicate_exists = await self.repo.check_duplicate_name(
            name=data.name,
            tenant_id=tenant_id
        )
        if duplicate_exists:
            raise NameCollisionException(
                f"A template with name '{data.name}' already exists in this tenant"
            )

        # Create template with tenant_id
        from intric.database.tables.app_template_table import AppTemplates
        import sqlalchemy as sa

        # Create snapshot from initial data
        snapshot = {
            "name": data.name,
            "description": data.description,
            "category": data.category,
            "prompt_text": data.prompt,
            "completion_model_kwargs": data.completion_model_kwargs,
            "wizard": data.wizard.model_dump() if data.wizard else None,
            "input_type": data.input_type,
            "input_description": data.input_description,
        }

        stmt = (
            sa.insert(AppTemplates)
            .values(
                name=data.name,
                description=data.description,
                category=data.category,
                prompt_text=data.prompt,
                wizard=data.wizard.model_dump() if data.wizard else None,
                completion_model_kwargs=data.completion_model_kwargs,
                input_type=data.input_type,
                input_description=data.input_description,
                tenant_id=tenant_id,
                deleted_at=None,
                original_snapshot=snapshot,
            )
            .returning(AppTemplates)
        )

        try:
            result = await self.session.execute(stmt)
            template_record = result.scalar_one()
        except IntegrityError as e:
            if 'uq_app_templates_name_tenant' in str(e):
                raise NameCollisionException(
                    f"A template with name '{data.name}' already exists in this tenant"
                )
            raise

        return self.factory.create_app_template(item=template_record)

    @validate_permissions(Permission.ADMIN)
    async def update_template(
        self,
        template_id: "UUID",
        data: "AppTemplateUpdate",
        tenant_id: "UUID",
    ) -> "AppTemplate":
        """Update tenant-scoped template.

        Business logic:
        - Must belong to tenant
        - If name changed: check uniqueness
        - original_snapshot NOT updated (preserved for rollback)
        - Admin only (enforced via decorator)

        Time complexity: O(log n) for ownership check + optional duplicate check + update
        """
        # Verify template belongs to tenant
        template = await self.repo.get_by_id(
            app_template_id=template_id,
            tenant_id=tenant_id
        )
        if not template:
            raise NotFoundException(
                "Template not found or does not belong to this tenant"
            )

        # If name changed, check duplicate
        if data.name and data.name != template.name:
            duplicate_exists = await self.repo.check_duplicate_name(
                name=data.name,
                tenant_id=tenant_id
            )
            if duplicate_exists:
                raise NameCollisionException(
                    f"A template with name '{data.name}' already exists in this tenant"
                )

        # Update template (original_snapshot preserved)
        from intric.database.tables.app_template_table import AppTemplates
        import sqlalchemy as sa

        update_values = {}
        if data.name is not None:
            update_values["name"] = data.name
        if data.description is not None:
            update_values["description"] = data.description
        if data.category is not None:
            update_values["category"] = data.category
        if data.prompt is not None:
            update_values["prompt_text"] = data.prompt
        if data.wizard is not None:
            update_values["wizard"] = data.wizard.model_dump() if data.wizard else None
        if data.completion_model_kwargs is not None:
            update_values["completion_model_kwargs"] = data.completion_model_kwargs
        if data.input_type is not None:
            update_values["input_type"] = data.input_type
        if data.input_description is not None:
            update_values["input_description"] = data.input_description

        stmt = (
            sa.update(AppTemplates)
            .where(
                AppTemplates.id == template_id,
                AppTemplates.tenant_id == tenant_id
            )
            .values(**update_values)
            .returning(AppTemplates)
        )
        result = await self.session.execute(stmt)
        updated_record = result.scalar_one()

        return self.factory.create_app_template(item=updated_record)

    @validate_permissions(Permission.ADMIN)
    async def toggle_default(
        self,
        template_id: "UUID",
        is_default: bool,
        tenant_id: "UUID",
    ) -> "AppTemplate":
        """Toggle template as default/featured.

        Business logic:
        - Must belong to tenant
        - Max 5 defaults per tenant (enforced with SELECT FOR UPDATE)
        - Admin only (enforced via decorator)
        - Concurrency-safe with row locking

        Time complexity: O(log n) for ownership + count check + update
        """
        from intric.database.tables.app_template_table import AppTemplates
        import sqlalchemy as sa

        # Verify template belongs to tenant
        template = await self.repo.get_by_id(
            app_template_id=template_id,
            tenant_id=tenant_id
        )
        if not template:
            raise NotFoundException(
                "Template not found or does not belong to this tenant"
            )

        # If setting to true, check limit with locking
        if is_default:
            # Lock current default template rows, then count (prevent race conditions)
            lock_stmt = (
                select(AppTemplates.id)
                .where(
                    AppTemplates.tenant_id == tenant_id,
                    AppTemplates.is_default == True,
                    AppTemplates.id != template_id  # Exclude current template
                )
                .with_for_update()
            )
            result = await self.session.execute(lock_stmt)
            current_count = len(result.scalars().all())

            if current_count >= 5:
                raise BadRequestException(
                    "Maximum of 5 featured templates reached. Remove one to add another."
                )

        # Update is_default field
        stmt = (
            sa.update(AppTemplates)
            .where(
                AppTemplates.id == template_id,
                AppTemplates.tenant_id == tenant_id
            )
            .values(is_default=is_default)
            .returning(AppTemplates)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        updated_record = result.scalar_one()

        return self.factory.create_app_template(item=updated_record)

    @validate_permissions(Permission.ADMIN)

    async def delete_template(
        self,
        template_id: "UUID",
        tenant_id: "UUID",
        user_id: "UUID",
    ) -> None:
        """Soft-delete tenant-scoped template.

        Business logic:
        - Must belong to tenant
        - Sets deleted_at timestamp
        - Tracks who deleted it (deleted_by_user_id)
        - Admin only (enforced at router level)
        - Apps using this template continue to work (FK has ondelete="SET NULL")

        Time complexity: O(log n) for ownership check + soft-delete
        """
        # Verify template belongs to tenant
        template = await self.repo.get_by_id(
            app_template_id=template_id,
            tenant_id=tenant_id
        )
        if not template:
            raise NotFoundException(
                "Template not found or does not belong to this tenant"
            )

        # Soft-delete with audit trail (no usage blocking)
        result = await self.repo.soft_delete(id=template_id, tenant_id=tenant_id, user_id=user_id)
        if not result:
            raise NotFoundException("Template not found")

    @validate_permissions(Permission.ADMIN)

    async def rollback_template(
        self,
        template_id: "UUID",
        tenant_id: "UUID",
    ) -> "AppTemplate":
        """Restore template to original state from snapshot.

        Business logic:
        - Must belong to tenant
        - Must have original_snapshot
        - Restores all fields from snapshot
        - Updates updated_at timestamp
        - Admin only (enforced at router level)

        Time complexity: O(log n) for ownership check + update
        """
        # Verify template belongs to tenant
        template = await self.repo.get_by_id(
            app_template_id=template_id,
            tenant_id=tenant_id
        )
        if not template:
            raise NotFoundException(
                "Template not found or does not belong to this tenant"
            )

        # Check snapshot exists
        if not template.original_snapshot:
            raise BadRequestException(
                "Cannot rollback template. Original snapshot not found."
            )

        # Restore from snapshot
        from intric.database.tables.app_template_table import AppTemplates
        import sqlalchemy as sa

        snapshot = template.original_snapshot

        stmt = (
            sa.update(AppTemplates)
            .where(
                AppTemplates.id == template_id,
                AppTemplates.tenant_id == tenant_id
            )
            .values(
                name=snapshot.get("name"),
                description=snapshot.get("description"),
                category=snapshot.get("category"),
                prompt_text=snapshot.get("prompt_text"),
                completion_model_kwargs=snapshot.get("completion_model_kwargs"),
                wizard=snapshot.get("wizard"),
                input_type=snapshot.get("input_type"),
                input_description=snapshot.get("input_description"),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(AppTemplates)
        )
        result = await self.session.execute(stmt)
        restored_record = result.scalar_one()

        return self.factory.create_app_template(item=restored_record)

    @validate_permissions(Permission.ADMIN)

    async def restore_template(
        self,
        template_id: "UUID",
        tenant_id: "UUID",
        user_id: "UUID",
    ) -> "AppTemplate":
        """Restore a soft-deleted template (clear deleted_at timestamp).

        Business logic:
        - Must belong to tenant
        - Must be soft-deleted (deleted_at IS NOT NULL)
        - Clears deleted_at to restore template
        - Tracks who restored it (restored_by_user_id, restored_at)
        - Admin only (enforced at router level)

        Time complexity: O(log n) for ownership check + update

        Raises:
            NotFoundException: Template not found, doesn't belong to tenant,
                              or not in deleted state
        """
        # Perform restore with audit trail
        template = await self.repo.restore(id=template_id, tenant_id=tenant_id, user_id=user_id)

        if not template:
            raise NotFoundException(
                "Template not found or not in deleted state. "
                "It may have already been restored or permanently deleted."
            )

        return template

    @validate_permissions(Permission.ADMIN)

    async def permanent_delete_template(
        self,
        template_id: "UUID",
        tenant_id: "UUID",
    ) -> None:
        """Permanently delete a soft-deleted template from database (hard delete).

        Business logic:
        - Must belong to tenant
        - Must be soft-deleted (deleted_at IS NOT NULL)
        - Cannot be undone - permanently removes from database
        - Admin only (enforced at router level)

        Time complexity: O(log n) for ownership check + delete
        """
        result = await self.repo.permanent_delete(id=template_id, tenant_id=tenant_id)
        if not result:
            raise NotFoundException(
                "Template not found or not in deleted state"
            )

    @validate_permissions(Permission.ADMIN)

    async def get_templates_for_tenant(
        self,
        tenant_id: "UUID",
    ) -> list[tuple["AppTemplate", int]]:
        """Get tenant-specific templates only (admin view) with usage counts.

        Returns only templates where tenant_id matches (NOT global templates).
        Used for admin management page.
        Each template is returned with its usage count (number of apps created from it).

        Time complexity: O(k log n) where k is number of tenant templates
        """
        from intric.database.tables.app_template_table import AppTemplates
        from intric.database.tables.app_table import Apps
        import sqlalchemy as sa

        # Query with LEFT JOIN to get usage count
        stmt = (
            select(
                AppTemplates,
                func.count(Apps.id).label("usage_count")
            )
            .outerjoin(
                Apps,
                sa.and_(
                    AppTemplates.id == Apps.template_id,
                    AppTemplates.tenant_id == Apps.tenant_id
                )
            )
            .where(
                AppTemplates.tenant_id == tenant_id,
                AppTemplates.deleted_at.is_(None)
            )
            .group_by(AppTemplates.id)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        # Convert to (AppTemplate, usage_count) tuples
        templates_with_usage = []
        for row in rows:
            template_record = row[0]
            usage_count = row[1]
            template = self.factory.create_app_template(item=template_record)
            templates_with_usage.append((template, usage_count))

        return templates_with_usage

    @validate_permissions(Permission.ADMIN)

    async def get_deleted_templates_for_tenant(
        self,
        tenant_id: "UUID",
    ) -> list[tuple["AppTemplate", int]]:
        """Get soft-deleted templates for audit trail with usage counts.

        Returns deleted templates ordered by deleted_at DESC.
        Each template is returned with its usage count.
        Admin only (enforced at router level).

        Time complexity: O(k log n) where k is number of deleted templates
        """
        from intric.database.tables.app_template_table import AppTemplates
        from intric.database.tables.app_table import Apps
        import sqlalchemy as sa

        # Query with LEFT JOIN to get usage count for deleted templates
        stmt = (
            select(
                AppTemplates,
                func.count(Apps.id).label("usage_count")
            )
            .outerjoin(
                Apps,
                sa.and_(
                    AppTemplates.id == Apps.template_id,
                    AppTemplates.tenant_id == Apps.tenant_id
                )
            )
            .where(
                AppTemplates.tenant_id == tenant_id,
                AppTemplates.deleted_at.is_not(None)
            )
            .group_by(AppTemplates.id)
            .order_by(AppTemplates.deleted_at.desc())
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        # Convert to (AppTemplate, usage_count) tuples
        templates_with_usage = []
        for row in rows:
            template_record = row[0]
            usage_count = row[1]
            template = self.factory.create_app_template(item=template_record)
            templates_with_usage.append((template, usage_count))

        return templates_with_usage

    async def _count_template_usage(self, template_id: "UUID") -> int:
        """Count how many apps use this template.

        Time complexity: O(log n) using template_id index
        """
        from intric.database.tables.app_table import Apps

        stmt = select(func.count(Apps.id)).where(
            Apps.template_id == template_id
        )
        result = await self.session.scalar(stmt)
        return result or 0
