import json
import re
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CanonFact,
    Character,
    MemoryItem,
    Message,
    Story,
    StoryBranch,
    StoryStateSnapshot,
    StorySummary,
    World,
)


async def build_story_export_payload(
    session: AsyncSession,
    story: Story,
    branch: StoryBranch,
) -> dict:
    world = await session.get(World, story.world_id) if story.world_id else None
    character_result = await session.execute(
        select(Character)
        .where(Character.world_id == story.world_id, Character.user_id == story.user_id)
        .order_by(Character.created_at.asc())
    )
    message_result = await session.execute(
        select(Message)
        .where(Message.story_id == story.id, Message.branch_id == branch.id)
        .order_by(Message.created_at.asc())
    )
    state_result = await session.execute(
        select(StoryStateSnapshot)
        .where(StoryStateSnapshot.story_id == story.id, StoryStateSnapshot.branch_id == branch.id)
        .order_by(desc(StoryStateSnapshot.created_at))
        .limit(1)
    )
    memory_result = await session.execute(
        select(MemoryItem)
        .where(MemoryItem.story_id == story.id, MemoryItem.branch_id == branch.id, MemoryItem.is_active.is_(True))
        .order_by(desc(MemoryItem.importance), desc(MemoryItem.updated_at))
    )
    canon_result = await session.execute(
        select(CanonFact)
        .where(CanonFact.story_id == story.id, CanonFact.branch_id == branch.id, CanonFact.is_active.is_(True))
        .order_by(desc(CanonFact.importance), CanonFact.created_at.asc())
    )
    summary_result = await session.execute(
        select(StorySummary)
        .where(StorySummary.story_id == story.id, StorySummary.branch_id == branch.id)
        .order_by(StorySummary.created_at.asc())
    )

    state_snapshot = state_result.scalar_one_or_none()

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "story": {
            "id": str(story.id),
            "title": story.title,
            "status": story.status,
            "created_at": _iso(story.created_at),
            "updated_at": _iso(story.updated_at),
        },
        "branch": {
            "id": str(branch.id),
            "name": branch.name,
            "parent_branch_id": str(branch.parent_branch_id) if branch.parent_branch_id else None,
            "created_at": _iso(branch.created_at),
        },
        "world": _world_payload(world),
        "characters": [_character_payload(character) for character in character_result.scalars().all()],
        "state": state_snapshot.state if state_snapshot else {},
        "summaries": [_summary_payload(summary) for summary in summary_result.scalars().all()],
        "canon_facts": [_canon_payload(fact) for fact in canon_result.scalars().all()],
        "memories": [_memory_payload(memory) for memory in memory_result.scalars().all()],
        "messages": [_message_payload(message) for message in message_result.scalars().all()],
    }


def render_story_markdown(payload: dict) -> str:
    story = payload["story"]
    branch = payload["branch"]
    world = payload.get("world") or {}
    lines = [
        f"# {story['title']}",
        "",
        f"- Story ID: `{story['id']}`",
        f"- Branch: {branch['name']} (`{branch['id']}`)",
        f"- Exported at: {payload['exported_at']}",
        "",
        "## World",
        "",
        f"**Name:** {world.get('name') or 'Unset'}",
        "",
        world.get("description") or "No world description.",
        "",
        f"**Genre:** {world.get('genre') or 'Unset'}",
        "",
    ]

    lines.extend(_section_list("Characters", [f"**{item['name']}**: {item['description'] or 'No description.'}" for item in payload["characters"]]))
    lines.extend(_state_section(payload.get("state") or {}))
    lines.extend(_section_list("Session Summaries", [f"**{item['title']}**\n\n{item['content']}" for item in payload["summaries"]]))
    lines.extend(_section_list("Canon Facts", [item["content"] for item in payload["canon_facts"]]))
    lines.extend(_section_list("Memories", [item["content"] for item in payload["memories"]]))
    lines.extend(["## Transcript", ""])

    if payload["messages"]:
        for message in payload["messages"]:
            role = message["role"].title()
            created = f" ({message['created_at']})" if message.get("created_at") else ""
            lines.extend([f"### {role}{created}", "", message["content"], ""])
    else:
        lines.extend(["No messages in this branch.", ""])

    return "\n".join(lines).rstrip() + "\n"


def render_story_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def export_filename(story_title: str, branch_name: str, extension: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{story_title}-{branch_name}").strip("-").lower()
    return f"{slug or 'witscraft-story'}.{extension}"


def _section_list(title: str, items: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if not items:
        return lines + [f"No {title.lower()} recorded.", ""]
    for item in items:
        lines.extend([f"- {item}", ""])
    return lines


def _state_section(state: dict) -> list[str]:
    lines = ["## Current State", ""]
    if not state:
        return lines + ["No state snapshot recorded.", ""]
    for key in ("location", "time", "mood", "objective"):
        lines.append(f"- **{key.replace('_', ' ').title()}:** {state.get(key) or 'Unset'}")
    for key in ("inventory", "open_threads"):
        values = state.get(key) or []
        lines.append(f"- **{key.replace('_', ' ').title()}:** {', '.join(values) if values else 'None'}")
    lines.append("")
    return lines


def _world_payload(world: World | None) -> dict:
    if world is None:
        return {}
    return {
        "id": str(world.id),
        "name": world.name,
        "description": world.description,
        "genre": world.genre,
        "rules": world.rules,
        "lorebook": world.lorebook,
        "tone": world.tone,
    }


def _character_payload(character: Character) -> dict:
    return {
        "id": str(character.id),
        "name": character.name,
        "description": character.description,
        "persona": character.persona,
        "speaking_style": character.speaking_style,
        "relationship_to_user": character.relationship_to_user,
        "constraints": character.constraints,
    }


def _summary_payload(summary: StorySummary) -> dict:
    return {
        "id": str(summary.id),
        "parent_summary_id": str(summary.parent_summary_id) if summary.parent_summary_id else None,
        "type": summary.summary_type,
        "prompt_version": summary.prompt_version,
        "provider": summary.provider,
        "model": summary.model,
        "trigger": summary.trigger,
        "title": summary.title,
        "content": summary.content,
        "message_count": summary.message_count,
        "token_count": summary.token_count,
        "created_at": _iso(summary.created_at),
    }


def _canon_payload(fact: CanonFact) -> dict:
    return {
        "id": str(fact.id),
        "type": fact.fact_type,
        "content": fact.content,
        "importance": fact.importance,
        "confidence": float(fact.confidence or 0),
    }


def _memory_payload(memory: MemoryItem) -> dict:
    return {
        "id": str(memory.id),
        "type": memory.memory_type,
        "content": memory.content,
        "importance": memory.importance,
        "recency_score": float(memory.recency_score or 0),
        "entity_tags": memory.entity_tags,
        "has_embedding": bool(memory.embedding),
        "embedding_model": memory.embedding_model,
        "embedding_dimensions": memory.embedding_dimensions or len(memory.embedding or []),
        "embedding_version": memory.embedding_version,
        "content_hash": memory.content_hash,
        "embedded_at": memory.embedded_at.isoformat() if memory.embedded_at else None,
    }


def _message_payload(message: Message) -> dict:
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "token_count": message.token_count,
        "metadata": message.meta,
        "created_at": _iso(message.created_at),
    }


def _iso(value) -> str:
    return value.isoformat() if value else ""
