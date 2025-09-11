from intric.jobs.task_models import EmbeddingModelMigrationTask, Transcription, UploadInfoBlob
from intric.main.container.container import Container
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.worker.crawl_tasks import crawl_task, queue_website_crawls
from intric.worker.embedding_migration_tasks import embedding_model_migration_task
from intric.worker.upload_tasks import transcription_task, upload_info_blob_task
from intric.worker.worker import Worker

worker = Worker()


@worker.function()
async def upload_info_blob(job_id: str, params: UploadInfoBlob, container: Container):
    return await upload_info_blob_task(job_id=job_id, params=params, container=container)


@worker.function()
async def transcription(job_id: str, params: Transcription, container: Container):
    return await transcription_task(job_id=job_id, params=params, container=container)


@worker.function()
async def crawl(job_id: str, params: CrawlTask, container: Container):
    return await crawl_task(job_id=job_id, params=params, container=container)


@worker.function()
async def migrate_embedding_model(job_id: str, params: EmbeddingModelMigrationTask, container: Container):
    return await embedding_model_migration_task(job_id=job_id, params=params, container=container)


@worker.cron_job(weekday="fri", hour=23, minute=0)
async def crawl_all_websites(container: Container):
    return await queue_website_crawls(container=container)
