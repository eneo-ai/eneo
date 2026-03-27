import json
from typing import TYPE_CHECKING

from eneo.info_blobs.info_blob import InfoBlobMetadata, InfoBlobPublic
from eneo.main.logging import get_logger
from eneo.questions.question import Question
from eneo.services.service import Service, ServicePublicWithUser, ServiceRun
from eneo.ai_models.completion_models.completion_model import CompletionModelPublic

if TYPE_CHECKING:
    from eneo.main.models import ResourcePermission

logger = get_logger(__name__)


def from_domain_service(
    service: Service, permissions: list["ResourcePermission"] = None
):
    permissions = permissions or []

    # TODO: Look into how we surface permissions to the presentation layer
    return ServicePublicWithUser(
        **service.model_dump(exclude={"permissions", "completion_model"}),
        completion_model=CompletionModelPublic.from_domain(service.completion_model),
        permissions=permissions,
    )


def to_question(question: Question, service: Service):
    try:
        output = json.loads(question.answer)
    except json.JSONDecodeError:
        logger.warning("%s is not valid JSON. Returning raw", question.answer)
        output = question.answer

    return ServiceRun(
        id=question.id,
        input=question.question,
        output=output,
        completion_model=CompletionModelPublic.from_domain(service.completion_model),
        references=[
            InfoBlobPublic(
                **blob.model_dump(), metadata=InfoBlobMetadata(**blob.model_dump())
            )
            for blob in question.info_blobs
        ],
    )
