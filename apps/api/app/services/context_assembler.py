from __future__ import annotations

from dataclasses import dataclass

from app.schemas.chat import StoryState
from app.schemas.llm import ChatMessage
from app.services.prompt_builder import build_story_prompt
from app.services.token_estimator import estimate_tokens, trim_to_token_budget


SECTION_TOKEN_BUDGETS = {
    "world": 900,
    "character": 700,
    "state": 520,
    "canon_facts": 800,
    "user_preferences": 400,
    "story_prompt": 900,
    "story_summary": 1100,
    "retrieved_memories": 900,
    "recent_messages": 1500,
}

SECTION_MIN_TOKEN_BUDGETS = {
    "world": 300,
    "character": 260,
    "state": 260,
    "canon_facts": 300,
    "user_preferences": 160,
    "story_prompt": 300,
    "story_summary": 300,
    "retrieved_memories": 320,
    "recent_messages": 500,
}

SECTION_ALLOCATION_PRIORITY = (
    "state",
    "story_summary",
    "recent_messages",
    "canon_facts",
    "retrieved_memories",
    "character",
    "world",
    "story_prompt",
    "user_preferences",
)

SECTION_SOURCES = {
    "world": "authorized story world",
    "character": "authorized perspective character",
    "state": "latest branch state snapshot",
    "canon_facts": "active branch canon facts",
    "user_preferences": "authenticated player preferences",
    "story_prompt": "active story custom instructions",
    "story_summary": "latest cumulative branch summary",
    "retrieved_memories": "authorized hybrid memory retrieval",
    "recent_messages": "uncovered branch message timeline",
}

