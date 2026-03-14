from fastapi import APIRouter, Depends

from intric.limits.limit import Limits
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.get("/", response_model=Limits)
def get_limits(container: Container = Depends(get_container(with_user=True))):
    service = container.limit_service()
    return service.get_limits()
