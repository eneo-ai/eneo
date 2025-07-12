import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from intric.completion_models.presentation.completion_model_models import (
    ModelUsageDetail,
    ModelUsageStatistics,
    ModelUsageSummary,
    PaginatedResponse,
)
from intric.database.tables.ai_models_table import CompletionModelUsageStats, CompletionModels, CompletionModelSettings
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.assistant_template_table import AssistantTemplates
from intric.database.tables.app_table import Apps
from intric.database.tables.app_template_table import AppTemplates
from intric.database.tables.questions_table import Questions
from intric.database.tables.service_table import Services
from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels
from intric.database.tables.users_table import Users

if TYPE_CHECKING:
    from intric.completion_models.domain.completion_model_repo import CompletionModelRepository


class CompletionModelUsageService:
    """Service for tracking and retrieving completion model usage statistics."""

    def __init__(
        self,
        session: AsyncSession,
        completion_model_repo: "CompletionModelRepository",
    ):
        self.session = session
        self.completion_model_repo = completion_model_repo
        self.logger = logging.getLogger(__name__)

    async def get_model_usage_statistics(
        self, model_id: UUID, tenant_id: UUID
    ) -> ModelUsageStatistics:
        """Get pre-aggregated usage statistics for a specific model."""
        stmt = select(CompletionModelUsageStats).where(
            and_(
                CompletionModelUsageStats.model_id == model_id,
                CompletionModelUsageStats.tenant_id == tenant_id,
            )
        )
        
        result = await self.session.execute(stmt)
        stats = result.scalar_one_or_none()
        
        if not stats:
            # Return empty statistics if no data exists
            return ModelUsageStatistics(
                model_id=model_id,
                total_usage=0,
                assistants_count=0,
                apps_count=0,
                services_count=0,
                questions_count=0,
                assistant_templates_count=0,
                app_templates_count=0,
                spaces_count=0,
                last_updated=datetime.utcnow(),
            )
        
        return ModelUsageStatistics(
            model_id=stats.model_id,
            total_usage=stats.total_usage,
            assistants_count=stats.assistants_count,
            apps_count=stats.apps_count,
            services_count=stats.services_count,
            questions_count=stats.questions_count,
            assistant_templates_count=stats.assistant_templates_count,
            app_templates_count=stats.app_templates_count,
            spaces_count=stats.spaces_count,
            last_updated=stats.last_updated,
        )

    async def get_model_usage_details(
        self,
        model_id: UUID,
        tenant_id: UUID,
        entity_type: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> PaginatedResponse:
        """Get detailed list of entities using this model with cursor pagination."""
        # Decode cursor if provided
        cursor_data = None
        if cursor:
            try:
                decoded = base64.b64decode(cursor).decode('utf-8')
                cursor_data = json.loads(decoded)
            except Exception as e:
                self.logger.warning(f"Invalid cursor format: {e}")
                cursor_data = None
        
        # Define entity types to query
        entity_queries = {
            "assistant": self._get_assistant_details,
            "app": self._get_app_details,
            "service": self._get_service_details,
            "assistant_template": self._get_assistant_template_details,
            "app_template": self._get_app_template_details,
        }
        
        if entity_type:
            # Query specific entity type with cursor support
            if entity_type in entity_queries:
                details, has_more = await entity_queries[entity_type](
                    model_id, tenant_id, limit, cursor_data
                )
                
                # Generate next cursor if there are more results
                next_cursor = None
                if has_more and details:
                    last_item = details[-1]
                    cursor_obj = {
                        "created_at": last_item.created_at.isoformat(),
                        "id": str(last_item.entity_id),
                        "entity_type": entity_type
                    }
                    next_cursor = base64.b64encode(
                        json.dumps(cursor_obj).encode('utf-8')
                    ).decode('utf-8')
                
                return PaginatedResponse(
                    items=details,
                    total=len(details),
                    has_more=has_more,
                    next_cursor=next_cursor,
                    prev_cursor=None,  # Single direction for simplicity
                )
        else:
            # For multiple entity types, use simpler approach
            # This is less common and doesn't need full cursor support
            details = []
            for entity_type_name, query_func in entity_queries.items():
                entity_details, _ = await query_func(
                    model_id, tenant_id, limit // len(entity_queries), None
                )
                details.extend(entity_details)
            
            # Sort by created_at descending
            details.sort(key=lambda x: x.created_at, reverse=True)
            
            # Apply limit
            details = details[:limit]
            
            return PaginatedResponse(
                items=details,
                total=len(details),
                has_more=len(details) == limit,
                next_cursor=None,
                prev_cursor=None,
            )

    async def get_all_models_usage_summary(self, tenant_id: UUID) -> List[ModelUsageSummary]:
        """Get usage summary for all models in a tenant."""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            logger.info(f"Starting get_all_models_usage_summary for tenant {tenant_id}")
            
            # Join with CompletionModelSettings to get the is_org_enabled field
            stmt = (
                select(
                    CompletionModels.id,
                    CompletionModels.name,
                    CompletionModels.nickname,
                    CompletionModelSettings.is_org_enabled,
                    CompletionModelUsageStats.total_usage,
                    CompletionModelUsageStats.last_updated,
                )
                .select_from(CompletionModels)
                .join(
                    CompletionModelSettings,
                    and_(
                        CompletionModelSettings.completion_model_id == CompletionModels.id,
                        CompletionModelSettings.tenant_id == tenant_id
                    )
                )
                .outerjoin(
                    CompletionModelUsageStats,
                    and_(
                        CompletionModelUsageStats.model_id == CompletionModels.id,
                        CompletionModelUsageStats.tenant_id == tenant_id
                    )
                )
                .order_by(
                    CompletionModelUsageStats.total_usage.desc().nullslast()
                )
            )
            
            logger.info(f"Executing query: {stmt}")
            
            results = await self.session.execute(stmt)
            rows = results.all()
            
            logger.info(f"Query returned {len(rows)} rows")
            
            summaries = []
            for row in rows:
                logger.debug(f"Processing row: {row}")
                
                summary = ModelUsageSummary(
                    model_id=row.id,
                    model_name=row.name,
                    model_nickname=row.nickname,
                    is_enabled=row.is_org_enabled,  # Map is_org_enabled to is_enabled
                    total_usage=row.total_usage or 0,
                    last_updated=row.last_updated or datetime.utcnow(),
                )
                summaries.append(summary)
            
            logger.info(f"Successfully created {len(summaries)} usage summaries")
            return summaries
            
        except Exception as e:
            logger.error(f"Error in get_all_models_usage_summary: {str(e)}", exc_info=True)
            raise

    def _build_tenant_filter_condition(self, table: Any, entity_type: str, tenant_id: UUID):
        """Build appropriate tenant filtering condition based on entity type."""
        if entity_type in {"app", "question"}:
            # Direct tenant_id field
            return table.tenant_id == tenant_id
        elif entity_type in {"assistant", "service"}:
            # Via user relationship - need to join with Users table
            return table.user_id.in_(
                select(Users.id).where(Users.tenant_id == tenant_id)
            )
        elif entity_type in {"assistant_template", "app_template"}:
            # Global entities - no tenant filtering needed
            return True
        else:
            self.logger.warning(f"Unknown entity type for tenant filtering: {entity_type}")
            return True

    async def _get_entity_details(
        self,
        table: Any,
        model_id: UUID,
        tenant_id: UUID,
        limit: int,
        entity_type: str,
        joins: List[tuple] = None,
        extra_columns: List[Any] = None,
        cursor_data: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[ModelUsageDetail], bool]:
        """Generic method to get entity details for any entity type with cursor support."""
        self.logger.debug(f"Getting entity details for entity_type={entity_type}, model_id={model_id}, tenant_id={tenant_id}")
        
        # Base columns that all entities have
        columns = [
            table.id,
            table.name,
            table.created_at,
        ]
        
        # Add any extra columns specific to this entity type
        if extra_columns:
            columns.extend(extra_columns)
        
        # Build the base query with tenant-aware filtering
        tenant_condition = self._build_tenant_filter_condition(table, entity_type, tenant_id)
        
        stmt = (
            select(*columns)
            .where(
                and_(
                    table.completion_model_id == model_id,
                    tenant_condition,
                )
            )
        )
        
        # Apply cursor filter if provided
        if cursor_data:
            cursor_created_at = datetime.fromisoformat(cursor_data["created_at"])
            cursor_id = UUID(cursor_data["id"])
            
            # Add cursor condition for pagination
            stmt = stmt.where(
                (table.created_at < cursor_created_at) |
                ((table.created_at == cursor_created_at) & (table.id < cursor_id))
            )
        
        # Order by created_at and id for consistent pagination
        stmt = stmt.order_by(table.created_at.desc(), table.id.desc())
        
        # Limit + 1 to check if there are more results
        stmt = stmt.limit(limit + 1)
        
        # Apply joins if provided
        if joins:
            for join_table, join_condition in joins:
                stmt = stmt.join(join_table, join_condition, isouter=True)
        
        result = await self.session.execute(stmt)
        rows = result.fetchall()
        
        # Check if there are more results
        has_more = len(rows) > limit
        rows = rows[:limit]  # Only return requested limit
        
        # Convert rows to ModelUsageDetail objects
        details = []
        for row in rows:
            # Build a dict from the row data
            row_dict = dict(row._mapping)
            
            # Map the data to ModelUsageDetail fields
            detail = ModelUsageDetail(
                entity_id=row_dict.get("id"),
                entity_name=row_dict.get("name"),
                entity_type=entity_type,
                space_id=row_dict.get("space_id"),
                space_name=row_dict.get("space_name"),
                owner_id=row_dict.get("user_id"),
                owner_name=row_dict.get("owner_name"),
                created_at=row_dict.get("created_at"),
            )
            details.append(detail)
        
        return details, has_more

    async def _get_assistant_details(
        self, model_id: UUID, tenant_id: UUID, limit: int, cursor_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[ModelUsageDetail], bool]:
        """Get details for assistants using this model."""
        return await self._get_entity_details(
            table=Assistants,
            model_id=model_id,
            tenant_id=tenant_id,
            limit=limit,
            entity_type="assistant",
            joins=[
                (Spaces, Assistants.space_id == Spaces.id),
                (Users, Assistants.user_id == Users.id),
            ],
            extra_columns=[
                Assistants.space_id,
                Assistants.user_id,
                Spaces.name.label("space_name"),
                Users.username.label("owner_name"),
            ],
            cursor_data=cursor_data,
        )

    async def _get_app_details(
        self, model_id: UUID, tenant_id: UUID, limit: int, cursor_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[ModelUsageDetail], bool]:
        """Get details for apps using this model."""
        return await self._get_entity_details(
            table=Apps,
            model_id=model_id,
            tenant_id=tenant_id,
            limit=limit,
            entity_type="app",
            joins=[
                (Spaces, Apps.space_id == Spaces.id),
                (Users, Apps.user_id == Users.id),
            ],
            extra_columns=[
                Apps.space_id,
                Apps.user_id,
                Spaces.name.label("space_name"),
                Users.username.label("owner_name"),
            ],
        )

    async def _get_service_details(
        self, model_id: UUID, tenant_id: UUID, limit: int, cursor_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[ModelUsageDetail], bool]:
        """Get details for services using this model."""
        return await self._get_entity_details(
            table=Services,
            model_id=model_id,
            tenant_id=tenant_id,
            limit=limit,
            entity_type="service",
            joins=[
                (Users, Services.user_id == Users.id),
            ],
            extra_columns=[
                Services.user_id,
                Users.username.label("owner_name"),
            ],
        )

    async def _get_assistant_template_details(
        self, model_id: UUID, tenant_id: UUID, limit: int, cursor_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[ModelUsageDetail], bool]:
        """Get details for assistant templates using this model."""
        return await self._get_entity_details(
            table=AssistantTemplates,
            model_id=model_id,
            tenant_id=tenant_id,
            limit=limit,
            entity_type="assistant_template",
            joins=[
                # Assistant templates don't have user_id, they are global entities
                # No joins needed for templates
            ],
            extra_columns=[
                # No user_id or owner information for templates
                # Templates are global and don't have owners
            ],
            cursor_data=cursor_data,
        )

    async def _get_app_template_details(
        self, model_id: UUID, tenant_id: UUID, limit: int, cursor_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[ModelUsageDetail], bool]:
        """Get details for app templates using this model."""
        return await self._get_entity_details(
            table=AppTemplates,
            model_id=model_id,
            tenant_id=tenant_id,
            limit=limit,
            entity_type="app_template",
            joins=[
                # App templates don't have user_id, they are global entities
                # No joins needed for templates
            ],
            extra_columns=[
                # No user_id or owner information for templates
                # Templates are global and don't have owners
            ],
            cursor_data=cursor_data,
        )

    async def update_usage_stats_incremental(
        self, tenant_id: UUID, model_id: Optional[UUID] = None
    ) -> None:
        """Update usage statistics incrementally for changes.
        
        TODO: For large tenants, this should be offloaded to a background job
        using ARQ worker system to avoid blocking API responses.
        """
        try:
            self.logger.info(f"Starting update_usage_stats_incremental for tenant {tenant_id}, model {model_id}")
            
            if model_id:
                # Update specific model
                self.logger.info(f"Updating specific model {model_id} for tenant {tenant_id}")
                await self._update_single_model_stats(model_id, tenant_id)
            else:
                # Update all models for tenant
                self.logger.info(f"Updating all models for tenant {tenant_id}")
                stmt = select(CompletionModels.id, CompletionModels.name).where(
                    CompletionModels.tenant_id == tenant_id
                )
                self.logger.debug(f"Query for completion models: {stmt}")
                
                result = await self.session.execute(stmt)
                model_rows = result.fetchall()
                
                self.logger.info(f"Found {len(model_rows)} completion models for tenant {tenant_id}")
                
                # Log details of each model
                for model_row in model_rows:
                    self.logger.info(f"  - Model ID: {model_row.id}, Name: {model_row.name}")
                
                model_ids = [row.id for row in model_rows]
                
                if not model_ids:
                    self.logger.warning(f"No completion models found for tenant {tenant_id}")
                    return
                
                for i, mid in enumerate(model_ids, 1):
                    self.logger.info(f"Processing model {i}/{len(model_ids)}: {mid}")
                    await self._update_single_model_stats(mid, tenant_id)
                    self.logger.info(f"Completed processing model {i}/{len(model_ids)}: {mid}")
            
            self.logger.info(
                "Incremental usage stats update completed successfully",
                extra={"tenant_id": str(tenant_id), "model_id": str(model_id) if model_id else "all"}
            )
            
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error while updating usage stats incrementally",
                extra={"tenant_id": str(tenant_id), "model_id": str(model_id), "error": str(e), "error_type": "database"},
                exc_info=True
            )
            raise
        except Exception as e:
            self.logger.error(
                "Unexpected error while updating usage stats incrementally",
                extra={"tenant_id": str(tenant_id), "model_id": str(model_id), "error": str(e), "error_type": "unexpected"},
                exc_info=True
            )
            raise

    async def recalculate_all_usage_stats(self, tenant_id: UUID) -> None:
        """Perform full recalculation of all usage statistics.
        
        TODO: This is a heavy operation that should definitely be run
        as a background job for production use with 10k+ users.
        """
        self.logger.info(f"Starting recalculate_all_usage_stats for tenant {tenant_id}")
        
        # Get all models enabled for tenant through CompletionModelSettings
        # This is done in a separate read-only transaction
        model_ids = []
        async with self.session.begin():
            stmt = select(CompletionModels.id, CompletionModels.name).join(
                CompletionModelSettings,
                CompletionModels.id == CompletionModelSettings.completion_model_id
            ).where(
                CompletionModelSettings.tenant_id == tenant_id,
                CompletionModelSettings.is_org_enabled == True
            )
            self.logger.debug(f"Query for completion models: {stmt}")
            
            result = await self.session.execute(stmt)
            model_rows = result.fetchall()
            
            self.logger.info(f"Found {len(model_rows)} completion models for tenant {tenant_id}")
            
            # Log details of each model
            for model_row in model_rows:
                self.logger.info(f"  - Model ID: {model_row.id}, Name: {model_row.name}")
            
            model_ids = [row.id for row in model_rows]
        
        if not model_ids:
            self.logger.warning(f"No completion models found for tenant {tenant_id}")
            return
        
        self.logger.info(f"Starting recalculation for {len(model_ids)} models")
        
        # Process each model in its own transaction for better isolation
        processed_count = 0
        failed_count = 0
        
        for i, model_id in enumerate(model_ids, 1):
            try:
                self.logger.info(f"Processing model {i}/{len(model_ids)}: {model_id}")
                
                # Each model gets its own transaction to prevent one failure from affecting others
                async with self.session.begin():
                    await self._recalculate_model_stats(model_id, tenant_id)
                
                processed_count += 1
                self.logger.info(f"Successfully completed processing model {i}/{len(model_ids)}: {model_id}")
                
            except Exception as e:
                failed_count += 1
                self.logger.error(
                    f"Failed to recalculate stats for model {model_id} (tenant {tenant_id})",
                    extra={
                        "tenant_id": str(tenant_id),
                        "model_id": str(model_id),
                        "error": str(e),
                        "error_type": type(e).__name__
                    },
                    exc_info=True
                )
                # Continue with other models even if one fails
                continue
        
        if failed_count > 0:
            self.logger.warning(
                f"Usage stats recalculation completed with errors: {processed_count} successful, {failed_count} failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "processed_count": processed_count,
                    "failed_count": failed_count,
                    "total_models": len(model_ids)
                }
            )
        else:
            self.logger.info(
                "Full usage stats recalculation completed successfully",
                extra={
                    "tenant_id": str(tenant_id),
                    "model_count": len(model_ids),
                    "processed_count": processed_count
                }
            )

    async def recalculate_all_usage_stats_in_transaction(self, tenant_id: UUID) -> None:
        """Perform full recalculation of all usage statistics within an existing transaction.
        
        This method is designed to be called from sysadmin endpoints that already
        have an active transaction, so it doesn't start its own transactions.
        """
        self.logger.info(f"Starting recalculate_all_usage_stats_in_transaction for tenant {tenant_id}")
        
        # Get all models enabled for tenant (no transaction needed, we're already in one)
        stmt = select(CompletionModels.id, CompletionModels.name).join(
            CompletionModelSettings,
            CompletionModels.id == CompletionModelSettings.completion_model_id
        ).where(
            CompletionModelSettings.tenant_id == tenant_id,
            CompletionModelSettings.is_org_enabled == True
        )
        self.logger.debug(f"Query for completion models: {stmt}")
        
        result = await self.session.execute(stmt)
        model_rows = result.fetchall()
        
        self.logger.info(f"Found {len(model_rows)} completion models for tenant {tenant_id}")
        
        # Log details of each model
        for model_row in model_rows:
            self.logger.info(f"  - Model ID: {model_row.id}, Name: {model_row.name}")
        
        model_ids = [row.id for row in model_rows]
        
        if not model_ids:
            self.logger.warning(f"No completion models found for tenant {tenant_id}")
            return
        
        self.logger.info(f"Starting recalculation for {len(model_ids)} models")
        
        # Process each model (no transactions needed, we're already in one)
        processed_count = 0
        failed_count = 0
        
        for i, model_id in enumerate(model_ids, 1):
            try:
                self.logger.info(f"Processing model {i}/{len(model_ids)}: {model_id}")
                await self._recalculate_model_stats(model_id, tenant_id)
                processed_count += 1
                self.logger.info(f"Successfully completed processing model {i}/{len(model_ids)}: {model_id}")
                
            except Exception as e:
                failed_count += 1
                self.logger.error(
                    f"Failed to recalculate stats for model {model_id} (tenant {tenant_id})",
                    extra={
                        "tenant_id": str(tenant_id),
                        "model_id": str(model_id),
                        "error": str(e),
                        "error_type": type(e).__name__
                    },
                    exc_info=True
                )
                # Continue with other models even if one fails
                continue
        
        if failed_count > 0:
            self.logger.warning(
                f"Usage stats recalculation completed with errors: {processed_count} successful, {failed_count} failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "processed_count": processed_count,
                    "failed_count": failed_count,
                    "total_models": len(model_ids)
                }
            )
        else:
            self.logger.info(
                "Full usage stats recalculation completed successfully",
                extra={
                    "tenant_id": str(tenant_id),
                    "model_count": len(model_ids),
                    "processed_count": processed_count
                }
            )

    async def _update_single_model_stats(self, model_id: UUID, tenant_id: UUID) -> None:
        """Update statistics for a single model."""
        self.logger.info(f"Starting _update_single_model_stats for model {model_id}, tenant {tenant_id}")
        
        # Check if stats record exists
        stmt = select(CompletionModelUsageStats).where(
            and_(
                CompletionModelUsageStats.model_id == model_id,
                CompletionModelUsageStats.tenant_id == tenant_id,
            )
        )
        result = await self.session.execute(stmt)
        stats = result.scalar_one_or_none()
        
        if not stats:
            # Create new stats record
            self.logger.info(f"No existing stats found for model {model_id}, creating new record")
            stats = CompletionModelUsageStats(
                model_id=model_id,
                tenant_id=tenant_id,
            )
            self.session.add(stats)
        else:
            self.logger.info(f"Found existing stats for model {model_id}, updating")
        
        # Update counts
        self.logger.info(f"Starting count updates for model {model_id}")
        await self._update_stats_counts(stats, model_id, tenant_id)
        self.logger.info(f"Completed _update_single_model_stats for model {model_id}")

    async def _recalculate_model_stats(self, model_id: UUID, tenant_id: UUID) -> None:
        """Recalculate statistics for a single model from scratch."""
        self.logger.info(f"Starting _recalculate_model_stats for model {model_id}, tenant {tenant_id}")
        
        # Use UPSERT pattern to avoid unique constraint violations
        # First, insert or update with zeroed stats
        stmt = (
            insert(CompletionModelUsageStats)
            .values(
                model_id=model_id,
                tenant_id=tenant_id,
                assistants_count=0,
                apps_count=0,
                services_count=0,
                questions_count=0,
                assistant_templates_count=0,
                app_templates_count=0,
                spaces_count=0,
                total_usage=0,
                last_updated=func.now(),
            )
            .on_conflict_do_update(
                index_elements=['model_id', 'tenant_id'],
                set_={
                    'assistants_count': 0,
                    'apps_count': 0,
                    'services_count': 0,
                    'questions_count': 0,
                    'assistant_templates_count': 0,
                    'app_templates_count': 0,
                    'spaces_count': 0,
                    'total_usage': 0,
                    'last_updated': func.now(),
                }
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()  # Ensure upsert is processed
        
        self.logger.info(f"Upserted stats record for model {model_id}")
        
        # Now get the stats record and calculate actual counts
        select_stmt = select(CompletionModelUsageStats).where(
            and_(
                CompletionModelUsageStats.model_id == model_id,
                CompletionModelUsageStats.tenant_id == tenant_id,
            )
        )
        result = await self.session.execute(select_stmt)
        stats = result.scalar_one()
        
        # Calculate actual counts
        self.logger.info(f"Starting count calculations for model {model_id}")
        await self._update_stats_counts(stats, model_id, tenant_id)
        self.logger.info(f"Completed _recalculate_model_stats for model {model_id}")

    async def _update_stats_counts(
        self, stats: CompletionModelUsageStats, model_id: UUID, tenant_id: UUID
    ) -> None:
        """Update all counts for a stats record."""
        self.logger.info(f"Starting _update_stats_counts for model {model_id}, tenant {tenant_id}")
        
        # Create all count queries
        assistants_stmt = select(func.count()).select_from(Assistants).join(
            Spaces, Assistants.space_id == Spaces.id
        ).where(
            and_(
                Assistants.completion_model_id == model_id,
                Spaces.tenant_id == tenant_id,
            )
        )
        self.logger.debug(f"Assistants query: {assistants_stmt}")
        
        apps_stmt = select(func.count()).select_from(Apps).where(
            and_(
                Apps.completion_model_id == model_id,
                Apps.tenant_id == tenant_id,
            )
        )
        self.logger.debug(f"Apps query: {apps_stmt}")
        
        services_stmt = select(func.count()).select_from(Services).join(
            Spaces, Services.space_id == Spaces.id
        ).where(
            and_(
                Services.completion_model_id == model_id,
                Spaces.tenant_id == tenant_id,
            )
        )
        self.logger.debug(f"Services query: {services_stmt}")
        
        questions_stmt = select(func.count()).select_from(Questions).where(
            and_(
                Questions.completion_model_id == model_id,
                Questions.tenant_id == tenant_id,
            )
        )
        self.logger.debug(f"Questions query: {questions_stmt}")
        
        assistant_templates_stmt = select(func.count()).select_from(AssistantTemplates).where(
            AssistantTemplates.completion_model_id == model_id
        )
        self.logger.debug(f"Assistant templates query: {assistant_templates_stmt}")
        
        app_templates_stmt = select(func.count()).select_from(AppTemplates).where(
            AppTemplates.completion_model_id == model_id
        )
        self.logger.debug(f"App templates query: {app_templates_stmt}")
        
        # Count spaces (many-to-many relationship)
        spaces_stmt = select(func.count(func.distinct(Spaces.id))).select_from(Spaces).join(
            SpacesCompletionModels,
            and_(
                SpacesCompletionModels.space_id == Spaces.id,
                SpacesCompletionModels.completion_model_id == model_id,
            )
        ).where(
            Spaces.tenant_id == tenant_id
        )
        self.logger.debug(f"Spaces query: {spaces_stmt}")
        
        # Execute all queries sequentially (asyncpg doesn't support concurrent queries on same session)
        self.logger.info(f"Executing count queries for model {model_id}")
        assistants_result = await self.session.execute(assistants_stmt)
        apps_result = await self.session.execute(apps_stmt)
        services_result = await self.session.execute(services_stmt)
        questions_result = await self.session.execute(questions_stmt)
        assistant_templates_result = await self.session.execute(assistant_templates_stmt)
        app_templates_result = await self.session.execute(app_templates_stmt)
        spaces_result = await self.session.execute(spaces_stmt)
        
        # Group results for processing
        results = [
            assistants_result,
            apps_result,
            services_result,
            questions_result,
            assistant_templates_result,
            app_templates_result,
            spaces_result,
        ]
        
        # Assign results with detailed logging
        assistants_count = results[0].scalar_one()
        apps_count = results[1].scalar_one()
        services_count = results[2].scalar_one()
        questions_count = results[3].scalar_one()
        assistant_templates_count = results[4].scalar_one()
        app_templates_count = results[5].scalar_one()
        spaces_count = results[6].scalar_one()
        
        # Log individual counts
        self.logger.info(f"Count results for model {model_id}:")
        self.logger.info(f"  - Assistants: {assistants_count}")
        self.logger.info(f"  - Apps: {apps_count}")
        self.logger.info(f"  - Services: {services_count}")
        self.logger.info(f"  - Questions: {questions_count}")
        self.logger.info(f"  - Assistant Templates: {assistant_templates_count}")
        self.logger.info(f"  - App Templates: {app_templates_count}")
        self.logger.info(f"  - Spaces: {spaces_count}")
        
        # Assign to stats object
        stats.assistants_count = assistants_count
        stats.apps_count = apps_count
        stats.services_count = services_count
        stats.questions_count = questions_count
        stats.assistant_templates_count = assistant_templates_count
        stats.app_templates_count = app_templates_count
        stats.spaces_count = spaces_count
        
        # Calculate total - only count entities that actually use the model
        # Excludes questions (individual conversations), templates (global), and spaces (availability only)
        total_usage = (
            assistants_count +    # Assistants configured to use this model
            apps_count +         # Apps configured to use this model  
            services_count       # Services configured to use this model
            # Spaces excluded - they define availability, not usage
            # Questions excluded - they are usage instances, not configured entities
            # Templates excluded - they are global, not tenant-specific
        )
        
        # Validate the calculation
        expected_total = assistants_count + apps_count + services_count
        if total_usage != expected_total:
            self.logger.error(
                f"CALCULATION ERROR: total_usage={total_usage} != expected_total={expected_total} "
                f"for model {model_id}, tenant {tenant_id}"
            )
            # Force correct calculation
            total_usage = expected_total
        
        stats.total_usage = total_usage
        
        self.logger.info(f"Total entities that use model {model_id}: {total_usage} (assistants: {assistants_count}, apps: {apps_count}, services: {services_count})")
        self.logger.info(f"Additional metrics tracked separately - Spaces: {spaces_count}, Questions: {questions_count}, Assistant Templates: {assistant_templates_count}, App Templates: {app_templates_count}")
        
        # Update timestamp
        stats.last_updated = datetime.utcnow()
        
        # Final verification of data integrity
        verification_total = stats.assistants_count + stats.apps_count + stats.services_count
        if stats.total_usage != verification_total:
            self.logger.error(
                f"DATA INTEGRITY ERROR: stats.total_usage={stats.total_usage} != "
                f"verification_total={verification_total} for model {model_id}, tenant {tenant_id}"
            )
            # Force correct value
            stats.total_usage = verification_total
        
        self.logger.info(f"Completed _update_stats_counts for model {model_id} - Total configured entities: {stats.total_usage}")
        self.logger.info(f"Final verification: assistants={stats.assistants_count}, apps={stats.apps_count}, services={stats.services_count}, total={stats.total_usage}")