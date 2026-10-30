from fastapi import APIRouter as _APIRouter

from eneo.flows.api.flow_authoring_router import (
    router as _authoring_router,
)
from eneo.flows.api.flow_execution_limits_router import (
    router as _execution_limits_router,
)
from eneo.flows.api.flow_http_test_router import (
    router as _http_test_router,
)
from eneo.flows.api.flow_security_classification_router import (
    router as _security_classification_router,
)
from eneo.flows.api.flow_step_kinds_router import (
    router as _step_kinds_router,
)
from eneo.flows.api.flow_suggestions_router import (
    router as _suggestions_router,
)
from eneo.flows.api.flow_template_router import (
    router as _template_router,
)
from eneo.flows.api.flow_tool_options_router import (
    router as _tool_options_router,
)

router = _APIRouter()
# Before the authoring routes: its literal path would match their `/{id}/`.
router.include_router(_execution_limits_router)
router.include_router(_authoring_router)
router.include_router(_template_router)
router.include_router(_security_classification_router)
router.include_router(_tool_options_router)
router.include_router(_step_kinds_router)
router.include_router(_suggestions_router)
router.include_router(_http_test_router)

__all__ = ["router"]
