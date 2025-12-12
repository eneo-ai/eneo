from uuid import UUID

from fastapi import APIRouter, Depends

from intric.apps.app_runs.api.app_run_models import (
    AppRunPublic,
    AppRunSparse,
    RunAppRequest,
)
from intric.apps.apps.api.app_models import AppPublic, AppUpdateRequest
from intric.main.container.container import Container
from intric.main.models import NOT_PROVIDED, PaginatedResponse
from intric.prompts.api.prompt_models import PromptSparse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.get(
    "/{id}/",
    response_model=AppPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_app(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_service()
    assembler = container.app_assembler()

    app, permissions = await service.get_app(id)

    return assembler.from_app_to_model(app, permissions=permissions)


@router.patch(
    "/{id}/",
    response_model=AppPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_app(
    id: UUID,
    update_service_req: AppUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_service()
    assembler = container.app_assembler()

    completion_model_id = (
        update_service_req.completion_model.id
        if update_service_req.completion_model is not None
        else None
    )
    transcription_model_id = (
        update_service_req.transcription_model.id
        if update_service_req.transcription_model is not None
        else None
    )
    prompt_text = update_service_req.prompt.text if update_service_req.prompt is not None else None
    prompt_description = (
        update_service_req.prompt.description if update_service_req.prompt is not None else None
    )

    # Handle icon_id: check if it was provided in the request
    request_dict = update_service_req.model_dump(exclude_unset=True)
    icon_id = NOT_PROVIDED
    if "icon_id" in request_dict:
        icon_id = update_service_req.icon_id

    app, permissions = await service.update_app(
        app_id=id,
        name=update_service_req.name,
        description=update_service_req.description,
        completion_model_id=completion_model_id,
        completion_model_kwargs=update_service_req.completion_model_kwargs,
        input_fields=update_service_req.input_fields,
        attachment_ids=update_service_req.attachments,
        prompt_text=prompt_text,
        prompt_description=prompt_description,
        transcription_model_id=transcription_model_id,
        data_retention_days=update_service_req.data_retention_days,
        icon_id=icon_id,
    )

    return assembler.from_app_to_model(app, permissions=permissions)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_app(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_service()

    await service.delete_app(id)


@router.post(
    "/{id}/runs/",
    status_code=203,
    response_model=AppRunPublic,
    responses=responses.get_responses([400, 403]),
)
async def run_app(
    id: UUID,
    run_app_req: RunAppRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_run_service()
    assembler = container.app_run_assembler()

    file_ids = [file.id for file in run_app_req.files]
    app_run = await service.queue_app_run(id, file_ids=file_ids, text=run_app_req.text)

    return assembler.from_app_run_to_model(app_run)


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[AppRunSparse],
    responses=responses.get_responses([400, 403, 404]),
)
async def get_app_runs(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_run_service()
    assembler = container.app_run_assembler()

    app_runs = await service.get_app_runs(app_id=id)
    app_runs_public = [assembler.from_app_run_to_sparse_model(app_run) for app_run in app_runs]

    return protocol.to_paginated_response(app_runs_public)


@router.get(
    "/{id}/prompts/",
    response_model=PaginatedResponse[PromptSparse],
    responses=responses.get_responses([403, 404]),
)
async def get_prompts(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_service()
    assembler = container.prompt_assembler()

    prompts = await service.get_prompts_by_app(id)
    prompts = [assembler.from_prompt_to_model(prompt) for prompt in prompts]

    return protocol.to_paginated_response(prompts)


@router.post(
    "/{id}/publish/",
    response_model=AppPublic,
    responses=responses.get_responses([403, 404]),
)
async def publish_app(
    id: UUID,
    published: bool,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.app_service()
    assembler = container.app_assembler()

    app, permissions = await service.publish_app(app_id=id, publish=published)

    return assembler.from_app_to_model(app=app, permissions=permissions)
