import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete

from app.config import Settings
from app.db.models import User, UserModelRoute
from app.db.session import AsyncSessionLocal, engine as db_engine
from app.llm.router import LLMGateway
from app.schemas.llm import ChatMessage
from app.services.model_route_service import load_user_purpose_routes


def test_persisted_routes_drive_primary_and_auxiliary_gateway_requests() -> None:
    async def scenario() -> None:
        marker = uuid4().hex
        user_id = None
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    email=f"model-route-{marker}@example.invalid",
                    display_name="route-player",
                    email_verified_at=datetime.now(timezone.utc),
                )
                session.add(user)
                await session.flush()
                user_id = user.id
                session.add_all(
                    [
                        UserModelRoute(
                            user_id=user.id,
                            purpose="normal_chat",
                            provider="deepinfra",
                            model="zai-org/GLM-5.2",
                        ),
                        UserModelRoute(
                            user_id=user.id,
                            purpose="state_update",
                            provider="deepinfra",
                            model="deepseek-ai/DeepSeek-V4-Pro",
                        ),
                        UserModelRoute(
                            user_id=user.id,
                            purpose="summary_generation",
                            provider="deepinfra",
                            model="moonshotai/Kimi-K2.5",
                        ),
                        UserModelRoute(
                            user_id=user.id,
                            purpose="event_extraction",
                            provider="openai",
                            model="zai-org/GLM-5.2",
                        ),
                    ]
                )
                await session.commit()

                routes = await load_user_purpose_routes(session, user.id)
                assert routes == {
                    "normal_chat": "zai-org/GLM-5.2",
                    "state_update": "deepseek-ai/DeepSeek-V4-Pro",
                    "summary_generation": "moonshotai/Kimi-K2.5",
                }

                gateway = LLMGateway(Settings(dry_run_llm=True), purpose_routes=routes)
                messages = [ChatMessage(role="user", content="continue")]
                assert gateway.request_for_purpose("normal_chat", messages).model == (
                    "zai-org/GLM-5.2"
                )
                assert gateway.request_for_purpose("state_update", messages).model == (
                    "deepseek-ai/DeepSeek-V4-Pro"
                )
                assert gateway.request_for_purpose("summary_generation", messages).model == (
                    "moonshotai/Kimi-K2.5"
                )
                default_route = gateway.route_for_purpose("consistency_check")
                assert default_route["source"] == "system_default"
                assert default_route["model"] == "Qwen/Qwen3-Max"
                assert gateway.route_for_purpose("normal_chat")["source"] == "user_route"
        finally:
            if user_id is not None:
                async with AsyncSessionLocal() as cleanup:
                    await cleanup.execute(delete(User).where(User.id == user_id))
                    await cleanup.commit()
            await db_engine.dispose()

    asyncio.run(scenario())
