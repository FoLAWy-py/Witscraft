from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.llm.router import LLMGateway
from app.schemas.chat import StoryState
from app.schemas.llm import ChatMessage


LOCATION_PATTERNS = [
    re.compile(r"(?:进入|抵达|来到|走进|到达|身处|停在|留在|位于)(?P<value>[^，。！？\n]{2,24})"),
]
TIME_PATTERNS = [
    re.compile(r"(清晨|早晨|上午|中午|下午|傍晚|黄昏|夜晚|深夜|凌晨|午夜)"),
    re.compile(r"倒计时[:：]?\s*(\d+\s*秒)"),
]
OBJECT_PATTERNS = [
    re.compile(r"(?:拿出|拿起|拾起|获得|捡起|收起|带上|插入|握紧|取出)(?P<value>[^，。！？\n]{1,18})"),
]
THREAD_PATTERNS = [
    re.compile(r"(?:关于|查明|确认|调查|寻找|弄清|发现)(?P<value>[^，。！？\n]{4,36})"),
    re.compile(r"(?P<value>[^，。！？\n]{2,20})(?:真相|身份|位置|目的|秘密)"),
]
CANON_PATTERNS = [
    re.compile(r"(?P<value>[^。！？\n]{2,48}(?:已经死亡|不能复活|不是|是|无法|必须|不会)[^。！？\n]{0,24})[。！？]?"),
]


@dataclass
class ExtractionResult:
    state: StoryState
    relationships: list[dict] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)
    canon_facts: list[str] = field(default_factory=list)
    source: str = "deterministic"


class RelationshipUpdate(BaseModel):
    from_name: str = Field(alias="from", min_length=1, max_length=80)
    to_name: str = Field(alias="to", min_length=1, max_length=80)
    bond: str = Field(min_length=1, max_length=80)
    value: int = Field(ge=-100, le=100)


class StructuredStateUpdate(BaseModel):
    location: str | None = Field(default=None, max_length=120)
    time: str | None = Field(default=None, max_length=120)
    mood: str | None = Field(default=None, max_length=160)
    objective: str | None = Field(default=None, max_length=300)
    inventory: list[str] | None = None
    open_threads: list[str] | None = None
    relationships: list[RelationshipUpdate] | None = None
    memories: list[str] = Field(default_factory=list)
    canon_facts: list[str] = Field(default_factory=list)


