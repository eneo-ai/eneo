# MIT License

from datetime import datetime
from uuid import UUID

from intric.analysis.analysis_job_manager import AnalysisJobManager
from intric.jobs.task_models import AnalyzeConversationInsightsTask
from intric.main.container.container import Container
from intric.main.logging import get_logger

logger = get_logger(__name__)


async def analyze_conversation_insights_task(
    *,
    job_id: str,
    params: AnalyzeConversationInsightsTask,
    container: Container,
):
    parsed_job_id = UUID(job_id)
    user = container.user()
    manager = AnalysisJobManager(container.redis_client())
    await manager.mark_processing(tenant_id=user.tenant_id, job_id=parsed_job_id)

    try:
        service = container.analysis_service()
        answer = await service.generate_unified_analysis_answer(
            question=params.question,
            assistant_id=params.assistant_id,
            group_chat_id=params.group_chat_id,
            from_date=datetime.fromisoformat(params.from_date),
            to_date=datetime.fromisoformat(params.to_date),
            include_followup=params.include_followups,
        )
    except Exception as exc:
        logger.exception(
            "Async conversation insights job failed",
            extra={"job_id": job_id, "tenant_id": str(user.tenant_id)},
        )
        await manager.mark_failed(
            tenant_id=user.tenant_id,
            job_id=parsed_job_id,
            error=str(exc),
        )
        raise

    await manager.mark_completed(
        tenant_id=user.tenant_id,
        job_id=parsed_job_id,
        answer=answer,
    )
    return {"job_id": job_id, "status": "completed"}