CONTEXT_SECTION_TOKEN_CEILING = 5460
CONTEXT_INPUT_TOKEN_TARGET = 9000
CONTEXT_RENDER_OVERHEAD_RESERVE = 900
ALLOCATION_QUANTUM = 16


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
    user_message_tokens = _estimate_tokens(user_message)
    demands = _section_demands(
        state=state,
        memories=memories,
        canon_facts=canon_facts,
        world=world,
        character=character,
        user_preferences=user_preferences,
        story_prompt=story_prompt,
        recent_messages=recent_messages,
        story_summary=story_summary,
    )
    section_pool = min(
        CONTEXT_SECTION_TOKEN_CEILING,
        max(
            0,
            CONTEXT_INPUT_TOKEN_TARGET
            - CONTEXT_RENDER_OVERHEAD_RESERVE
            - user_message_tokens,
        ),
    )
    budgets = _allocate_section_budgets(demands, section_pool)

    trimmed_world = _trim_dict(
        world,
        budgets["world"],
        key_order=("name", "genre", "rules", "description"),
    )
    trimmed_character = _trim_dict(
        character,
        budgets["character"],
        key_order=(
            "name",
            "goal",
            "identity",
            "personality",
            "secret",
            "speaking_style",
            "relationship",
        ),
    )
    trimmed_state = _trim_state(state, budgets["state"])
    trimmed_canon = _take_items(canon_facts, budgets["canon_facts"])
    trimmed_preferences = _take_items(user_preferences, budgets["user_preferences"])
    trimmed_story_prompt = _trim_text(story_prompt, budgets["story_prompt"])
    trimmed_summary = _trim_text(story_summary, budgets["story_summary"])
    trimmed_memories = _take_items(memories, budgets["retrieved_memories"])
    trimmed_recent_messages = _take_recent_messages(
        recent_messages,
        budgets["recent_messages"],
    )

    prompt_messages = build_story_prompt(
        user_message,
        trimmed_state,
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
    selected_tokens = {
        "world": _estimate_tokens(str(trimmed_world)),
        "character": _estimate_tokens(str(trimmed_character)),
        "state": _estimate_tokens(trimmed_state.model_dump_json()),
        "canon_facts": _estimate_tokens("\n".join(trimmed_canon)),
        "user_preferences": _estimate_tokens("\n".join(trimmed_preferences)),
        "story_prompt": _estimate_tokens(trimmed_story_prompt),
        "story_summary": _estimate_tokens(trimmed_summary),
        "retrieved_memories": _estimate_tokens("\n".join(trimmed_memories)),
        "recent_messages": _estimate_tokens(str(trimmed_recent_messages)),
    }
    preview = {
        "budgets": budgets,
        "budget_policy": {
            "input_target": CONTEXT_INPUT_TOKEN_TARGET,
            "render_overhead_reserve": CONTEXT_RENDER_OVERHEAD_RESERVE,
            "section_pool": section_pool,
            "allocated": sum(budgets.values()),
            "selected": sum(selected_tokens.values()),
            "minimums": SECTION_MIN_TOKEN_BUDGETS,
            "maximums": SECTION_TOKEN_BUDGETS,
        },
        "token_estimator": {
            "name": "conservative-multilingual-v1",
            "calibrated_to_provider_tokenizer": False,
        },
        "estimated_tokens": {
            "user_message": user_message_tokens,
            "world": _estimate_tokens(str(trimmed_world)),
            "character": _estimate_tokens(str(trimmed_character)),
            "state": _estimate_tokens(trimmed_state.model_dump_json()),
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
        "section_selection": {
            name: {
                "source": SECTION_SOURCES[name],
                "demand_tokens": demands[name],
                "allocated_tokens": budgets[name],
                "selected_tokens": selected_tokens[name],
                "truncated": selected_tokens[name] < demands[name],
                "truncation_reason": (
                    "dynamic_section_budget"
                    if selected_tokens[name] < demands[name]
                    else None
                ),
            }
            for name in SECTION_ALLOCATION_PRIORITY
        },
        "sections": {
            "world": trimmed_world,
            "character": trimmed_character,
            "state": trimmed_state.model_dump(),
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
    for message in reversed(messages):
        content = str(message.get("content", ""))
        role = str(message.get("role", ""))
        candidate = [{"role": role, "content": content}, *selected]
        if _estimate_tokens(str(candidate)) <= token_budget:
            selected = candidate
            continue
        remaining = token_budget - _estimate_tokens(
            str([{"role": role, "content": ""}, *selected])
        )
        if remaining <= 0:
            break
        trimmed = _trim_text(content, remaining)
        candidate = [{"role": role, "content": trimmed}, *selected]
        while trimmed and _estimate_tokens(str(candidate)) > token_budget:
            trimmed = _trim_text(trimmed, max(0, _estimate_tokens(trimmed) - 1))
            candidate = [{"role": role, "content": trimmed}, *selected]
        if trimmed:
            selected = candidate
        break
    return selected


def _trim_dict(
    payload: dict,
    token_budget: int,
    *,
    key_order: tuple[str, ...] | None = None,
) -> dict:
    if token_budget <= 0:
        return {}
    trimmed: dict = {}
    ordered_keys = [
        *(key for key in (key_order or ()) if key in payload),
        *(key for key in payload if key not in (key_order or ())),
    ]
    for key in ordered_keys:
        value = payload[key]
        candidate = {**trimmed, key: value}
        if _estimate_tokens(str(candidate)) <= token_budget:
            trimmed[key] = value
            continue
        remaining = token_budget - _estimate_tokens(str({**trimmed, key: ""}))
        shortened = _trim_text(str(value), max(0, remaining))
        if not shortened:
            break
        candidate = {**trimmed, key: shortened}
        while shortened and _estimate_tokens(str(candidate)) > token_budget:
            shortened = _trim_text(shortened, max(0, _estimate_tokens(shortened) - 1))
            candidate = {**trimmed, key: shortened}
        if shortened:
            trimmed[key] = shortened
        break
    return trimmed


def _trim_state(state: StoryState, token_budget: int) -> StoryState:
    payload = state.model_dump()
    scalar_fields = ("location", "time", "mood", "objective")
    while True:
        candidate = StoryState(**payload)
        current_tokens = _estimate_tokens(candidate.model_dump_json())
        if current_tokens <= token_budget:
            return candidate

        scalar_costs = {
            field: _estimate_tokens(str(payload[field]))
            for field in scalar_fields
        }
        longest_scalar = max(scalar_costs, key=scalar_costs.get)
        if scalar_costs[longest_scalar] > 16:
            payload[longest_scalar] = _trim_text(
                str(payload[longest_scalar]),
                max(16, scalar_costs[longest_scalar] - ALLOCATION_QUANTUM),
            )
        elif payload["open_threads"]:
            payload["open_threads"] = payload["open_threads"][1:]
        elif payload["inventory"]:
            payload["inventory"] = payload["inventory"][1:]
        elif scalar_costs[longest_scalar] > 1:
            payload[longest_scalar] = _trim_text(
                str(payload[longest_scalar]),
                scalar_costs[longest_scalar] - 1,
            )
        else:
            return candidate


def _section_demands(
    *,
    state: StoryState,
    memories: list[str],
    canon_facts: list[str],
    world: dict,
    character: dict,
    user_preferences: list[str],
    story_prompt: str,
    recent_messages: list[dict],
    story_summary: str,
) -> dict[str, int]:
    return {
        "world": _estimate_tokens(str(world)),
        "character": _estimate_tokens(str(character)),
        "state": _estimate_tokens(state.model_dump_json()),
        "canon_facts": _estimate_tokens("\n".join(canon_facts)),
        "user_preferences": _estimate_tokens("\n".join(user_preferences)),
        "story_prompt": _estimate_tokens(story_prompt),
        "story_summary": _estimate_tokens(story_summary),
        "retrieved_memories": _estimate_tokens("\n".join(memories)),
        "recent_messages": _estimate_tokens(str(recent_messages)),
    }


def _allocate_section_budgets(
    demands: dict[str, int],
    available_tokens: int,
) -> dict[str, int]:
    budgets = {name: 0 for name in SECTION_ALLOCATION_PRIORITY}
    remaining = available_tokens
    for targets in (
        {
            name: min(demands[name], SECTION_MIN_TOKEN_BUDGETS[name])
            for name in SECTION_ALLOCATION_PRIORITY
        },
        {
            name: min(demands[name], SECTION_TOKEN_BUDGETS[name])
            for name in SECTION_ALLOCATION_PRIORITY
        },
    ):
        while remaining > 0:
            progressed = False
            for name in SECTION_ALLOCATION_PRIORITY:
                deficit = targets[name] - budgets[name]
                if deficit <= 0:
                    continue
                granted = min(ALLOCATION_QUANTUM, deficit, remaining)
                budgets[name] += granted
                remaining -= granted
                progressed = True
                if remaining == 0:
                    break
            if not progressed:
                break
    return budgets


def _trim_text(text: str, token_budget: int) -> str:
    return trim_to_token_budget(text, token_budget)


def _estimate_tokens(text: str) -> int:
    return estimate_tokens(text)
