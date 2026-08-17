import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.auth import get_admin_user
from app.config import Settings
from app.db.models import ModelCall, QuotaPolicyChange, QuotaResetEvent, Story, User
from app.db.session import AsyncSessionLocal, engine
from app.routers.admin import overview, reset_all_quotas, update_quota_policy
from app.routers.quota import my_quota
from app.schemas.quota import QuotaPolicyUpdateRequest, QuotaResetRequest
from app.services.quota_service import QuotaExceededError, ensure_quota, quota_snapshot


def test_weekly_quota_reset_and_admin_bypass() -> None:
    async def scenario() -> None:
        regular_id = uuid4()
        admin_id = uuid4()
        reset_id = uuid4()
        policy_change_id: int | None = None
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
                assert snapshot.soft_limit_percentage == 80
                assert snapshot.soft_limit_reached is True
                with pytest.raises(QuotaExceededError):
                    await ensure_quota(session, regular_id, 101, settings)

                admin_snapshot = await ensure_quota(session, admin_id, 1000000, settings)
                assert admin_snapshot.unlimited is True
                assert admin_snapshot.limit_tokens is None
                assert admin_snapshot.soft_limit_reached is False

                standard_overview = await overview(
                    search="Quota",
                    role="standard",
                    page=1,
                    page_size=10,
                    _admin=admin,
                    session=session,
                    settings=settings,
                )
                assert standard_overview.filtered_users == 1
                assert standard_overview.users[0].id == str(regular_id)
                assert standard_overview.users[0].used_tokens == 900
                assert standard_overview.total_users >= 2
                assert standard_overview.administrator_count >= 1

                policy_update = await update_quota_policy(
                    QuotaPolicyUpdateRequest(
                        weekly_token_quota=1200,
                        reason="Integration test policy update",
                    ),
                    admin,
                    session,
                    settings,
                )
                policy_change_id = int(policy_update.change.id)
                assert policy_update.change.previous_limit_tokens == 1000
                assert policy_update.change.limit_tokens == 1200
                assert policy_update.change.estimated_words == 900

                paged_overview = await overview(
                    search="Quota",
                    role="all",
                    page=2,
                    page_size=1,
                    _admin=admin,
                    session=session,
                    settings=settings,
                )
                assert paged_overview.filtered_users == 2
                assert paged_overview.page == 2
                assert paged_overview.total_pages == 2
                assert len(paged_overview.users) == 1
                assert paged_overview.total_users == standard_overview.total_users

                literal_wildcard_overview = await overview(
                    search="%",
                    role="all",
                    page=1,
                    page_size=10,
                    _admin=admin,
                    session=session,
                    settings=settings,
                )
                assert literal_wildcard_overview.filtered_users == 0
                assert literal_wildcard_overview.users == []

                reset = await reset_all_quotas(
                    QuotaResetRequest(reason="Integration test reset"), admin, session
                )
                reset_id = UUID(reset.reset_event_id)
                reset_snapshot = await quota_snapshot(session, regular, settings)
                assert reset_snapshot.used_tokens == 0
                assert reset_snapshot.remaining_tokens == 1200
                assert reset_snapshot.soft_limit_reached is False

                reset_overview = await overview(
                    search="Quota",
                    role="all",
                    page=1,
                    page_size=10,
                    _admin=admin,
                    session=session,
                    settings=settings,
                )
                assert reset_overview.reset_events[0].id == str(reset_id)
                assert reset_overview.reset_events[0].administrator_email == admin.email
                assert reset_overview.reset_events[0].reason == "Integration test reset"
                assert reset_overview.weekly_token_quota == 1200
                assert reset_overview.estimated_weekly_words == 900
                assert reset_overview.policy_changes[0].id == str(policy_change_id)
                assert reset_overview.policy_changes[0].reason == "Integration test policy update"

                assert (await get_admin_user(admin_id, session)).id == admin_id
                with pytest.raises(HTTPException) as forbidden:
                    await get_admin_user(regular_id, session)
                assert forbidden.value.status_code == 403
        finally:
            async with AsyncSessionLocal() as cleanup:
                if policy_change_id is not None:
                    await cleanup.execute(
                        delete(QuotaPolicyChange).where(QuotaPolicyChange.id == policy_change_id)
                    )
                await cleanup.execute(delete(QuotaResetEvent).where(QuotaResetEvent.id == reset_id))
                await cleanup.execute(delete(User).where(User.id.in_([regular_id, admin_id])))
                await cleanup.commit()
            await engine.dispose()

    asyncio.run(scenario())


