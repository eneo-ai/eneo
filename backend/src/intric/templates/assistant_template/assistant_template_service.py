from typing import TYPE_CHECKING, Optional
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from intric.main.exceptions import (
    NotFoundException,
    BadRequestException,
    NameCollisionException,
)
from intric.roles.permissions import Permission, validate_permissions
from intric.templates.assistant_template.api.assistant_template_models import (
    AssistantTemplateCreate,
)

if TYPE_CHECKING:
    from uuid import UUID
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.templates.assistant_template.assistant_template import AssistantTemplate
    from intric.templates.assistant_template.assistant_template_factory import (
        AssistantTemplateFactory,
    )
    from intric.templates.assistant_template.assistant_template_repo import (
        AssistantTemplateRepository,
    )
    from intric.templates.assistant_template.api.assistant_template_models import (
        AssistantTemplateUpdate,
    )
    from intric.feature_flag.feature_flag_service import FeatureFlagService
    from intric.users.user import UserInDB


class AssistantTemplateService:
    def __init__(
        self,
        factory: "AssistantTemplateFactory",
        repo: "AssistantTemplateRepository",
        feature_flag_service: "FeatureFlagService",
        session: "AsyncSession",
        user: "UserInDB",
    ) -> None:
        self.factory = factory
        self.repo = repo
        self.feature_flag_service = feature_flag_service
        self.session = session
        self.user = user

    async def get_assistant_template(
        self, assistant_template_id: "UUID", tenant_id: Optional["UUID"] = None
    ) -> "AssistantTemplate":
        """Get template by ID.

        Time complexity: O(log n) using primary key and composite index
        """
        assistant_template = await self.repo.get_by_id(
            assistant_template_id=assistant_template_id,
            tenant_id=tenant_id
        )

        if assistant_template is None:
            raise NotFoundException("Template not found")

        return assistant_template

    async def get_assistant_templates(
        self, tenant_id: "UUID"
    ) -> list["AssistantTemplate"]:
        """Get templates for gallery (tenant + global).

        Returns tenant-specific and global templates for template selection gallery.
        Feature flag gated - returns empty list if disabled.

        Time complexity: O(k log n) where k is number of matching templates
        """
        # Check feature flag
        is_enabled = await self.feature_flag_service.check_is_feature_enabled(
            feature_name="using_templates",
            tenant_id=tenant_id
        )
        if not is_enabled:
            # Return empty list when feature disabled (not error)
            return []

        return await self.repo.get_assistant_template_list(tenant_id=tenant_id)

    @validate_permissions(Permission.ADMIN)
    async def create_template(
        self,
        data: AssistantTemplateCreate,
        tenant_id: "UUID",
    ) -> "AssistantTemplate":
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
        from intric.database.tables.assistant_template_table import AssistantTemplates
        import sqlalchemy as sa

        # Create snapshot from initial data
        snapshot = {
            "name": data.name,
            "description": data.description,
            "category": data.category,
            "prompt_text": data.prompt,
            "completion_model_kwargs": data.completion_model_kwargs,
            "wizard": data.wizard.model_dump() if data.wizard else None,
        }

        stmt = (
            sa.insert(AssistantTemplates)
            .values(
                name=data.name,
                description=data.description,
                category=data.category,
                prompt_text=data.prompt,
                wizard=data.wizard.model_dump() if data.wizard else None,
                completion_model_kwargs=data.completion_model_kwargs,
                tenant_id=tenant_id,
                deleted_at=None,
                original_snapshot=snapshot,
                icon_name=data.icon_name,
            )
            .returning(AssistantTemplates)
        )

        try:
            result = await self.session.execute(stmt)
            template_record = result.scalar_one()
        except IntegrityError as e:
            if 'uq_assistant_templates_name_tenant' in str(e):
                raise NameCollisionException(
                    f"A template with name '{data.name}' already exists in this tenant"
                )
            raise

        # Eagerly load relationship to prevent lazy-load I/O in async context
        await self.session.refresh(template_record, ["completion_model"])

        return self.factory.create_assistant_template(item=template_record)

    @validate_permissions(Permission.ADMIN)
    async def update_template(
        self,
        template_id: "UUID",
        data: "AssistantTemplateUpdate",
        tenant_id: "UUID",
    ) -> "AssistantTemplate":
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
            assistant_template_id=template_id,
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
        from intric.database.tables.assistant_template_table import AssistantTemplates
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
        if data.completion_model_id is not None:
            update_values["completion_model_id"] = data.completion_model_id
        if data.icon_name is not None:
            update_values["icon_name"] = data.icon_name

        stmt = (
            sa.update(AssistantTemplates)
            .where(
                AssistantTemplates.id == template_id,
                AssistantTemplates.tenant_id == tenant_id
            )
            .values(**update_values)
            .returning(AssistantTemplates)
        )
        result = await self.session.execute(stmt)
        updated_record = result.scalar_one()

        # Eagerly load relationship to prevent lazy-load I/O in async context
        await self.session.refresh(updated_record, ["completion_model"])

        return self.factory.create_assistant_template(item=updated_record)

    @validate_permissions(Permission.ADMIN)
    async def toggle_default(
        self,
        template_id: "UUID",
        is_default: bool,
        tenant_id: "UUID",
    ) -> "AssistantTemplate":
        """Toggle template as default/featured.

        Business logic:
        - Must belong to tenant
        - Max 5 defaults per tenant (enforced with SELECT FOR UPDATE)
        - Admin only (enforced via decorator)
        - Concurrency-safe with row locking

        Time complexity: O(log n) for ownership + count check + update
        """
        from intric.database.tables.assistant_template_table import AssistantTemplates
        import sqlalchemy as sa

        # Verify template belongs to tenant
        template = await self.repo.get_by_id(
            assistant_template_id=template_id,
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
                select(AssistantTemplates.id)
                .where(
                    AssistantTemplates.tenant_id == tenant_id,
                    AssistantTemplates.is_default == True,
                    AssistantTemplates.id != template_id  # Exclude current template
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
            sa.update(AssistantTemplates)
            .where(
                AssistantTemplates.id == template_id,
                AssistantTemplates.tenant_id == tenant_id
            )
            .values(is_default=is_default)
            .returning(AssistantTemplates)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        updated_record = result.scalar_one()

        # Eagerly load relationship to prevent lazy-load I/O in async context
        await self.session.refresh(updated_record, ["completion_model"])

        return self.factory.create_assistant_template(item=updated_record)

    @validate_permissions(Permission.ADMIN)
    async def delete_template(
        self,
        template_id: "UUID",
        tenant_id: "UUID",
        user_id: "UUID",
    ) -> "AssistantTemplate":
        """Soft-delete tenant-scoped template.

        Business logic:
        - Must belong to tenant
        - Sets deleted_at timestamp
        - Tracks who deleted it (deleted_by_user_id)
        - Admin only (enforced via decorator)
        - Assistants using this template continue to work (FK has ondelete="SET NULL")

        Time complexity: O(log n) for ownership check + soft-delete

        Returns:
            The deleted template object
        """
        # Verify template belongs to tenant
        template = await self.repo.get_by_id(
            assistant_template_id=template_id,
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

        return result

    @validate_permissions(Permission.ADMIN)
    async def rollback_template(
        self,
        template_id: "UUID",
        tenant_id: "UUID",
    ) -> "AssistantTemplate":
        """Restore template to original state from snapshot.

        Business logic:
        - Must belong to tenant
        - Must have original_snapshot
        - Restores all fields from snapshot
        - Updates updated_at timestamp
        - Admin only (enforced via decorator)

        Time complexity: O(log n) for ownership check + update
        """
        # Verify template belongs to tenant
        template = await self.repo.get_by_id(
            assistant_template_id=template_id,
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
        from intric.database.tables.assistant_template_table import AssistantTemplates
        import sqlalchemy as sa

        snapshot = template.original_snapshot

        stmt = (
            sa.update(AssistantTemplates)
            .where(
                AssistantTemplates.id == template_id,
                AssistantTemplates.tenant_id == tenant_id
            )
            .values(
                name=snapshot.get("name"),
                description=snapshot.get("description"),
                category=snapshot.get("category"),
                prompt_text=snapshot.get("prompt_text"),
                completion_model_kwargs=snapshot.get("completion_model_kwargs"),
                wizard=snapshot.get("wizard"),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(AssistantTemplates)
        )
        result = await self.session.execute(stmt)
        restored_record = result.scalar_one()

        # Eagerly load relationship to prevent lazy-load I/O in async context
        await self.session.refresh(restored_record, ["completion_model"])

        return self.factory.create_assistant_template(item=restored_record)

    @validate_permissions(Permission.ADMIN)
    async def restore_template(
        self,
        template_id: "UUID",
        tenant_id: "UUID",
        user_id: "UUID",
    ) -> "AssistantTemplate":
        """Restore a soft-deleted template (clear deleted_at timestamp).

        Business logic:
        - Must belong to tenant
        - Must be soft-deleted (deleted_at IS NOT NULL)
        - Clears deleted_at to restore template
        - Tracks who restored it (restored_by_user_id, restored_at)
        - Admin only (enforced via decorator)

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
        - Admin only (enforced via decorator)

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
    ) -> list[tuple["AssistantTemplate", int]]:
        """Get tenant-specific templates only (admin view) with usage counts.

        Returns only templates where tenant_id matches (NOT global templates).
        Used for admin management page.
        Each template is returned with its usage count (number of assistants created from it).
        Admin only (enforced via decorator).

        Time complexity: O(k log n) where k is number of tenant templates
        """
        from intric.database.tables.assistant_template_table import AssistantTemplates
        from intric.database.tables.assistant_table import Assistants

        # Query with LEFT JOIN to get usage count
        # Note: Assistants don't have tenant_id (they use space_id -> Space -> Tenant)
        # Tenant isolation is guaranteed by template filtering in WHERE clause
        stmt = (
            select(
                AssistantTemplates,
                func.count(Assistants.id).label("usage_count")
            )
            .outerjoin(
                Assistants,
                AssistantTemplates.id == Assistants.template_id
            )
            .where(
                AssistantTemplates.tenant_id == tenant_id,
                AssistantTemplates.deleted_at.is_(None)
            )
            .group_by(AssistantTemplates.id)
            .options(selectinload(AssistantTemplates.completion_model))
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        # Convert to (AssistantTemplate, usage_count) tuples
        templates_with_usage = []
        for row in rows:
            template_record = row[0]
            usage_count = row[1]
            template = self.factory.create_assistant_template(item=template_record)
            templates_with_usage.append((template, usage_count))

        return templates_with_usage

    @validate_permissions(Permission.ADMIN)
    async def get_deleted_templates_for_tenant(
        self,
        tenant_id: "UUID",
    ) -> list[tuple["AssistantTemplate", int]]:
        """Get soft-deleted templates for audit trail with usage counts.

        Returns deleted templates ordered by deleted_at DESC.
        Each template is returned with its usage count.
        Admin only (enforced via decorator).

        Time complexity: O(k log n) where k is number of deleted templates
        """
        from intric.database.tables.assistant_template_table import AssistantTemplates
        from intric.database.tables.assistant_table import Assistants

        # Query with LEFT JOIN to get usage count for deleted templates
        # Note: Assistants don't have tenant_id (they use space_id -> Space -> Tenant)
        # Tenant isolation is guaranteed by template filtering in WHERE clause
        stmt = (
            select(
                AssistantTemplates,
                func.count(Assistants.id).label("usage_count")
            )
            .outerjoin(
                Assistants,
                AssistantTemplates.id == Assistants.template_id
            )
            .where(
                AssistantTemplates.tenant_id == tenant_id,
                AssistantTemplates.deleted_at.is_not(None)
            )
            .group_by(AssistantTemplates.id)
            .order_by(AssistantTemplates.deleted_at.desc())
            .options(selectinload(AssistantTemplates.completion_model))
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        # Convert to (AssistantTemplate, usage_count) tuples
        templates_with_usage = []
        for row in rows:
            template_record = row[0]
            usage_count = row[1]
            template = self.factory.create_assistant_template(item=template_record)
            templates_with_usage.append((template, usage_count))

        return templates_with_usage

    async def _count_template_usage(self, template_id: "UUID") -> int:
        """Count how many assistants use this template.

        Time complexity: O(log n) using template_id index
        """
        from intric.database.tables.assistant_table import Assistants

        stmt = select(func.count(Assistants.id)).where(
            Assistants.template_id == template_id
        )
        result = await self.session.scalar(stmt)
        return result or 0
