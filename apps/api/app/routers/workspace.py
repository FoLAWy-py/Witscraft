from fastapi import APIRouter

from app.routers.workspace_branches import router as branches_router
from app.routers.workspace_entities import router as entities_router
from app.routers.workspace_memory import router as memory_router
from app.routers.workspace_onboarding import router as onboarding_router
from app.routers.workspace_stories import router as stories_router
from app.routers.workspace_support import workspace
from app.schemas.chat import WorkspaceResponse

router = APIRouter(prefix="/workspace", tags=["workspace"])
router.include_router(onboarding_router)
router.include_router(stories_router)
router.include_router(branches_router)
router.include_router(entities_router)
router.include_router(memory_router)
router.get("", response_model=WorkspaceResponse)(workspace)
