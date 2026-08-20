from __future__ import annotations

import base64
import hashlib
import re
import statistics
import unicodedata
from dataclasses import dataclass


STYLE_ANALYSIS_VERSION = "style-profile-v1"
STYLE_SAFETY_VERSION = "overlap-bloom-v1"
MIN_REFERENCE_CHARACTERS = 500
MAX_REFERENCE_CHARACTERS = 30_000
_BLOOM_BITS = 262_144
_BLOOM_HASHES = 7


class StyleReproductionError(ValueError):
    pass


@dataclass(frozen=True)
class OverlapResult:
    blocked: bool
    character_ratio: float
    character_hits: int
    word_ratio: float
    word_hits: int


def normalize_reference_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def reference_content_hash(text: str) -> str:
    return hashlib.sha256(normalize_reference_text(text).encode("utf-8")).hexdigest()


def _normalized_characters(text: str) -> str:
    return "".join(
        character.casefold()
        for character in unicodedata.normalize("NFKC", text)
        if character.isalnum()
    )


def _normalized_words(text: str) -> list[str]:
    return re.findall(r"[\w']+", unicodedata.normalize("NFKC", text).casefold())


def _bloom_indexes(value: str, salt: str) -> list[int]:
    digest = hashlib.sha256(f"{salt}:{value}".encode()).digest()
    return [
        int.from_bytes(digest[index * 4 : index * 4 + 4], "big") % _BLOOM_BITS
        for index in range(_BLOOM_HASHES)
    ]


def _add_bloom(bits: bytearray, value: str, salt: str) -> None:
    for index in _bloom_indexes(value, salt):
        bits[index // 8] |= 1 << (index % 8)


def _has_bloom(bits: bytes, value: str, salt: str) -> bool:
    return all(bits[index // 8] & (1 << (index % 8)) for index in _bloom_indexes(value, salt))


def build_overlap_signature(text: str, content_hash: str) -> dict:
    bits = bytearray(_BLOOM_BITS // 8)
    characters = _normalized_characters(text)
    words = _normalized_words(text)
    for index in range(0, max(0, len(characters) - 31), 4):
        _add_bloom(bits, f"c:{characters[index:index + 32]}", content_hash)
    for index in range(0, max(0, len(words) - 7), 2):
        _add_bloom(bits, f"w:{' '.join(words[index:index + 8])}", content_hash)
    return {
        "version": STYLE_SAFETY_VERSION,
        "bits": _BLOOM_BITS,
        "hashes": _BLOOM_HASHES,
        "character_ngram": 32,
        "character_stride": 4,
        "word_ngram": 8,
        "word_stride": 2,
        "filter": base64.b64encode(bits).decode("ascii"),
    }


def _ratio(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def evaluate_reference_overlap(text: str, content_hash: str, signature: object) -> OverlapResult:
    if not isinstance(signature, dict) or signature.get("version") != STYLE_SAFETY_VERSION:
        return OverlapResult(False, 0.0, 0, 0.0, 0)
    try:
        bits = base64.b64decode(str(signature["filter"]), validate=True)
    except (KeyError, ValueError):
        return OverlapResult(False, 0.0, 0, 0.0, 0)
    if len(bits) * 8 != _BLOOM_BITS:
        return OverlapResult(False, 0.0, 0, 0.0, 0)
    characters = _normalized_characters(text)
    character_windows = [
        f"c:{characters[index:index + 32]}"
        for index in range(max(0, len(characters) - 31))
    ]
    words = _normalized_words(text)
    word_windows = [
        f"w:{' '.join(words[index:index + 8])}" for index in range(max(0, len(words) - 7))
    ]
    character_hits = sum(_has_bloom(bits, value, content_hash) for value in character_windows)
    word_hits = sum(_has_bloom(bits, value, content_hash) for value in word_windows)
    character_ratio = _ratio(character_hits, len(character_windows))
    word_ratio = _ratio(word_hits, len(word_windows))
    blocked = (character_hits >= 8 and character_ratio >= 0.18) or (
        word_hits >= 6 and word_ratio >= 0.35
    )
    return OverlapResult(
        blocked,
        character_ratio,
        character_hits,
        word_ratio,
        word_hits,
    )


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[。！？.!?])\s*", text) if item.strip()]


def _density(text: str, markers: tuple[str, ...]) -> float:
    lowered = text.casefold()
    return min(1.0, sum(lowered.count(marker) for marker in markers) / max(1, len(text) / 180))


def analyze_style_features(text: str, language: str, content_hash: str) -> dict:
    normalized = normalize_reference_text(text)
    sentences = _sentences(normalized)
    sentence_lengths = [len(_normalized_characters(sentence)) for sentence in sentences] or [0]
    paragraphs = normalized.split("\n")
    dialogue_characters = sum(
        len(line) for line in paragraphs if re.match(r'^[“"「『—-]', line.strip())
    )
    first_person = sum(normalized.count(token) for token in ("我", "我们", " i ", " we "))
    third_person = sum(normalized.count(token) for token in ("他", "她", "他们", " she ", " he "))
    viewpoint = "first" if first_person > third_person * 1.2 else "third" if third_person else "mixed"
    average = statistics.fmean(sentence_lengths)
    deviation = statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
    paragraph_average = statistics.fmean(len(_normalized_characters(item)) for item in paragraphs)
    dialogue_ratio = round(dialogue_characters / max(1, len(normalized)), 3)
    descriptive_density = round(
        _density(normalized, ("仿佛", "如同", "似乎", "微微", "缓慢", "silently", "seemed")),
        3,
    )
    figurative_density = round(
        _density(normalized, ("仿佛", "宛如", "好似", "like a", "as if", "as though")),
        3,
    )
    pacing = "fast" if average < 18 or dialogue_ratio > 0.38 else "slow" if average > 38 else "moderate"
    return {
        "sentence_length_mean": round(average, 1),
        "sentence_length_variation": (
            "high" if deviation > average * 0.65 else "low" if deviation < average * 0.3 else "medium"
        ),
        "paragraph_rhythm": (
            "compact" if paragraph_average < 90 else "expansive" if paragraph_average > 220 else "balanced"
        ),
        "dialogue_ratio": dialogue_ratio,
        "viewpoint": viewpoint,
        "tense": "contextual" if language.lower().startswith(("zh", "ja", "ko")) else "mixed",
        "descriptive_density": descriptive_density,
        "figurative_density": figurative_density,
        "pacing": pacing,
        "analysis_method": "deterministic",
        "_safety": build_overlap_signature(normalized, content_hash),
    }


def public_style_features(features: object) -> dict:
    if not isinstance(features, dict):
        return {}
    return {key: value for key, value in features.items() if not key.startswith("_")}


def style_prompt(features: object) -> str:
    public = public_style_features(features)
    if not public:
        return ""
    ordered = ", ".join(f"{key}={public[key]}" for key in sorted(public))
    return (
        "Apply this abstract prose profile without naming or imitating any author and without "
        f"reusing source wording: {ordered}."
    )


def assert_non_reproducing(text: str, content_hash: str, features: object) -> None:
    signature = features.get("_safety") if isinstance(features, dict) else None
    result = evaluate_reference_overlap(text, content_hash, signature)
    if result.blocked:
        raise StyleReproductionError("Generated prose overlapped the reference too closely")
