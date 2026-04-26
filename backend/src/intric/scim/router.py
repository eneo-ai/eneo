from fastapi import APIRouter

from intric.scim.resources.bulk import router as bulk_router
from intric.scim.resources.discovery import router as discovery_router
from intric.scim.resources.groups import router as groups_router
from intric.scim.resources.users import router as users_router

router = APIRouter()
router.include_router(discovery_router)
router.include_router(users_router)
router.include_router(groups_router)
router.include_router(bulk_router)
