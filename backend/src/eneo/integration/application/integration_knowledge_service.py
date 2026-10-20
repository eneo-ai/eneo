from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast
from uuid import UUID, uuid4

from typing_extensions import TypedDict

from eneo.authentication.auth_models import is_service_api_key
from eneo.integration.domain.entities.integration_knowledge import (
    KNOWLEDGE_NAME_LENGTH_REASON,
    KNOWLEDGE_NAME_MAX_LENGTH,
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.task_params import (
    ConfluenceContentTaskParam,
    SharepointContentTaskParam,
)
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.content_service.types import (
    SharePointTokenProtocol,
)
from eneo.integration.infrastructure.detached_tasks import run_after_commit
from eneo.jobs.job_models import JobInDb, Task
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.logging import get_logger
from eneo.observability.error_text import user_visible_error
from eneo.roles.permissions import Permission
from eneo.spaces.space_repo import INTEGRATION_KNOWLEDGE_SOURCE

if TYPE_CHECKING:
    from eneo.actors import ActorManager
    from eneo.embedding_models.domain.embedding_model import EmbeddingModel
    from eneo.embedding_models.domain.embedding_model_repo import (
        EmbeddingModelRepository,
    )
    from eneo.integration.application.user_integration_service import (
        UserIntegrationService,
    )
    from eneo.integration.domain.entities.tenant_sharepoint_app import (
        TenantSharePointApp,
    )
    from eneo.integration.domain.entities.user_integration import UserIntegration
    from eneo.integration.domain.repositories.integration_knowledge_repo import (
        IntegrationKnowledgeLocation,
        IntegrationKnowledgeRepository,
    )
    from eneo.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from eneo.integration.infrastructure.auth_service.org_token_provider import (
        OrgTokenProvider,
    )
    from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
        ServiceAccountAuthService,
    )
    from eneo.integration.infrastructure.auth_service.tenant_app_auth_service import (
        TenantAppAuthService,
    )
    from eneo.integration.infrastructure.sharepoint_subscription_service import (
        SharePointSubscriptionService,
    )
    from eneo.jobs.job_service import JobService
    from eneo.jobs.task_models import TaskParams
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.users.user import UserInDB


logger = get_logger(__name__)


class BatchIntegrationKnowledgeCreateItem(TypedDict):
    name: str
    key: str | None
    url: str
    folder_id: str | None
    folder_path: str | None
    selected_item_type: str | None
    resource_type: str | None


class BatchIntegrationKnowledgeCreateResult(TypedDict):
    index: int
    name: str
    status: str
    knowledge: "IntegrationKnowledge | None"
    integration_knowledge_id: UUID | None
    job: "JobInDb | None"
    error: str | None


class SpaceItem(NamedTuple):
    """An item as its space showed it before a change, with that space."""

    space: "Space"
    knowledge: IntegrationKnowledge


@dataclass(frozen=True)
class _ImportContext:
    """What every item of one import shares, resolved before anything is written."""

    space_id: UUID
    space: "Space"
    user_integration: "UserIntegration"
    embedding_model: "EmbeddingModel"
    token: "SimpleToken | OauthToken"
    token_id: UUID | None
    tenant_app_id: UUID | None


@dataclass(frozen=True)
class _PendingDispatch:
    """A queued job row whose hand-over to the worker waits for the commit."""

    task: Task
    job_id: UUID
    params: "TaskParams"


def _failed_batch_item(
    index: int, item: BatchIntegrationKnowledgeCreateItem, error: str
) -> BatchIntegrationKnowledgeCreateResult:
    return BatchIntegrationKnowledgeCreateResult(
        index=index,
        name=item["name"],
        status="failed",
        knowledge=None,
        integration_knowledge_id=None,
        job=None,
        error=error,
    )


class SubscriptionCleanupInfo(TypedDict):
    subscription_id: UUID
    token: "SimpleToken | OauthToken"


