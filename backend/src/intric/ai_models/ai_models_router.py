from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.ai_models.ai_models_presentation import ModelsPresentation
from intric.ai_models.completion_models.completion_model import (
    CompletionModelSecurityStatus,
)
from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelSecurityStatus,
)
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelSecurityStatus,
)

router = APIRouter()


@router.get(
    "/",
    response_model=ModelsPresentation,
    summary="Get all AI models",
    description="Get all completion, embedding, and transcription models. ",
    responses=responses.get_responses([404, 500]),
)
async def get_models(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    space_id: Annotated[
        Optional[UUID],
        Query(
            description="Optional space ID to provide security classification status."
        ),
    ] = None,
) -> ModelsPresentation:
    # Get services and assemblers
    completion_model_crud_service = container.completion_model_crud_service()
    transcription_model_crud_service = container.transcription_model_crud_service()
    embedding_model_crud_service = container.embedding_model_crud_service()
    user = container.user()
    space_service = container.space_service()
    space = None
    if space_id:
        space = await space_service.get_space(space_id)

    cms = await completion_model_crud_service.get_completion_models()
    tms = await transcription_model_crud_service.get_transcription_models()
    ems = await embedding_model_crud_service.get_embedding_models()

    completion_models: list[CompletionModelSecurityStatus] = []
    for cm in cms:
        completion_model_public = CompletionModelSecurityStatus.from_domain(
            cm, show_pricing=user.can_view_model_pricing
        )
        if space:
            if user.tenant.security_enabled:
                if space.security_classification is None:
                    completion_model_public.meets_security_classification = True
                else:
                    completion_model_public.meets_security_classification = (
                        not space.security_classification.is_greater_than(
                            cm.security_classification
                        )
                    )
            else:
                completion_model_public.meets_security_classification = None
        completion_models.append(completion_model_public)

    transcription_models: list[TranscriptionModelSecurityStatus] = []
    for tm in tms:
        transcription_model_public = TranscriptionModelSecurityStatus.from_domain(tm)
        if space:
            if user.tenant.security_enabled:
                if space.security_classification is None:
                    transcription_model_public.meets_security_classification = True
                else:
                    transcription_model_public.meets_security_classification = (
                        not space.security_classification.is_greater_than(
                            tm.security_classification
                        )
                    )
            else:
                transcription_model_public.meets_security_classification = None
        transcription_models.append(transcription_model_public)

    embedding_models: list[EmbeddingModelSecurityStatus] = []
    for em in ems:
        embedding_model_public = EmbeddingModelSecurityStatus.from_domain(em)
        if space:
            if user.tenant.security_enabled:
                if space.security_classification is None:
                    embedding_model_public.meets_security_classification = True
                else:
                    embedding_model_public.meets_security_classification = (
                        not space.security_classification.is_greater_than(
                            em.security_classification
                        )
                    )
            else:
                embedding_model_public.meets_security_classification = None
        embedding_models.append(embedding_model_public)

    return ModelsPresentation(
        completion_models=completion_models,
        embedding_models=embedding_models,
        transcription_models=transcription_models,
    )
