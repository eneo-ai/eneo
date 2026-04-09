from typing import Annotated

from fastapi import APIRouter, Depends

from intric.limits.limit import Limits
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container

router = APIRouter()
with_user_container = get_container(with_user=True)


@router.get("/", response_model=Limits)
def get_limits(container: Annotated[Container, Depends(with_user_container)]):
    service = container.limit_service()
    return service.get_limits()
