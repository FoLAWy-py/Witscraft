from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    if not text:
        return 0

    wide_characters = sum(1 for character in text if _is_wide_character(character))
    compact_characters = len(text) - wide_characters
    return max(1, wide_characters + math.ceil(compact_characters / 4))


def trim_to_token_budget(text: str, token_budget: int) -> str:
    if token_budget <= 0 or not text:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text

    low = 0
    high = len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= token_budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def _is_wide_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x2E80 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0xFF00 <= codepoint <= 0xFFEF
    )