async def extract_story_updates_with_llm(
    gateway: LLMGateway,
    previous: StoryState,
    user_message: str,
    assistant_message: str,
    relationships: list[dict] | None = None,
    perspective_character: str | None = None,
) -> ExtractionResult:
    fallback = extract_story_updates(
        previous,
        user_message,
        assistant_message,
        relationships=relationships,
    )
    prompt = {
        "previous_state": previous.model_dump(),
        "previous_relationships": relationships or [],
        "perspective_character": perspective_character,
        "user_turn": user_message,
        "assistant_turn": assistant_message,
    }
    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是小说连续性状态提取器。只提取本轮结束时明确成立的信息，不续写剧情。"
                "返回 JSON：location、time、mood、objective 可为 null；inventory、open_threads、"
                "relationships 可为 null 表示沿用旧值；memories、canon_facts 为本轮新增数组。"
                "mood 是当前场景情绪而非作品文风；objective 是角色眼下可执行目标而非故事简介。"
                "location 只表示本轮结束时角色实际身处的地点；不要求文本使用固定动词。计划前往、讨论是否去、"
                "看见远处地点、回忆某地，以及‘站在某人角度/立场’等抽象表达都不得更新 location。"
                "inventory 是角色当前持有物品的完整列表；open_threads 仅保留尚未解决的具体问题。"
                "relationships 要包含文本明确说明的长期关系，即使相关人物未在现场；每项必须含"
                " from、to、bond、value（-100 到 100）。"
                "若文本说明某个新称呼只是既有角色的职阶、称号、代号或别名，必须沿用既有实体"
                "名称，不得为该称呼新增第二条关系。"
                "memory 只写值得后续召回的行动或事件；canon 只写稳定事实，禁止写比喻、疑问、"
                "备选行动或推测。禁止补充本轮文本没有出现的姓名、物品、日期、时间或背景。"
                "relationships 必须是数组，例如 [{\"from\":\"甲\",\"to\":\"乙\","
                "\"bond\":\"信任\",\"value\":60}]，没有关系变化时返回 null。"
                "所有文本使用简洁中文。"
            ),
        ),
        ChatMessage(role="user", content=json.dumps(prompt, ensure_ascii=False)),
    ]
    request = gateway.request_for_purpose("state_update", messages).model_copy(
        update={
            "max_output_tokens": 1800,
            "temperature": 0.2,
            "top_p": 0.85,
            "response_format": "json",
            "stream": False,
        }
    )
    try:
        response = await gateway.generate(gateway.normalize_request(request))
        raw_payload = json.loads(_json_object_text(response.text))
        if not isinstance(raw_payload, dict):
            raise ValueError("Structured state response must be an object")
        raw_payload["relationships"] = _normalize_relationship_shape(
            raw_payload.get("relationships"), perspective_character
        )
        payload = StructuredStateUpdate.model_validate(raw_payload)
    except Exception:
        fallback.canon_facts = []
        return fallback

    source_text = f"{user_message}\n{assistant_message}"
    state = StoryState(
        location=_grounded_location(payload.location, fallback.state.location, source_text),
        time=_grounded_value(payload.time, fallback.state.time, source_text),
        mood=_generated_value(payload.mood, fallback.state.mood),
        objective=_grounded_value(payload.objective, fallback.state.objective, source_text),
        inventory=_grounded_list(
            payload.inventory,
            fallback.state.inventory,
            source_text,
            limit=20,
            reject_negated=True,
        ),
        open_threads=_grounded_list(
            payload.open_threads,
            fallback.state.open_threads,
            source_text,
            limit=12,
        ),
    )
    relationship_source = f"{source_text}\n{json.dumps(relationships or [], ensure_ascii=False)}"
    extracted_relationships = (
        [
            item.model_dump(by_alias=True)
            for item in payload.relationships
            if _is_grounded(item.from_name, relationship_source)
            and _is_grounded(item.to_name, relationship_source)
        ]
        if payload.relationships is not None
        else list(relationships or [])
    )
    if not extracted_relationships and perspective_character:
        extracted_relationships = _infer_explicit_relationships(
            source_text, perspective_character
        )
    aliases = _relationship_aliases(
        source_text,
        relationships or [],
        perspective_character,
    )
    normalized_relationships = _canonicalize_relationships(extracted_relationships, aliases)
    return ExtractionResult(
        state=state,
        relationships=normalized_relationships[:20],
        memories=_grounded_list(payload.memories, [], source_text, limit=3),
        canon_facts=_grounded_list(payload.canon_facts, [], source_text, limit=4),
        source="llm",
    )


def extract_story_updates(
    previous: StoryState,
    user_message: str,
    assistant_message: str,
    relationships: list[dict] | None = None,
) -> ExtractionResult:
    text = f"{user_message}\n{assistant_message}"
    location = _extract_location(text) or previous.location
    time = _extract_time(text) or previous.time
    inventory = _merge_unique(previous.inventory, _extract_objects(text))
    open_threads = _merge_unique(previous.open_threads, _extract_threads(text), limit=8)

    state = StoryState(
        location=location,
        time=time,
        mood=_infer_mood(text, previous.mood),
        objective=_infer_objective(text, previous.objective, open_threads),
        inventory=inventory,
        open_threads=open_threads,
    )
    memory = _summarize_memory(user_message, assistant_message, location, time)
    canon_facts = _extract_canon_facts(text)
    return ExtractionResult(
        state=state,
        relationships=list(relationships or []),
        memories=[memory] if memory else [],
        canon_facts=canon_facts,
    )


def _extract_location(text: str) -> str | None:
    for pattern in LOCATION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = match.groupdict().get("value") or match.group(0)
        return _clean_phrase(value)
    return None


def _extract_time(text: str) -> str | None:
    for pattern in TIME_PATTERNS:
        match = pattern.search(text)
        if match:
            return _clean_phrase(match.group(1))
    return None


def _extract_objects(text: str) -> list[str]:
    objects: list[str] = []
    for pattern in OBJECT_PATTERNS:
        for match in pattern.finditer(text):
            value = _clean_phrase(match.group("value"))
            if value and len(value) <= 18:
                objects.append(value)
    return objects


def _extract_threads(text: str) -> list[str]:
    threads: list[str] = []
    for pattern in THREAD_PATTERNS:
        for match in pattern.finditer(text):
            value = _clean_phrase(match.group("value"))
            if 4 <= len(value) <= 36:
                threads.append(value if value.endswith(("真相", "身份", "位置", "目的", "秘密")) else value)
    return threads


