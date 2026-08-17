from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserModelRoute
from app.llm.model_registry import PURPOSE_DEFAULTS, get_model
from app.schemas.llm import StoryPurpose


async def load_user_purpose_routes(
    session: AsyncSession,
    user_id: UUID,
) -> dict[StoryPurpose, str]:
    result = await session.execute(
        select(UserModelRoute).where(UserModelRoute.user_id == user_id)
    )
    routes: dict[StoryPurpose, str] = {}
    for route in result.scalars().all():
        if route.purpose not in PURPOSE_DEFAULTS:
            continue
        option = get_model(route.model)
        if option is None or option.provider != route.provider:
            continue
        routes[route.purpose] = route.model
    return routes
