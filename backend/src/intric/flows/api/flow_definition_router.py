from __future__ import annotations

from fastapi import APIRouter

from intric.flows.api.flow_authoring_router import (
    create_flow,
    delete_flow,
    get_flow,
    list_flows,
    publish_flow,
    router as authoring_router,
    unpublish_flow,
    update_flow,
)
from intric.flows.api.flow_http_test_router import (
    HttpTestRequest,
    HttpTestResponse,
    _find_stored_http_config,
    execute_http_test,
    router as http_test_router,
    test_flow_http,
)
from intric.flows.api.flow_template_router import (
    generate_flow_template_signed_url,
    inspect_flow_template,
    list_flow_template_files,
    router as template_router,
    upload_flow_template_file,
)

router = APIRouter()
router.include_router(authoring_router)
router.include_router(template_router)
router.include_router(http_test_router)

__all__ = [
    "HttpTestRequest",
    "HttpTestResponse",
    "_find_stored_http_config",
    "create_flow",
    "delete_flow",
    "execute_http_test",
    "generate_flow_template_signed_url",
    "get_flow",
    "inspect_flow_template",
    "list_flow_template_files",
    "list_flows",
    "publish_flow",
    "router",
    "test_flow_http",
    "unpublish_flow",
    "update_flow",
    "upload_flow_template_file",
]