def _extract_canon_facts(text: str) -> list[str]:
    facts: list[str] = []
    for pattern in CANON_PATTERNS:
        for match in pattern.finditer(text):
            value = _clean_phrase(match.group("value"))
            uncertain = ("仿佛", "像是", "是否", "也许", "可能", "或是", "选择", "？")
            if (
                4 <= len(value) <= 72
                and not value.startswith(("如果", "也许", "可能"))
                and not any(marker in value for marker in uncertain)
            ):
                facts.append(value if value.endswith(("。", "！", "？")) else f"{value}。")
    return _merge_unique([], facts, limit=4)


def _infer_mood(text: str, previous: str) -> str:
    mood_map = [
        (("警报", "倒计时", "追", "封锁", "危险"), "紧张、急迫、被追踪"),
        (("低声", "屏住呼吸", "躲", "暗"), "压抑、低声、警觉"),
        (("犹豫", "沉默", "信任", "骗"), "犹疑、试探、慢热"),
        (("愤怒", "颤抖", "苍白"), "震动、压抑、濒临失控"),
    ]
    for keys, mood in mood_map:
        if any(key in text for key in keys):
            return mood
    return previous


def _infer_objective(text: str, previous: str, open_threads: list[str]) -> str:
    if open_threads:
        return f"继续推进：{open_threads[0]}"
    return previous


def _summarize_memory(user_message: str, assistant_message: str, location: str, time: str) -> str:
    user = _clean_phrase(user_message)
    assistant_sentences = [part.strip() for part in re.split(r"[。！？\n]+", assistant_message) if part.strip()]
    if not user or not assistant_sentences:
        return ""
    scene = f"{time}，{location}" if location and time else location or time or "当前场景"
    summary = assistant_sentences[0]
    return f"{scene}：用户选择“{user[:36]}”，随后{summary[:72]}。"


