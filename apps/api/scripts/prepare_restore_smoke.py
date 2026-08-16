"""Create an isolated account and story for a restored-database smoke test."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.models import AuthCredential, Character, Message, Story, StoryBranch, User, World
from app.db.session import AsyncSessionLocal, engine
from app.services.auth_service import hash_password


EMAIL = "restore-smoke@example.invalid"
PASSWORD = "Witscraft-restore-smoke-2026!"


async def main() -> None:
    settings = get_settings()
    if not settings.database_name.startswith("witscraft_restore_"):
        raise RuntimeError("Restore smoke fixtures are restricted to witscraft_restore_* databases")

    async with AsyncSessionLocal() as session:
        await session.execute(delete(User).where(User.email == EMAIL))
        user = User(
            email=EMAIL,
            display_name="Restore Smoke",
            email_verified_at=datetime.now(timezone.utc),
        )
        session.add(user)
        await session.flush()
        session.add(AuthCredential(user_id=user.id, password_hash=hash_password(PASSWORD)))

        world = World(
            user_id=user.id,
            name="Recovery World",
            description="An isolated restore verification world.",
            genre="speculative fiction",
            rules={},
            lorebook=[],
            tone={"style": "concise"},
        )
        session.add(world)
        await session.flush()
        character = Character(
            user_id=user.id,
            world_id=world.id,
            name="Mira",
            description="An archivist verifying recovered records.",
            persona={},
            speaking_style={},
            relationship_to_user={},
            constraints={},
        )
        story = Story(
            user_id=user.id,
            world_id=world.id,
            main_character_id=character.id,
            title="Recovery Drill",
            status="active",
            interaction_mode="open",
            consistency_mode="auto",
        )
        session.add_all([character, story])
        await session.flush()
        branch = StoryBranch(story_id=story.id, name="main", version=0)
        session.add(branch)
        await session.flush()
        story.current_branch_id = branch.id
        session.add(
            Message(
                story_id=story.id,
                branch_id=branch.id,
                role="assistant",
                content="The recovered archive opens at the final verified page.",
                meta={},
            )
        )
        await session.commit()

    print(
        json.dumps(
            {
                "email": EMAIL,
                "password": PASSWORD,
                "story_id": str(story.id),
                "branch_id": str(branch.id),
                "branch_version": branch.version,
            }
        )
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
