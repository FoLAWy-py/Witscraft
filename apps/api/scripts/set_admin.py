"""Grant or revoke the administrator role by account email."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import User
from app.db.session import AsyncSessionLocal, engine


async def main(email: str, revoke: bool) -> None:
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            raise RuntimeError("Account not found")
        user.is_admin = not revoke
        await session.commit()
        print(f"Administrator role {'revoked from' if revoke else 'granted to'} {user.email}")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.revoke))