def test_all_stories_share_one_account_weekly_quota() -> None:
    async def scenario() -> None:
        user_id = uuid4()
        first_story_id = uuid4()
        second_story_id = uuid4()
        settings = Settings(user_weekly_token_quota=1100)
        try:
            async with AsyncSessionLocal() as session:
                user = User(
                    id=user_id,
                    email=f"story-quota-{user_id}@example.invalid",
                    display_name="Story Quota User",
                )
                session.add(user)
                await session.flush()
                session.add_all(
                    [
                        Story(id=first_story_id, user_id=user_id, title="First Story"),
                        Story(id=second_story_id, user_id=user_id, title="Second Story"),
                    ]
                )
                await session.flush()
                session.add_all(
                    [
                        ModelCall(
                            user_id=user_id,
                            story_id=first_story_id,
                            call_type="llm",
                            provider="test",
                            model="test",
                            purpose="normal_chat",
                            status="succeeded",
                            input_tokens=700,
                            output_tokens=200,
                            request={},
                            response={},
                        ),
                        ModelCall(
                            user_id=user_id,
                            story_id=second_story_id,
                            call_type="llm",
                            provider="test",
                            model="test",
                            purpose="normal_chat",
                            status="succeeded",
                            input_tokens=50,
                            output_tokens=50,
                            request={},
                            response={},
                        ),
                    ]
                )
                await session.commit()

                snapshot = await ensure_quota(session, user_id, 100, settings)
                assert snapshot.used_tokens == 1000
                assert snapshot.remaining_tokens == 100
                with pytest.raises(QuotaExceededError) as exceeded:
                    await ensure_quota(session, user_id, 101, settings)
                assert exceeded.value.scope == "account"
                assert exceeded.value.snapshot.used_tokens == 1000
                assert exceeded.value.snapshot.remaining_tokens == 100
                assert str(exceeded.value) == "Account weekly AI token quota exceeded"

                response = await my_quota(
                    user_id=user_id,
                    session=session,
                    settings=settings,
                )
                assert response.used_tokens == 1000
                assert response.limit_tokens == 1100
                assert response.remaining_tokens == 100
        finally:
            async with AsyncSessionLocal() as cleanup:
                await cleanup.execute(delete(User).where(User.id == user_id))
                await cleanup.commit()
            await engine.dispose()

    asyncio.run(scenario())


def test_concurrent_quota_policy_updates_form_one_serial_audit_chain() -> None:
    async def scenario() -> None:
        admin_id = uuid4()
        settings = Settings(user_weekly_token_quota=1000)
        try:
            async with AsyncSessionLocal() as setup:
                admin = User(
                    id=admin_id,
                    email=f"quota-policy-admin-{admin_id}@example.invalid",
                    display_name="Policy Admin",
                    is_admin=True,
                )
                setup.add(admin)
                await setup.commit()

            async def change(limit: int) -> None:
                async with AsyncSessionLocal() as session:
                    await update_quota_policy(
                        QuotaPolicyUpdateRequest(
                            weekly_token_quota=limit,
                            reason=f"Concurrent policy test {limit}",
                        ),
                        admin,
                        session,
                        settings,
                    )

            await asyncio.gather(change(2000), change(3000))

            async with AsyncSessionLocal() as verification:
                changes = list(
                    (
                        await verification.execute(
                            select(QuotaPolicyChange)
                            .where(QuotaPolicyChange.changed_by_user_id == admin_id)
                            .order_by(QuotaPolicyChange.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(changes) == 2
                assert changes[0].previous_limit_tokens == 1000
                assert changes[1].previous_limit_tokens == changes[0].limit_tokens
                assert {change.limit_tokens for change in changes} == {2000, 3000}
        finally:
            async with AsyncSessionLocal() as cleanup:
                await cleanup.execute(
                    delete(QuotaPolicyChange).where(
                        QuotaPolicyChange.changed_by_user_id == admin_id
                    )
                )
                await cleanup.execute(delete(User).where(User.id == admin_id))
                await cleanup.commit()
            await engine.dispose()

    asyncio.run(scenario())
