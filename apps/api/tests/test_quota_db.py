import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.auth import get_admin_user
from app.config import Settings
from app.db.models import ModelCall, QuotaResetEvent, User
from app.db.session import AsyncSessionLocal, engine
from app.routers.admin import reset_all_quotas
from app.schemas.quota import QuotaResetRequest
from app.services.quota_service import QuotaExceededError, ensure_quota, quota_snapshot


def test_weekly_quota_reset_and_admin_bypass() -> None:
    async def scenario() -> None:
        regular_id = uuid4()
        admin_id = uuid4()
        reset_id = uuid4()
        settings = Settings(user_weekly_token_quota=1000)
        try:
            async with AsyncSessionLocal() as session:
                regular = User(
                    id=regular_id,
                    email=f"quota-{regular_id}@example.invalid",
                    display_name="Quota User",
                )
                admin = User(
                    id=admin_id,
                    email=f"quota-admin-{admin_id}@example.invalid",
                    display_name="Quota Admin",
                    is_admin=True,
                )
                session.add_all([regular, admin])
                await session.flush()
                session.add(
                    ModelCall(
                        user_id=regular_id,
                        call_type="llm",
                        provider="test",
                        model="test",
                        purpose="normal_chat",
                        status="succeeded",
                        input_tokens=700,
                        output_tokens=200,
                        request={},
                        response={},
                    )
                )
                session.add_all(
                    [
                        ModelCall(
                            user_id=regular_id,
                            call_type="embedding",
                            provider="local",
                            model="deterministic-test",
                            purpose="memory_embedding",
                            status="succeeded",
                            input_tokens=5000,
                            output_tokens=0,
                            request={},
                            response={"dry_run": False},
                        ),
                        ModelCall(
                            user_id=regular_id,
                            call_type="llm",
                            provider="deepinfra",
                            model="dry-run-test",
                            purpose="normal_chat",
                            status="succeeded",
                            input_tokens=5000,
                            output_tokens=5000,
                            request={},
                            response={"dry_run": True},
                        ),
                    ]
                )
                await session.commit()

                snapshot = await quota_snapshot(session, regular, settings)
                assert snapshot.used_tokens == 900
                assert snapshot.remaining_tokens == 100
                assert snapshot.percentage_used == 90
                with pytest.raises(QuotaExceededError):
                    await ensure_quota(session, regular_id, 101, settings)

                admin_snapshot = await ensure_quota(session, admin_id, 1000000, settings)
                assert admin_snapshot.unlimited is True
                assert admin_snapshot.limit_tokens is None

                reset = await reset_all_quotas(
                    QuotaResetRequest(reason="Integration test reset"), admin, session
                )
                reset_id = UUID(reset.reset_event_id)
                reset_snapshot = await quota_snapshot(session, regular, settings)
                assert reset_snapshot.used_tokens == 0
                assert reset_snapshot.remaining_tokens == 1000

                assert (await get_admin_user(admin_id, session)).id == admin_id
                with pytest.raises(HTTPException) as forbidden:
                    await get_admin_user(regular_id, session)
                assert forbidden.value.status_code == 403
        finally:
            async with AsyncSessionLocal() as cleanup:
                await cleanup.execute(delete(QuotaResetEvent).where(QuotaResetEvent.id == reset_id))
                await cleanup.execute(delete(User).where(User.id.in_([regular_id, admin_id])))
                await cleanup.commit()
            await engine.dispose()

    asyncio.run(scenario())
