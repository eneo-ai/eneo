from fastapi import APIRouter

from intric.flows.api.flow_assistant_router import router as flow_assistant_router
from intric.flows.api.flow_consumer_router import router as flow_consumer_router
from intric.flows.api.flow_definition_router import router as flow_definition_router

router = APIRouter()
router.include_router(flow_definition_router)
router.include_router(flow_assistant_router)
router.include_router(flow_consumer_router)
