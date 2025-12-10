from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID

from intric.main.exceptions import (
    BadRequestException,
    CrawlAlreadyRunningException,
    UnauthorizedException,
)
from intric.main.logging import get_logger
from intric.main.models import NOT_PROVIDED, NotProvided, Status  # Status used for job status check
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.websites.domain.website import UpdateInterval, Website

logger = get_logger(__name__)

if TYPE_CHECKING:
    from intric.actors.actor_manager import ActorManager
    from intric.spaces.space_repo import SpaceRepository
    from intric.spaces.space_service import SpaceService
    from intric.tenants.tenant_repo import TenantRepository
    from intric.users.user import UserInDB
    from intric.websites.domain.crawl_run import CrawlRun, CrawlType
    from intric.websites.domain.crawl_run_repo import CrawlRunRepository
    from intric.websites.domain.crawl_service import CrawlService


class WebsiteCRUDService:
    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        space_repo: "SpaceRepository",
        crawl_run_repo: "CrawlRunRepository",
        actor_manager: "ActorManager",
        crawl_service: "CrawlService",
        tenant_repo: "TenantRepository",
    ):
        self.user = user
        self.space_service = space_service
        self.space_repo = space_repo
        self.crawl_run_repo = crawl_run_repo
        self.actor_manager = actor_manager
        self.crawl_service = crawl_service
        self.tenant_repo = tenant_repo

    async def create_website(
        self,
        space_id: "UUID",
        url: str,
        name: Optional[str],
        download_files: bool,
        crawl_type: "CrawlType",
        update_interval: UpdateInterval,
        embedding_model_id: Optional["UUID"] = None,
        http_auth_username: Optional[str] = None,
        http_auth_password: Optional[str] = None,
    ) -> Website:
        space = await self.space_service.get_space(space_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_websites():
            raise UnauthorizedException()

        if embedding_model_id is None:
            embedding_model = space.get_default_embedding_model()
            if embedding_model is None:
                raise BadRequestException("No embedding model found")
        else:
            embedding_model = space.get_embedding_model(embedding_model_id)

        website = Website.create(
            space_id=space.id,
            user=self.user,
            url=url,
            name=name,
            download_files=download_files,
            crawl_type=crawl_type,
            update_interval=update_interval,
            embedding_model=embedding_model,
            http_auth_username=http_auth_username,
            http_auth_password=http_auth_password,
        )

        space.add_website(website)
        updated_space = await self.space_repo.update(space=space)
        new_website = updated_space.get_website(website_id=website.id)

        await self.crawl_service.crawl(website=new_website)

        return new_website

    async def get_website(self, id: UUID) -> Website:
        space = await self.space_service.get_space_by_website(id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return space.get_website(website_id=id)

    async def update_website(
        self,
        id: UUID,
        url: Union[str, NotProvided] = NOT_PROVIDED,
        name: Union[str, NotProvided] = NOT_PROVIDED,
        download_files: Union[bool, NotProvided] = NOT_PROVIDED,
        crawl_type: Union["CrawlType", NotProvided] = NOT_PROVIDED,
        update_interval: Union[UpdateInterval, NotProvided] = NOT_PROVIDED,
        http_auth_username: Union[str, None, NotProvided] = NOT_PROVIDED,
        http_auth_password: Union[str, None, NotProvided] = NOT_PROVIDED,
    ) -> Website:
        space = await self.space_service.get_space_by_website(id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_edit_websites():
            raise UnauthorizedException()

        website = space.get_website(website_id=id)

        website.update(
            name=name,
            url=url,
            download_files=download_files,
            crawl_type=crawl_type,
            update_interval=update_interval,
            http_auth_username=http_auth_username,
            http_auth_password=http_auth_password,
        )

        await self.space_repo.update(space=space)

        return website

    async def delete_website(self, id: UUID) -> None:
        owner_space = await self.space_service.get_space_by_website(id)
        owner_actor = self.actor_manager.get_space_actor_from_space(space=owner_space)

        if not owner_actor.can_delete_websites():
            raise UnauthorizedException()

        await self.space_repo.hard_delete_website(website_id=id, owner_space_id=owner_space.id)
        

    async def crawl_website(self, id: UUID) -> bool:
        space = await self.space_service.get_space_by_website(id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_create_websites():
            raise UnauthorizedException()

        website = space.get_website(website_id=id)

        if website.latest_crawl.status in [Status.QUEUED, Status.IN_PROGRESS]:
            # Safe preemption: Check if job is stale (no activity for threshold period)
            preempted = await self._try_preempt_stale_job(website)
            if not preempted:
                # Job is actively running, don't preempt
                raise CrawlAlreadyRunningException()
            # Job was stale and preempted, proceed with new crawl

        return await self.crawl_service.crawl(website=website)

    async def _try_preempt_stale_job(self, website: Website) -> bool:
        """Check if existing crawl job is stale and preempt it if so.

        Safe preemption: If a job hasn't had activity (updated_at) for longer than
        the configured threshold, it's considered stale (crashed worker). We mark it
        as FAILED so the user can immediately start a new crawl.

        Uses atomic Compare-and-Swap to prevent race conditions when multiple
        users click "recrawl" simultaneously on the same stale job.

        Returns:
            True if job was stale and preempted (or already finished), False if actively running.
        """
        latest_crawl = website.latest_crawl
        if not latest_crawl or not latest_crawl.job_id:
            return True  # No job to preempt, allow new crawl

        try:
            # Get the job to check its updated_at
            job_repo = self.crawl_service.task_service.job_service.job_repo
            job = await job_repo.get_job(latest_crawl.job_id)

            if not job:
                return True  # Job not found, allow new crawl

            # Check if job is stale - use different thresholds for QUEUED vs IN_PROGRESS
            # QUEUED jobs should move to IN_PROGRESS quickly (within seconds)
            # If stuck in QUEUED for 5+ min, it's likely orphaned (Redis cleared, worker restarted)
            # IN_PROGRESS jobs use longer tenant-configurable threshold (heartbeat timeout)
            tenant = await self.tenant_repo.get(self.user.tenant_id)
            tenant_settings = tenant.crawler_settings if tenant else None

            if job.status == Status.QUEUED:
                # Configurable threshold for QUEUED - if stuck, it's orphaned
                threshold_minutes = get_crawler_setting(
                    "queued_stale_threshold_minutes", tenant_settings
                )
            else:
                # Standard threshold for IN_PROGRESS (heartbeat timeout)
                threshold_minutes = get_crawler_setting(
                    "crawl_stale_threshold_minutes", tenant_settings
                )
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)

            # Use updated_at if available, otherwise created_at
            job_activity_time = job.updated_at or job.created_at
            if job_activity_time and job_activity_time.tzinfo is None:
                job_activity_time = job_activity_time.replace(tzinfo=timezone.utc)

            if job_activity_time and job_activity_time < cutoff_time:
                # Job is stale - attempt ATOMIC preemption (Compare-and-Swap)
                # Only succeeds if job is still IN_PROGRESS or QUEUED
                error_message = (
                    f"Preempted: Job was stale (no activity for {threshold_minutes} minutes)"
                )
                rows_affected = await job_repo.mark_job_failed_if_running(
                    latest_crawl.job_id, error_message
                )

                if rows_affected > 0:
                    # We successfully preempted the job
                    logger.info(
                        "Preempted stale crawl job",
                        extra={
                            "job_id": str(latest_crawl.job_id),
                            "website_id": str(website.id),
                            "last_activity": str(job_activity_time),
                            "threshold_minutes": threshold_minutes,
                        },
                    )
                    return True
                else:
                    # rows_affected == 0: Someone else preempted it, or job already finished
                    # Check current status to decide if we can proceed
                    refreshed_job = await job_repo.get_job(latest_crawl.job_id)
                    if refreshed_job and refreshed_job.status in [
                        Status.QUEUED,
                        Status.IN_PROGRESS,
                    ]:
                        # Job is still running (another user refreshed it?) - don't allow
                        return False
                    # Job completed or was preempted by someone else - allow new crawl
                    return True

            # Job has recent activity, don't preempt
            return False

        except Exception as exc:
            # If we can't check staleness, be conservative and don't preempt
            logger.warning(
                "Failed to check job staleness, not preempting",
                extra={"job_id": str(latest_crawl.job_id), "error": str(exc)},
            )
            return False

    async def get_crawl_run(self, id: UUID) -> "CrawlRun":
        crawl_run = await self.crawl_run_repo.one(id)
        space = await self.space_service.get_space_by_website(crawl_run.website_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return crawl_run

    async def get_crawl_runs(self, website_id: UUID) -> list["CrawlRun"]:
        space = await self.space_service.get_space_by_website(website_id)
        actor = self.actor_manager.get_space_actor_from_space(space=space)

        if not actor.can_read_websites():
            raise UnauthorizedException()

        return await self.crawl_run_repo.get_crawl_runs(website_id=website_id)

    async def bulk_crawl_websites(
        self, website_ids: list[UUID]
    ) -> tuple[list["CrawlRun"], list[dict[str, str]]]:
        """Trigger crawls for multiple websites in bulk.

        Why: Enables efficient batch operations for users managing many websites.
        Each website is processed independently - failures don't stop the batch.

        Args:
            website_ids: List of website IDs to crawl

        Returns:
            Tuple of (successful_crawl_runs, errors)
            - successful_crawl_runs: List of CrawlRun objects that were queued
            - errors: List of dicts with website_id and error message for failures

        Raises:
            BadRequestException: If more than 50 websites requested (safety limit)
        """
        if len(website_ids) > 50:
            raise BadRequestException("Cannot crawl more than 50 websites at once")

        successful_runs = []
        errors = []

        for website_id in website_ids:
            try:
                # Reuse existing crawl_website method for consistent behavior
                crawl_run = await self.crawl_website(website_id)
                successful_runs.append(crawl_run)
            except CrawlAlreadyRunningException:
                errors.append({
                    "website_id": str(website_id),
                    "error": "Crawl already in progress for this website"
                })
            except UnauthorizedException:
                errors.append({
                    "website_id": str(website_id),
                    "error": "Not authorized to crawl this website"
                })
            except Exception as e:
                errors.append({
                    "website_id": str(website_id),
                    "error": str(e)
                })

        return successful_runs, errors
