from __future__ import annotations

from dataclasses import dataclass

from app.schemas.chat import StoryState
from app.schemas.llm import ChatMessage
from app.services.prompt_builder import build_story_prompt
from app.services.token_estimator import estimate_tokens, trim_to_token_budget


SECTION_TOKEN_BUDGETS = {
    "world": 700,
    "character": 520,
    "state": 420,
    "canon_facts": 560,
    "user_preferences": 320,
    "story_prompt": 700,
    "story_summary": 700,
    "retrieved_memories": 640,
    "recent_messages": 900,
}


@dataclass(frozen=True)
class ContextAssembly:
    prompt_messages: list[ChatMessage]
    preview: dict


def assemble_story_context(
    user_message: str,
    state: StoryState,
    memories: list[str],
    canon_facts: list[str],
    world: dict,
    character: dict,
    user_preferences: list[str],
    story_prompt: str,
    interaction_mode: str,
    recent_messages: list[dict],
    story_summary: str = "",
) -> ContextAssembly:
    trimmed_world = _trim_dict(world, SECTION_TOKEN_BUDGETS["world"])
    trimmed_character = _trim_dict(character, SECTION_TOKEN_BUDGETS["character"])
    trimmed_canon = _take_items(canon_facts, SECTION_TOKEN_BUDGETS["canon_facts"])
    trimmed_preferences = _take_items(user_preferences, SECTION_TOKEN_BUDGETS["user_preferences"])
    trimmed_story_prompt = _trim_text(story_prompt, SECTION_TOKEN_BUDGETS["story_prompt"])
    trimmed_summary = _trim_text(story_summary, SECTION_TOKEN_BUDGETS["story_summary"])
    trimmed_memories = _take_items(memories, SECTION_TOKEN_BUDGETS["retrieved_memories"])
    trimmed_recent_messages = _take_recent_messages(recent_messages, SECTION_TOKEN_BUDGETS["recent_messages"])

    prompt_messages = build_story_prompt(
        user_message,
        state,
        trimmed_memories,
        trimmed_canon,
        trimmed_world,
        trimmed_character,
        trimmed_preferences,
        trimmed_story_prompt,
        interaction_mode,
        trimmed_recent_messages,
        trimmed_summary,
    )
    preview = {
        "budgets": SECTION_TOKEN_BUDGETS,
        "estimated_tokens": {
            "user_message": _estimate_tokens(user_message),
            "world": _estimate_tokens(str(trimmed_world)),
            "character": _estimate_tokens(str(trimmed_character)),
            "state": _estimate_tokens(state.model_dump_json()),
            "canon_facts": _estimate_tokens("\n".join(trimmed_canon)),
            "user_preferences": _estimate_tokens("\n".join(trimmed_preferences)),
            "story_prompt": _estimate_tokens(trimmed_story_prompt),
            "story_summary": _estimate_tokens(trimmed_summary),
            "retrieved_memories": _estimate_tokens("\n".join(trimmed_memories)),
            "recent_messages": _estimate_tokens(str(trimmed_recent_messages)),
            "prompt_total": sum(_estimate_tokens(message.content) for message in prompt_messages),
        },
        "selected_counts": {
            "canon_facts": len(trimmed_canon),
            "user_preferences": len(trimmed_preferences),
            "retrieved_memories": len(trimmed_memories),
            "recent_messages": len(trimmed_recent_messages),
        },
        "dropped_counts": {
            "canon_facts": max(0, len(canon_facts) - len(trimmed_canon)),
            "user_preferences": max(0, len(user_preferences) - len(trimmed_preferences)),
            "retrieved_memories": max(0, len(memories) - len(trimmed_memories)),
            "recent_messages": max(0, len(recent_messages) - len(trimmed_recent_messages)),
        },
        "sections": {
            "world": trimmed_world,
            "character": trimmed_character,
            "state": state.model_dump(),
            "canon_facts": trimmed_canon,
            "user_preferences": trimmed_preferences,
            "story_prompt": trimmed_story_prompt,
            "story_summary": trimmed_summary,
            "interaction_mode": interaction_mode,
            "retrieved_memories": trimmed_memories,
            "recent_messages": trimmed_recent_messages,
        },
        "prompt_roles": [message.role for message in prompt_messages],
    }
    return ContextAssembly(prompt_messages=prompt_messages, preview=preview)


def _take_items(items: list[str], token_budget: int) -> list[str]:
    selected: list[str] = []
    used = 0
    for item in items:
        remaining = token_budget - used
        if remaining <= 0:
            break
        trimmed = _trim_text(item, remaining)
        if not trimmed:
            continue
        selected.append(trimmed)
        used += _estimate_tokens(trimmed)
        if trimmed != item:
            break
    return selected


def _take_recent_messages(messages: list[dict], token_budget: int) -> list[dict]:
    selected: list[dict] = []
    used = 0
    for message in reversed(messages):
        content = str(message.get("content", ""))
        remaining = token_budget - used
        if remaining <= 0:
            break
        trimmed = _trim_text(content, remaining)
        if not trimmed:
            continue
        selected.append({"role": message.get("role", ""), "content": trimmed})
        used += _estimate_tokens(trimmed)
        if trimmed != content:
            break
    return list(reversed(selected))


def _trim_dict(payload: dict, token_budget: int) -> dict:
    trimmed = {}
    used = 0
    for key, value in payload.items():
        text = str(value)
        cost = _estimate_tokens(f"{key}: {text}")
        if trimmed and used + cost > token_budget:
            break
        trimmed[key] = value
        used += cost
    return trimmed


def _trim_text(text: str, token_budget: int) -> str:
    return trim_to_token_budget(text, token_budget)


def _estimate_tokens(text: str) -> int:
    return estimate_tokens(text)
