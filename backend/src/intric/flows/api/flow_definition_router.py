from fastapi import APIRouter as _APIRouter

from intric.flows.api.flow_authoring_router import (
    router as _authoring_router,
)
from intric.flows.api.flow_http_test_router import (
    router as _http_test_router,
)
from intric.flows.api.flow_template_router import (
    router as _template_router,
)

router = _APIRouter()
router.include_router(_authoring_router)
router.include_router(_template_router)
router.include_router(_http_test_router)

__all__ = ["router"]
