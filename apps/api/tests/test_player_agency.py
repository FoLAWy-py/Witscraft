from app.services.player_agency import (
    chapter_authoring_instruction,
    ensure_chapter_heading,
    reject_known_impossible_action,
)


def test_normal_turn_preserves_protagonist_control() -> None:
    instruction = chapter_authoring_instruction(
        control_mode="player_action",
        chapter_number=4,
        chapter_title="The Locked Gate",
        chapter_objective="Reveal the cost of entry.",
        target_length=1800,
        length_unit="words",
        prose_language="en",
    )
    assert "player controls the protagonist" in instruction
    assert "private thoughts" in instruction
    assert "approximately 1800" in instruction


def test_continue_delegates_exactly_one_reversible_turn() -> None:
    instruction = chapter_authoring_instruction(
        control_mode="continue",
        chapter_number=2,
        chapter_title="潮声",
        chapter_objective="推进线索。",
        target_length=1800,
        length_unit="characters",
        prose_language="zh-CN",
    )
    assert "for this chapter only" in instruction
    assert "delegation expires after this reply" in instruction
    assert "irreversible commitment" in instruction


def test_explicit_impossible_action_is_rejected_with_rule_reason() -> None:
    rejection = reject_known_impossible_action(
        "I teleport through the sealed gate.",
        {
            "impossible_actions": [
                {"action": "teleport", "reason": "Teleportation does not exist in this world."}
            ]
        },
    )
    assert rejection is not None
    assert rejection.reason == "Teleportation does not exist in this world."
    assert reject_known_impossible_action("I inspect the gate.", {"impossible_actions": []}) is None


def test_canonical_chapter_heading_is_idempotent() -> None:
    titled = ensure_chapter_heading("The gate opens.", 3, "The Last Lock")
    assert titled.startswith("## 3. The Last Lock\n\n")
    assert ensure_chapter_heading(titled, 3, "The Last Lock") == titled
