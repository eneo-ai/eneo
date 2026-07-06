import json
from typing import TYPE_CHECKING

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.info_blobs.info_blob import InfoBlobMetadata, InfoBlobPublic
from eneo.main.logging import get_logger
from eneo.questions.question import Question
from eneo.services.service import Service, ServicePublicWithUser, ServiceRun

if TYPE_CHECKING:
    from eneo.main.models import ResourcePermission

logger = get_logger(__name__)


def from_domain_service(
    service: Service,
    permissions: list["ResourcePermission"] | None = None,
    *,
    show_pricing: bool = True,
):
    permissions = permissions or []

    # TODO: Look into how we surface permissions to the presentation layer
    assert service.completion_model is not None, "Service must have a completion model"
    return ServicePublicWithUser(
        **service.model_dump(exclude={"permissions", "completion_model"}),
        completion_model=CompletionModelPublic.from_domain(
            service.completion_model, show_pricing=show_pricing
        ),
        permissions=permissions,
    )


def to_question(question: Question, service: Service, *, show_pricing: bool = True):
    try:
        output = json.loads(question.answer)
    except json.JSONDecodeError:
        logger.warning("%s is not valid JSON. Returning raw", question.answer)
        output = question.answer

    assert service.completion_model is not None, "Service must have a completion model"
    return ServiceRun(
        id=question.id,
        input=question.question,
        output=output,
        completion_model=CompletionModelPublic.from_domain(
            service.completion_model, show_pricing=show_pricing
        ),
        references=[
            InfoBlobPublic(
                **blob.model_dump(), metadata=InfoBlobMetadata(**blob.model_dump())
            )
            for blob in question.info_blobs
        ],
    )