def _merge_unique(existing: list[str], incoming: list[str], limit: int | None = None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        cleaned = _clean_phrase(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
        if limit and len(merged) >= limit:
            break
    return merged


def _clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n：:，。！？“”\"'`*-")


def _json_object_text(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Structured state response did not contain a JSON object")
    return stripped[start : end + 1]


def _generated_value(value: str | None, fallback: str) -> str:
    cleaned = _clean_phrase(value or "")
    return cleaned if cleaned and cleaned not in {"不变", "沿用", "null"} else fallback


def _generated_list(values: list[str] | None, fallback: list[str], *, limit: int) -> list[str]:
    if values is None:
        return list(fallback)
    return _merge_unique([], values, limit=limit)


def _grounded_value(value: str | None, fallback: str, source: str) -> str:
    generated = _generated_value(value, fallback)
    if generated == fallback or _is_grounded(generated, source):
        return generated
    return fallback


def _grounded_location(value: str | None, fallback: str, source: str) -> str:
    candidate = _generated_value(value, fallback)
    if candidate == fallback:
        return fallback
    compact_candidate = re.sub(r"\s+", "", candidate)
    if any(marker in compact_candidate for marker in ("角度", "立场", "观点", "层面", "意义", "程度")):
        return fallback
    if not compact_candidate or compact_candidate not in re.sub(r"\s+", "", source):
        return fallback
    if fallback in {"", "未设定"}:
        return candidate

    planning_markers = ("准备去", "打算去", "要去", "想去", "是否去", "前往", "去不去", "能不能去")
    arrival_markers = ("进入", "抵达", "来到", "走进", "到达", "身处", "停在", "留在", "位于")
    for segment in re.split(r"[，,。！？；;\n]+", source):
        compact_segment = re.sub(r"\s+", "", segment)
        if compact_candidate not in compact_segment:
            continue
        if any(marker in compact_segment for marker in planning_markers) and not any(
            marker in compact_segment for marker in arrival_markers
        ):
            continue
        located = (
            any(marker in compact_segment for marker in arrival_markers)
            or f"在{compact_candidate}" in compact_segment
            or any(f"{compact_candidate}{suffix}" in compact_segment for suffix in ("里", "内", "中", "前", "入口", "站台"))
        )
        if located:
            return candidate
    return fallback


def _grounded_list(
    values: list[str] | None,
    fallback: list[str],
    source: str,
    *,
    limit: int,
    preserve_fallback: bool = False,
    reject_negated: bool = False,
) -> list[str]:
    if values is None:
        return list(fallback)
    grounded = [
        value
        for value in values
        if _is_grounded(value, source) and not (reject_negated and _is_negated(value, source))
    ]
    base = fallback if preserve_fallback else []
    return _merge_unique(base, grounded, limit=limit)


def _is_grounded(value: str, source: str) -> bool:
    cleaned = _clean_phrase(value)
    compact_source = re.sub(r"\s+", "", source)
    compact_value = re.sub(r"\s+", "", cleaned)
    if not compact_value:
        return False
    if compact_value in compact_source:
        return True
    grams = {compact_value[index : index + 2] for index in range(len(compact_value) - 1)}
    if not grams:
        return compact_value in compact_source
    matches = sum(1 for gram in grams if gram in compact_source)
    return matches / len(grams) >= 0.45


def _is_negated(value: str, source: str) -> bool:
    markers = ("没有拿", "没拿", "未拿", "没有带", "未携带", "放下", "丢下", "丢弃", "失去")
    for segment in re.split(r"[，,。！？；\n]+", source):
        for marker in markers:
            marker_index = segment.find(marker)
            if marker_index >= 0 and _is_grounded(value, segment[marker_index:]):
                return True
    return False


def _normalize_relationship_shape(value, perspective_character: str | None):
    if value is None or isinstance(value, list):
        return value
    if not isinstance(value, dict) or not perspective_character:
        return None
    normalized = []
    for target_label, description in value.items():
        target = _relationship_target(str(target_label))
        if not target:
            continue
        bond = _relationship_bond(str(target_label), str(description))
        normalized.append(
            {
                "from": perspective_character,
                "to": target,
                "bond": bond,
                "value": 70 if bond in {"兄长", "哥哥", "姐姐", "妹妹", "家人", "牵挂"} else 40,
            }
        )
    return normalized or None


def _relationship_aliases(
    source: str,
    existing: list[dict],
    perspective_character: str | None,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    candidates = {
        str(item.get(key, "")).strip()
        for item in existing
        for key in ("from", "to")
        if str(item.get(key, "")).strip()
        and str(item.get(key, "")).strip() != perspective_character
    }
    pattern = re.compile(
        r"[“\"‘'](?P<alias>[\u4e00-\u9fff]{2,8})[”\"’']"
        r"[。！？；，,\s]{0,6}不是名字[，,]?\s*是(?:一种)?(?:职阶|称号|代号|别名)"
    )
    for match in pattern.finditer(source):
        alias = match.group("alias")
        prefix = source[max(0, match.start() - 320) : match.start()]
        ranked = sorted(
            ((prefix.rfind(candidate), candidate) for candidate in candidates if candidate != alias),
            reverse=True,
        )
        if ranked and ranked[0][0] >= 0:
            aliases[alias] = ranked[0][1]
    return aliases


def _canonicalize_relationships(items: list[dict], aliases: dict[str, str]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for item in items:
        from_name = aliases.get(str(item.get("from", "")), str(item.get("from", "")))
        to_name = aliases.get(str(item.get("to", "")), str(item.get("to", "")))
        if not from_name or not to_name or from_name == to_name:
            continue
        normalized = {**item, "from": from_name, "to": to_name}
        merged[(from_name, to_name)] = normalized
    return list(merged.values())[:20]


def _infer_explicit_relationships(source: str, perspective_character: str) -> list[dict]:
    kinship = ("兄长", "哥哥", "姐姐", "妹妹", "父亲", "母亲", "弟弟", "家人")
    pattern = re.compile(
        rf"(?P<bond>{'|'.join(kinship)})(?P<name>[\u4e00-\u9fff]{{2,4}}?)"
        rf"(?=留下|说|的|在|已|，|。|；|\s|$)"
    )
    relationships = []
    for match in pattern.finditer(source):
        target = match.group("name")
        if target == perspective_character:
            continue
        relationships.append(
            {
                "from": perspective_character,
                "to": target,
                "bond": match.group("bond"),
                "value": 70,
            }
        )
    return relationships[:6]


def _relationship_target(label: str) -> str:
    parenthetical = re.search(r"[（(]([\u4e00-\u9fff]{2,4})[）)]", label)
    if parenthetical:
        return parenthetical.group(1)
    cleaned = re.sub(r"兄长|哥哥|姐姐|妹妹|父亲|母亲|弟弟|家人", "", label)
    name = re.search(r"[\u4e00-\u9fff]{2,4}", cleaned)
    return name.group(0) if name else ""


def _relationship_bond(label: str, description: str) -> str:
    for bond in ("兄长", "哥哥", "姐姐", "妹妹", "父亲", "母亲", "弟弟", "家人", "牵挂"):
        if bond in label or bond in description:
            return bond
    return _clean_phrase(description)[:24] or "关联"
