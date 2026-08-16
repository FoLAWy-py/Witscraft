from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.schemas.chat import StoryState


RESURRECTION_MARKERS = ("复活", "活着", "醒来", "苏醒", "站起来", "重新出现", "开口说话")
NEGATION_MARKERS = ("不能", "无法", "不会", "禁止", "不允许", "不得")


@dataclass(frozen=True)
class ConsistencyIssue:
    severity: str
    source: str
    rule: str
    reference: str
    evidence: str
    message: str


def check_response_consistency(
    response_text: str,
    state: StoryState,
    canon_facts: list[str],
    character: dict[str, Any],
    world: dict[str, Any],
) -> dict:
    issues: list[ConsistencyIssue] = []
    issues.extend(_check_canon_facts(response_text, canon_facts))
    issues.extend(_check_state_continuity(response_text, state))
    issues.extend(_check_character_constraints(response_text, character))
    issues.extend(_check_world_rules(response_text, world))

    return {
        "status": "fail" if any(issue.severity == "error" for issue in issues) else "pass",
        "issue_count": len(issues),
        "issues": [asdict(issue) for issue in issues],
    }


def _check_canon_facts(response_text: str, canon_facts: list[str]) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for fact in canon_facts:
        subject = _extract_subject(fact)
        if not subject:
            continue
        if _mentions_death(fact) and subject in response_text and any(marker in response_text for marker in RESURRECTION_MARKERS):
            issues.append(
                ConsistencyIssue(
                    severity="error",
                    source="canon_facts",
                    rule="dead_character_resurrection",
                    reference=fact,
                    evidence=_sentence_with(response_text, subject),
                    message=f"Canon states `{subject}` is dead, but the response appears to bring them back.",
                )
            )
        issues.extend(_check_is_not_fact(response_text, fact, subject))
        issues.extend(_check_negative_capability(response_text, fact, subject))
    return issues


def _check_is_not_fact(response_text: str, fact: str, subject: str) -> list[ConsistencyIssue]:
    match = re.search(r"不是(?P<predicate>[^，。！？\n]{1,18})", fact)
    if not match:
        return []
    predicate = _clean(match.group("predicate"))
    if subject in response_text and predicate and re.search(fr"{re.escape(subject)}[^。！？\n]{{0,16}}是[^。！？\n]{{0,12}}{re.escape(predicate)}", response_text):
        return [
            ConsistencyIssue(
                severity="error",
                source="canon_facts",
                rule="negated_identity_conflict",
                reference=fact,
                evidence=_sentence_with(response_text, subject),
                message=f"Canon negates `{subject}` as `{predicate}`, but the response asserts it.",
            )
        ]
    return []


def _check_negative_capability(response_text: str, fact: str, subject: str) -> list[ConsistencyIssue]:
    if not any(marker in fact for marker in NEGATION_MARKERS):
        return []
    action = _extract_negative_action(fact)
    if not action or subject not in response_text:
        return []
    if re.search(fr"{re.escape(subject)}[^。！？\n]{{0,18}}{re.escape(action)}", response_text):
        return [
            ConsistencyIssue(
                severity="warning",
                source="canon_facts",
                rule="negative_capability_warning",
                reference=fact,
                evidence=_sentence_with(response_text, subject),
                message=f"Canon limits `{subject}` from `{action}`, but the response may allow it.",
            )
        ]
    return []


def _check_state_continuity(response_text: str, state: StoryState) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    if state.time and _has_conflicting_time(response_text, state.time):
        issues.append(
            ConsistencyIssue(
                severity="warning",
                source="scene_state",
                rule="time_jump_without_transition",
                reference=state.time,
                evidence=_sentence_with_any(response_text, ("清晨", "早晨", "上午", "中午", "下午", "傍晚", "黄昏", "夜晚", "深夜", "凌晨", "午夜")),
                message="Response appears to change scene time without an explicit transition.",
            )
        )

    missing_inventory = [item for item in state.inventory if item and _uses_missing_inventory(response_text, item)]
    for item in missing_inventory[:3]:
        issues.append(
            ConsistencyIssue(
                severity="warning",
                source="scene_state",
                rule="inventory_continuity",
                reference=item,
                evidence=_sentence_with(response_text, item),
                message=f"Response uses `{item}`; verify it remains in inventory after this turn.",
            )
        )
    return issues


def _check_character_constraints(response_text: str, character: dict[str, Any]) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    secret = _clean(str(character.get("secret", "")))
    name = _clean(str(character.get("name", "")))
    if secret and secret in response_text:
        issues.append(
            ConsistencyIssue(
                severity="warning",
                source="character_profile",
                rule="secret_revealed",
                reference=f"{name}: {secret}" if name else secret,
                evidence=_sentence_with(response_text, secret),
                message="Response may reveal a character secret; verify this reveal is intentional.",
            )
        )
    return issues


def _check_world_rules(response_text: str, world: dict[str, Any]) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    rules = world.get("rules")
    if not isinstance(rules, dict):
        return issues
    for key, value in rules.items():
        text = _clean(str(value))
        if not text or not any(marker in text for marker in NEGATION_MARKERS):
            continue
        action = _extract_negative_action(text)
        if action and action in response_text:
            issues.append(
                ConsistencyIssue(
                    severity="warning",
                    source="world_rules",
                    rule="world_rule_warning",
                    reference=f"{key}: {text}",
                    evidence=_sentence_with(response_text, action),
                    message=f"World rule may forbid `{action}`, but the response includes it.",
                )
            )
    return issues


def _extract_subject(text: str) -> str:
    cleaned = _clean(text)
    for marker in ("已经死亡", "不能复活", "无法复活", "不是", "不能", "无法", "不会"):
        if marker in cleaned:
            return _clean(cleaned.split(marker, 1)[0])[-18:]
    return ""


def _extract_negative_action(text: str) -> str:
    match = re.search(r"(?:不能|无法|不会|禁止|不允许|不得)(?P<action>[^，。！？\n]{1,18})", text)
    return _clean(match.group("action")) if match else ""


def _mentions_death(text: str) -> bool:
    return any(marker in text for marker in ("已经死亡", "死亡", "死去", "不能复活", "无法复活"))


def _has_conflicting_time(response_text: str, current_time: str) -> bool:
    time_markers = ("清晨", "早晨", "上午", "中午", "下午", "傍晚", "黄昏", "夜晚", "深夜", "凌晨", "午夜")
    if not any(marker in response_text for marker in time_markers):
        return False
    if current_time and current_time in response_text:
        return False
    transition_markers = ("后来", "数小时后", "天亮", "入夜", "第二天", "时间一晃", "转眼")
    return not any(marker in response_text for marker in transition_markers)


def _uses_missing_inventory(response_text: str, item: str) -> bool:
    if item not in response_text:
        return False
    return any(verb in response_text for verb in ("拿出", "握紧", "插入", "递出", "打开", "使用"))


def _sentence_with(text: str, needle: str) -> str:
    for sentence in re.split(r"(?<=[。！？\n])", text):
        if needle in sentence:
            return sentence.strip()[:180]
    return text[:180]


def _sentence_with_any(text: str, needles: tuple[str, ...]) -> str:
    for needle in needles:
        if needle in text:
            return _sentence_with(text, needle)
    return text[:180]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n：:，。！？“”\"'`*-")