class SimpleToken:
    """Simple token wrapper for subscription service compatibility.

    Used for tenant_app integrations where we don't have an OauthToken
    in the database, but need a token object with access_token attribute.
    """

    def __init__(self, access_token: str):
        super().__init__()
        self.access_token = access_token
        self.base_url = "https://graph.microsoft.com"
        self.token_type = IntegrationType.Sharepoint


def _as_sharepoint_token(token: SimpleToken | OauthToken) -> SharePointTokenProtocol:
    if isinstance(token, SimpleToken):
        return token
    if token.is_sharepoint:
        return cast(SharePointTokenProtocol, token)
    raise BadRequestException("Expected a SharePoint token")


class TenantSharePointAppRepositoryProtocol(Protocol):
    async def one(self, *, id: UUID) -> "TenantSharePointApp": ...

    async def update(self, obj: "TenantSharePointApp") -> "TenantSharePointApp": ...


class IntegrationKnowledgeService:
    def __init__(
        self,
        job_service: "JobService",
        user: "UserInDB",
        oauth_token_repo: "OauthTokenRepository",
        space_repo: "SpaceRepository",
        integration_knowledge_repo: "IntegrationKnowledgeRepository",
        embedding_model_repo: "EmbeddingModelRepository",
        user_integration_service: "UserIntegrationService",
        actor_manager: "ActorManager",
        sharepoint_subscription_service: "SharePointSubscriptionService",
        tenant_sharepoint_app_repo: TenantSharePointAppRepositoryProtocol,
        tenant_app_auth_service: "TenantAppAuthService",
        org_token_provider: "OrgTokenProvider",
        service_account_auth_service: "ServiceAccountAuthService | None" = None,
    ) -> None:
        super().__init__()
        self.job_service = job_service
        self.user = user
        self.oauth_token_repo = oauth_token_repo
        self.space_repo = space_repo
        self.integration_knowledge_repo = integration_knowledge_repo
        self.embedding_model_repo = embedding_model_repo
        self.user_integration_service = user_integration_service
        self.actor_manager = actor_manager
        self.sharepoint_subscription_service = sharepoint_subscription_service
        self.tenant_sharepoint_app_repo: TenantSharePointAppRepositoryProtocol = (
            tenant_sharepoint_app_repo
        )
        self.tenant_app_auth_service = tenant_app_auth_service
        self.service_account_auth_service = service_account_auth_service
        self.org_token_provider = org_token_provider

    async def require_sync_log_access(self, integration_knowledge_id: UUID) -> None:
        """Sync history follows knowledge read access, not connection ownership."""
        if is_service_api_key(self.user):
            owner = await self.space_repo.get_knowledge_source_owner_access(
                INTEGRATION_KNOWLEDGE_SOURCE, integration_knowledge_id
            )
            access = [owner] if owner is not None else []
        else:
            access = await self.space_repo.get_knowledge_source_read_access(
                INTEGRATION_KNOWLEDGE_SOURCE, integration_knowledge_id
            )
        for space in access:
            actor = self.actor_manager.get_space_actor(space)
            if actor.can_read_space() and actor.can_read_integrations():
                return
        raise NotFoundException("Integration knowledge not found")

    async def get_readable_knowledge(
        self, space_id: UUID, integration_knowledge_id: UUID
    ) -> IntegrationKnowledgeLocation:
        """Where an item seen from a space keeps its documents, for anyone who
        may read the space's integrations."""
        await self.require_readable_knowledge(space_id, integration_knowledge_id)
        return await self.integration_knowledge_repo.get_location(
            integration_knowledge_id
        )

    async def require_readable_knowledge(
        self, space_id: UUID, integration_knowledge_id: UUID
    ) -> None:
        """Raise unless the caller may read the space's integrations (403) and
        the space shows the item (404, as for an unknown space).

        Membership is checked before the item is looked up so a non-member
        cannot probe which items a space holds.
        """
        if integration_knowledge_id not in await self.list_readable_knowledge_ids(
            space_id
        ):
            raise NotFoundException()

    async def list_readable_knowledge_ids(self, space_id: UUID) -> list[UUID]:
        """Ids of the items a space shows, for anyone who may read its integrations.

        Reads the caller's access facts and the ids only: the source pages
        poll this and ask once per folder, and the space aggregate loads
        every member, assistant and source of the space.
        """
        facts = await self.space_repo.get_space_access_facts(space_id)
        actor = self.actor_manager.get_space_actor(facts)
        if not (actor.can_read_space() and actor.can_read_integrations()):
            raise UnauthorizedException()
        return await self.space_repo.get_visible_integration_knowledge_ids(
            space_id, facts.tenant_space_id
        )

    async def _get_tenant_app_access_token(
        self, tenant_app: "TenantSharePointApp"
    ) -> str:
        """Resolve tenant app access token and persist service-account token rotation."""
        return await self.org_token_provider.get_access_token(tenant_app)

    async def create_space_integration_knowledge(
        self,
        user_integration_id: UUID,
        name: str,
        embedding_model_id: UUID,
        space_id: UUID,
        key: str | None,
        url: str,
        folder_id: str | None = None,
        folder_path: str | None = None,
        selected_item_type: str | None = None,
        resource_type: str = "site",
        wrapper_id: UUID | None = None,
        wrapper_name: str | None = None,
    ) -> tuple[IntegrationKnowledge, "JobInDb"]:
        context = await self._prepare_import(
            user_integration_id=user_integration_id,
            embedding_model_id=embedding_model_id,
            space_id=space_id,
        )
        knowledge, job, dispatch = await self._import(
            context,
            name=name,
            key=key,
            url=url,
            folder_id=folder_id,
            folder_path=folder_path,
            selected_item_type=selected_item_type,
            resource_type=resource_type,
            wrapper_id=wrapper_id,
            wrapper_name=wrapper_name,
        )
        await self.job_service.dispatch_after_commit(
            dispatch.task, dispatch.job_id, dispatch.params
        )
        return knowledge, job

    async def _prepare_import(
        self,
        *,
        user_integration_id: UUID,
        embedding_model_id: UUID,
        space_id: UUID,
    ) -> _ImportContext:
        """Everything an import needs that can fail, checked before any write."""
        space = await self.space_repo.one(id=space_id)

        connection = await self.user_integration_service.get_authorized_integration(
            user_integration_id, space=space
        )
        user_integration = connection.integration

        if not space.is_embedding_model_in_space(embedding_model_id=embedding_model_id):
            raise BadRequestException("No valid embedding model")

        if user_integration.integration_type not in ("sharepoint", "confluence"):
            raise BadRequestException("Unknown integration type")

        embedding_model = await self.embedding_model_repo.one(
            model_id=embedding_model_id
        )

        if connection.tenant_app is not None:
            access_token = await self._get_tenant_app_access_token(
                connection.tenant_app
            )
            return _ImportContext(
                space_id=space_id,
                space=space,
                user_integration=user_integration,
                embedding_model=embedding_model,
                token=SimpleToken(access_token=access_token),
                token_id=None,
                tenant_app_id=connection.tenant_app.id,
            )
        oauth_token = await self.oauth_token_repo.one(
            user_integration_id=user_integration_id
        )
        if (
            user_integration.integration_type == "confluence"
            and not oauth_token.token_type.is_confluence
        ):
            raise BadRequestException("Expected a Confluence token")
        return _ImportContext(
            space_id=space_id,
            space=space,
            user_integration=user_integration,
            embedding_model=embedding_model,
            token=oauth_token,
            token_id=oauth_token.id,
            tenant_app_id=None,
        )

    async def _import(
        self,
        context: _ImportContext,
        *,
        name: str,
        key: str | None,
        url: str,
        folder_id: str | None,
        folder_path: str | None,
        selected_item_type: str | None,
        resource_type: str,
        wrapper_id: UUID | None,
        wrapper_name: str | None,
    ) -> tuple[IntegrationKnowledge, "JobInDb", _PendingDispatch]:
        """Write one item and its first sync's job row.

        The job is not handed to the worker here: the caller dispatches it
        once the item's writes are kept (``JobService.dispatch_after_commit``),
        so an item rolled back later never leaves the worker a job.
        """
        if not key:
            raise BadRequestException("Integration key is required")
        name = name.strip()
        if not name or len(name) > KNOWLEDGE_NAME_MAX_LENGTH:
            raise BadRequestException(KNOWLEDGE_NAME_LENGTH_REASON)

        space = context.space
        user_integration = context.user_integration
        user_integration_id = user_integration.id
        is_sharepoint = user_integration.integration_type == "sharepoint"
        if is_sharepoint and resource_type == "onedrive":
            site_id_value, drive_id_value = None, key
        elif is_sharepoint:
            site_id_value, drive_id_value = key, None
        else:
            site_id_value, drive_id_value = None, None

        knowledge = await self.integration_knowledge_repo.add(
            obj=IntegrationKnowledge(
                name=name,
                original_name=name,
                space_id=context.space_id,
                embedding_model=context.embedding_model,
                user_integration=user_integration,
                tenant_id=self.user.tenant_id,
                url=url,
                site_id=site_id_value,
                drive_id=drive_id_value,
                resource_type=resource_type,
                folder_id=folder_id,
                folder_path=folder_path,
                selected_item_type=selected_item_type,
                wrapper_id=wrapper_id,
                wrapper_name=wrapper_name,
            )
        )

        await self._distribute_knowledge_if_org_space(knowledge, space)

        if not is_sharepoint:
            if context.token_id is None:
                raise BadRequestException("Confluence token ID is required")
            task = Task.PULL_CONFLUENCE_CONTENT
            params: TaskParams = ConfluenceContentTaskParam(
                user_id=self.user.id,
                id=user_integration_id,
                token_id=context.token_id,
                space_key=key,
                integration_knowledge_id=knowledge.id,
            )
        else:
            task = Task.PULL_SHAREPOINT_CONTENT
            params = SharepointContentTaskParam(
                user_id=self.user.id,
                id=user_integration_id,
                token_id=context.token_id,
                tenant_app_id=context.tenant_app_id,
                integration_knowledge_id=knowledge.id,
                site_id=site_id_value,
                drive_id=drive_id_value,
                folder_id=folder_id,
                folder_path=folder_path,
                resource_type=resource_type,
            )
        job = await self.job_service.queue_job(
            task=task, name=name, task_params=params, enqueue=False
        )
        if is_sharepoint:
            await self._link_subscription_on_import(
                context, knowledge, key=key, is_onedrive=resource_type == "onedrive"
            )
        return knowledge, job, _PendingDispatch(task, job.id, params)

    async def _link_subscription_on_import(
        self,
        context: _ImportContext,
        knowledge: IntegrationKnowledge,
        *,
        key: str,
        is_onedrive: bool,
    ) -> None:
        """Register the change-notification subscription; a failure only logs.

        A savepoint keeps a failed statement from aborting the transaction the
        item was written in.
        """
        logger.info(
            "Ensuring %s subscription for knowledge %s (%s=%s)",
            "drive-level" if is_onedrive else "site-level",
            knowledge.id,
            "drive" if is_onedrive else "site",
            key[:30],
        )
        try:
            async with self.space_repo.session.begin_nested():
                subscription = await self.sharepoint_subscription_service.ensure_subscription_for_site(
                    user_integration_id=context.user_integration.id,
                    site_id=key,
                    token=_as_sharepoint_token(context.token),
                    is_onedrive=is_onedrive,
                )
                if not subscription:
                    logger.warning(
                        "Could not create/reuse subscription for %s %s (webhook URL may not be configured)",
                        "drive" if is_onedrive else "site",
                        key[:30],
                    )
                    return
                await self.integration_knowledge_repo.link_subscription(
                    knowledge.id, subscription.id
                )
                knowledge.sharepoint_subscription_id = subscription.id
                logger.info(
                    "Successfully linked knowledge %s to subscription %s",
                    knowledge.id,
                    subscription.subscription_id,
                )
        except Exception as exc:
            logger.warning(
                "Failed to ensure subscription for knowledge %s: %s",
                knowledge.id,
                exc,
                exc_info=True,
            )

    async def create_space_integration_knowledge_batch(
        self,
        user_integration_id: UUID,
        embedding_model_id: UUID,
        space_id: UUID,
        items: list[BatchIntegrationKnowledgeCreateItem],
        wrapper_name: str | None = None,
    ) -> list[BatchIntegrationKnowledgeCreateResult]:
        """Create several items in one request; a failed item leaves nothing behind.

        Access, the embedding model and the token are checked once, before any
        write; when that fails, the request fails with that error and nothing
        is written. Each item is then written in its own savepoint, so an item
        that fails part-way is rolled back alone, and its job is dispatched
        only after its savepoint is released.
        """
        normalized_wrapper_name = (
            wrapper_name.strip() if wrapper_name and wrapper_name.strip() else None
        )
        batch_wrapper_id = uuid4() if len(items) > 1 else None
        batch_wrapper_name = normalized_wrapper_name if batch_wrapper_id else None

        context = await self._prepare_import(
            user_integration_id=user_integration_id,
            embedding_model_id=embedding_model_id,
            space_id=space_id,
        )

        results: list[BatchIntegrationKnowledgeCreateResult] = []
        for index, item in enumerate(items):
            try:
                async with self.space_repo.session.begin_nested():
                    knowledge, job, dispatch = await self._import(
                        context,
                        name=item["name"],
                        key=item.get("key"),
                        url=item["url"],
                        folder_id=item.get("folder_id"),
                        folder_path=item.get("folder_path"),
                        selected_item_type=item.get("selected_item_type"),
                        resource_type=item.get("resource_type") or "site",
                        wrapper_id=batch_wrapper_id,
                        wrapper_name=batch_wrapper_name,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to create integration knowledge batch item at index %s: %s",
                    index,
                    exc,
                    exc_info=True,
                )
                results.append(_failed_batch_item(index, item, user_visible_error(exc)))
                continue
            await self.job_service.dispatch_after_commit(
                dispatch.task, dispatch.job_id, dispatch.params
            )
            results.append(
                BatchIntegrationKnowledgeCreateResult(
                    index=index,
                    name=item["name"],
                    status="created",
                    knowledge=knowledge,
                    integration_knowledge_id=knowledge.id,
                    job=job,
                    error=None,
                )
            )

        return results

    async def _distribute_knowledge_if_org_space(
        self, knowledge: IntegrationKnowledge, space: "Space"
    ) -> None:
        """Distribute integration knowledge to child spaces if created on org space.

        This mirrors the behavior of collections and websites. When integration knowledge
        is created on an organization space (tenant_space_id IS NULL), it's automatically
        made available to all child spaces via the IntegrationKnowledgesSpaces junction table.
        """
        import sqlalchemy as sa
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from eneo.database.tables.integration_knowledge_spaces_table import (
            IntegrationKnowledgesSpaces,
        )
        from eneo.database.tables.spaces_table import Spaces as SpacesTable

        # Only distribute if this is an org space (no parent tenant_space_id)
        if space.tenant_space_id is not None:
            return

        # Get all child spaces for this tenant
        child_spaces = await self.space_repo.session.scalars(
            sa.select(SpacesTable.id).where(
                SpacesTable.tenant_id == space.tenant_id,
                SpacesTable.tenant_space_id == space.id,
            )
        )

        child_space_ids = child_spaces.all()

        if not child_space_ids:
            return

        # Insert distribution records
        ins = (
            pg_insert(IntegrationKnowledgesSpaces)
            .values(
                [
                    dict(integration_knowledge_id=knowledge.id, space_id=space_id)
                    for space_id in child_space_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IntegrationKnowledgesSpaces.integration_knowledge_id,
                    IntegrationKnowledgesSpaces.space_id,
                ]
            )
        )
        await self.space_repo.session.execute(ins)

    async def remove_knowledge(
        self,
        space_id: "UUID",
        integration_knowledge_id: "UUID",
    ) -> SpaceItem:
        """Remove an item from the space it was created in; returns what was
        removed, for the audit log."""
        space = await self.space_repo.one(id=space_id)

        # Membership is checked before the item is looked up so a non-member
        # cannot probe which items a space holds.
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_delete_integrations():
            raise UnauthorizedException(
                "User does not have permission to remove integration knowledge "
                "from this space"
            )

        knowledge = space.get_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )
        await self._remove_from_space(space, knowledge)
        return SpaceItem(space, knowledge)

    async def _remove_from_space(
        self, space: "Space", knowledge: IntegrationKnowledge
    ) -> None:
        """Delete ``knowledge`` as seen from ``space``; the caller checked delete access."""
        import sqlalchemy as sa

        from eneo.database.tables.integration_knowledge_spaces_table import (
            IntegrationKnowledgesSpaces,
        )

        # SECURITY: tenant_app integrations require admin permission
        if knowledge.user_integration.auth_type == "tenant_app":
            if Permission.ADMIN not in self.user.permissions:
                raise UnauthorizedException(
                    "Admin permission is required to delete organization-wide SharePoint integrations. "
                    "Please contact your administrator."
                )

        # Check if knowledge belongs to this space
        # Only allow deletion from the space where it was created
        if knowledge.space_id != space.id:
            raise UnauthorizedException(
                "Cannot delete knowledge from this space. "
                "This knowledge belongs to another space and must be deleted from there."
            )

        # Remove distribution records if this is an org space
        if space.tenant_space_id is None:
            await self.space_repo.session.execute(
                sa.delete(IntegrationKnowledgesSpaces).where(
                    IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
                )
            )

        # Prepare subscription cleanup info BEFORE database delete
        # We need to get the token while the transaction is still open
        subscription_cleanup_info: SubscriptionCleanupInfo | None = None
        subscription_id = knowledge.sharepoint_subscription_id
        if subscription_id and knowledge.integration_type == "sharepoint":
            try:
                user_integration = knowledge.user_integration
                if user_integration.auth_type == "tenant_app":
                    if not user_integration.tenant_app_id:
                        raise BadRequestException(
                            "Tenant app ID is required for tenant_app integrations"
                        )

                    tenant_app = await self.tenant_sharepoint_app_repo.one(
                        id=user_integration.tenant_app_id
                    )
                    access_token = await self._get_tenant_app_access_token(tenant_app)
                    token: SimpleToken | OauthToken = SimpleToken(
                        access_token=access_token
                    )
                else:
                    token = await self.oauth_token_repo.one(
                        user_integration_id=knowledge.user_integration.id
                    )

                subscription_cleanup_info = {
                    "subscription_id": subscription_id,
                    "token": token,
                }
            except Exception as exc:
                logger.warning(
                    "Failed to prepare subscription cleanup for %s: %s",
                    subscription_id,
                    exc,
                    exc_info=True,
                )

        # Delete from database FIRST (within transaction)
        await self.integration_knowledge_repo.remove(id=knowledge.id)

        # The Graph call runs after this transaction commits, on a session of
        # its own: the request session is closed by then, and the reference
        # count must see the deleted row. A failure here is retried by the
        # daily orphan cleanup job.
        if subscription_cleanup_info:
            cleanup_subscription_id = subscription_cleanup_info["subscription_id"]
            cleanup_token = _as_sharepoint_token(subscription_cleanup_info["token"])
            run_after_commit(
                self.space_repo.session,
                lambda: self.sharepoint_subscription_service.delete_subscription_if_unused_detached(
                    subscription_id=cleanup_subscription_id,
                    token=cleanup_token,
                ),
            )

    async def trigger_full_sync(
        self,
        space_id: UUID,
        integration_knowledge_id: UUID,
    ) -> tuple["JobInDb", SpaceItem]:
        """Trigger a full resync for an existing SharePoint integration knowledge.

        Returns the job and the item synced, for the audit log.
        """
        space = await self.space_repo.one(id=space_id)
        # Membership before the item, as for a removal.
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_integrations():
            raise UnauthorizedException(
                "User does not have permission to sync integration knowledge in "
                "this space"
            )

        knowledge = space.get_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )

        if knowledge.space_id != space.id:
            raise UnauthorizedException(
                "Cannot sync knowledge from this space. "
                "This knowledge belongs to another space."
            )

        if knowledge.integration_type != "sharepoint":
            raise BadRequestException(
                "Full sync is only supported for SharePoint integrations"
            )

        user_integration = knowledge.user_integration

        if user_integration.auth_type == "tenant_app":
            if Permission.ADMIN not in self.user.permissions:
                raise UnauthorizedException(
                    "Admin permission is required to sync organization-wide SharePoint integrations. "
                    "Please contact your administrator."
                )

            if not user_integration.tenant_app_id:
                raise BadRequestException(
                    "Tenant app ID is required for tenant_app integrations"
                )

            tenant_app = await self.tenant_sharepoint_app_repo.one(
                id=user_integration.tenant_app_id
            )
            access_token = await self._get_tenant_app_access_token(tenant_app)
            subscription_token: SimpleToken | OauthToken = SimpleToken(
                access_token=access_token
            )
            token_id = None
            tenant_app_id = tenant_app.id
        else:
            oauth_token = await self.oauth_token_repo.one(
                user_integration_id=user_integration.id
            )
            subscription_token = oauth_token
            token_id = oauth_token.id
            tenant_app_id = None

        resource_type = knowledge.resource_type or "site"
        is_onedrive = resource_type == "onedrive"
        subscription_resource_id = (
            knowledge.drive_id if is_onedrive else knowledge.site_id
        )

        if subscription_resource_id:
            # A savepoint keeps a failed statement here from aborting the
            # transaction the job is queued in.
            try:
                async with self.space_repo.session.begin_nested():
                    sharepoint_token = _as_sharepoint_token(subscription_token)
                    subscription = await self.sharepoint_subscription_service.ensure_subscription_for_site(
                        user_integration_id=user_integration.id,
                        site_id=subscription_resource_id,
                        token=sharepoint_token,
                        is_onedrive=is_onedrive,
                    )
                    subscription_db_id = (
                        getattr(subscription, "id", None) if subscription else None
                    )
                    existing_subscription_db_id = getattr(
                        knowledge, "sharepoint_subscription_id", None
                    )
                    if (
                        subscription_db_id
                        and existing_subscription_db_id != subscription_db_id
                    ):
                        await self.integration_knowledge_repo.link_subscription(
                            knowledge.id, subscription_db_id
                        )
                        knowledge.sharepoint_subscription_id = subscription_db_id
            except Exception as exc:
                logger.warning(
                    "Failed to ensure SharePoint subscription during full sync "
                    "for knowledge %s: %s",
                    knowledge.id,
                    exc,
                    exc_info=True,
                )
        else:
            logger.warning(
                "Skipping subscription ensure during full sync for knowledge %s: "
                "missing %s identifier",
                knowledge.id,
                "drive" if is_onedrive else "site",
            )

        job = await self.job_service.queue_job(
            task=Task.PULL_SHAREPOINT_CONTENT,
            name=knowledge.name,
            task_params=SharepointContentTaskParam(
                user_id=self.user.id,
                id=user_integration.id,
                token_id=token_id,
                tenant_app_id=tenant_app_id,
                integration_knowledge_id=knowledge.id,
                site_id=knowledge.site_id,
                drive_id=knowledge.drive_id,
                folder_id=knowledge.folder_id,
                folder_path=knowledge.folder_path,
                resource_type=resource_type,
            ),
            after_commit=True,
        )

        return job, SpaceItem(space, knowledge)

    async def update_knowledge_name(
        self,
        space_id: UUID,
        integration_knowledge_id: UUID,
        name: str,
    ) -> IntegrationKnowledge:
        """Update the name of an integration knowledge item."""
        space = await self.space_repo.one(id=space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_integrations():
            raise UnauthorizedException()

        space_knowledge = space.get_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )

        # SECURITY: tenant_app integrations require admin permission
        if space_knowledge.user_integration.auth_type == "tenant_app":
            if Permission.ADMIN not in self.user.permissions:
                raise UnauthorizedException(
                    "Admin permission is required to rename organization-wide SharePoint integrations. "
                    "Please contact your administrator."
                )

        # Only allow renaming from the space where knowledge was created
        if space_knowledge.space_id != space.id:
            raise UnauthorizedException(
                "Cannot rename knowledge from this space. "
                "This knowledge belongs to another space and must be renamed from there."
            )

        await self.integration_knowledge_repo.rename(integration_knowledge_id, name)
        knowledge = await self.integration_knowledge_repo.one(
            id=integration_knowledge_id
        )
        await self.integration_knowledge_repo.attach_document_counts([knowledge])
        return knowledge

    async def _get_owned_wrapper_knowledge(
        self,
        space: "Space",
        wrapper_id: UUID,
    ) -> list[IntegrationKnowledge]:
        wrapper_items = [
            knowledge
            for knowledge in space.integration_knowledge_list
            if getattr(knowledge, "wrapper_id", None) == wrapper_id
        ]

        if not wrapper_items:
            raise NotFoundException("Integration knowledge wrapper not found")

        owned_items = [
            knowledge for knowledge in wrapper_items if knowledge.space_id == space.id
        ]
        if not owned_items:
            raise UnauthorizedException(
                "Cannot manage this wrapper from this space. "
                "It belongs to another space."
            )

        return owned_items

    async def update_wrapper_name(
        self,
        space_id: UUID,
        wrapper_id: UUID,
        name: str,
    ) -> list[IntegrationKnowledge]:
        """Update wrapper_name for all knowledge items in a wrapper."""
        normalized_name = name.strip()
        if not normalized_name:
            raise BadRequestException("Wrapper name cannot be empty")

        space = await self.space_repo.one(id=space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_edit_integrations():
            raise UnauthorizedException()

        owned_items = await self._get_owned_wrapper_knowledge(
            space=space,
            wrapper_id=wrapper_id,
        )

        # SECURITY: tenant_app integrations require admin permission
        if owned_items and owned_items[0].user_integration.auth_type == "tenant_app":
            if Permission.ADMIN not in self.user.permissions:
                raise UnauthorizedException(
                    "Admin permission is required to rename organization-wide SharePoint integrations. "
                    "Please contact your administrator."
                )

        ids = [item.id for item in owned_items]
        await self.integration_knowledge_repo.rename_wrapper(ids, normalized_name)
        by_id = {
            item.id: item
            for item in await self.integration_knowledge_repo.get_by_ids(ids)
        }
        updated_items = [by_id[id] for id in ids if id in by_id]
        await self.integration_knowledge_repo.attach_document_counts(updated_items)

        return updated_items

    async def remove_wrapper_knowledge(
        self,
        space_id: UUID,
        wrapper_id: UUID,
    ) -> None:
        """Delete all owned knowledge items in a wrapper."""
        space = await self.space_repo.one(id=space_id)
        actor = self.actor_manager.get_space_actor_from_space(space)
        if not actor.can_delete_integrations():
            raise UnauthorizedException()

        owned_items = await self._get_owned_wrapper_knowledge(
            space=space,
            wrapper_id=wrapper_id,
        )

        # SECURITY: tenant_app integrations require admin permission
        if owned_items and owned_items[0].user_integration.auth_type == "tenant_app":
            if Permission.ADMIN not in self.user.permissions:
                raise UnauthorizedException(
                    "Admin permission is required to delete organization-wide SharePoint integrations. "
                    "Please contact your administrator."
                )

        for item in list(owned_items):
            await self._remove_from_space(space, item)
