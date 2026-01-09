from dependency_injector import providers

from intric.database.database import sessionmanager
from intric.main.container.container import Container
from intric.worker.worker import Worker

worker = Worker()


@worker.cron_job(hour=3, minute=0)  # Run daily at 3 AM
async def cleanup_old_data(container: Container):
    """Clean up old data (questions, app runs, sessions) based on retention policy.

    Uses explicit sessionmanager.session() to avoid nested transaction issues
    when cron wrapper already has a transaction open.
    """
    # Use fresh session to avoid nested transaction error from cron wrapper
    async with sessionmanager.session() as session:
        container.session.override(providers.Object(session))
        try:
            async with session.begin():
                data_retention_service = container.data_retention_service()

                await data_retention_service.delete_old_questions()
                await data_retention_service.delete_old_app_runs()
                await data_retention_service.delete_old_sessions()
        finally:
            # Always reset override, even on exception
            container.session.reset_override()

    return True
