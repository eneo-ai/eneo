from fastapi import APIRouter, Depends

from eneo.limits.limit import Limits
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container

router = APIRouter()


@router.get("/", response_model=Limits)
def get_limits(container: Container = Depends(get_container())):
    service = container.limit_service()
    return service.get_limits()
