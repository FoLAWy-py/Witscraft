from app.services.style_profiles import (
    STYLE_ANALYSIS_VERSION,
    analyze_style_features,
    assert_non_reproducing,
    evaluate_reference_overlap,
    public_style_features,
    reference_content_hash,
    style_prompt,
)


REFERENCE = "\n".join(
    f"第{index}段的潮声穿过石阶，留下不同的灯影与钟声。守夜人记录天气，却不替旅人选择方向。"
    for index in range(1, 45)
)


def test_abstract_profile_is_deterministic_and_hides_safety_signature() -> None:
    content_hash = reference_content_hash(REFERENCE)
    features = analyze_style_features(REFERENCE, "zh-CN", content_hash)

    assert STYLE_ANALYSIS_VERSION == "style-profile-v1"
    assert features == analyze_style_features(REFERENCE, "zh-CN", content_hash)
    assert features["analysis_method"] == "deterministic"
    assert "_safety" in features
    assert "_safety" not in public_style_features(features)
    assert REFERENCE[:80] not in str(features)
    prompt = style_prompt(features)
    assert "without naming or imitating any author" in prompt
    assert "paragraph rhythm" in prompt
    assert "dialogue" in prompt
    assert "overriding player agency" in prompt
    assert REFERENCE[:20] not in prompt


def test_seeded_overlap_is_blocked_but_abstractly_similar_text_is_allowed() -> None:
    content_hash = reference_content_hash(REFERENCE)
    features = analyze_style_features(REFERENCE, "zh-CN", content_hash)
    copied = REFERENCE[120:520]
    result = evaluate_reference_overlap(copied, content_hash, features["_safety"])

    assert result.blocked is True
    try:
        assert_non_reproducing(copied, content_hash, features)
    except ValueError as error:
        assert "overlapped" in str(error)
    else:
        raise AssertionError("seeded overlap should be rejected")

    original = "雾散以后，港口只剩修船的敲击声。陌生人把地图折好，等待玩家决定是否靠近。"
    assert evaluate_reference_overlap(original, content_hash, features["_safety"]).blocked is False
    assert_non_reproducing(original, content_hash, features)


def test_overlap_normalization_survives_spacing_punctuation_and_case_changes() -> None:
    english_reference = " ".join(
        f"Lantern {index} watches the patient harbor while the tide records another quiet crossing."
        for index in range(1, 90)
    )
    content_hash = reference_content_hash(english_reference)
    features = analyze_style_features(english_reference, "en", content_hash)
    copied_words = english_reference.split()[45:105]
    obfuscated = " , \n".join(word.swapcase() for word in copied_words)

    result = evaluate_reference_overlap(obfuscated, content_hash, features["_safety"])
    assert result.blocked is True
    assert result.word_hits >= 6

    common_short_phrase = "The harbor is quiet tonight."
    assert (
        evaluate_reference_overlap(common_short_phrase, content_hash, features["_safety"]).blocked
        is False
    )


def test_fast_dialogue_profile_becomes_an_observable_scene_contract() -> None:
    prompt = style_prompt(
        {
            "viewpoint": "third",
            "pacing": "fast",
            "paragraph_rhythm": "compact",
            "sentence_length_variation": "high",
            "sentence_length_mean": 44.7,
            "dialogue_ratio": 0.412,
            "descriptive_density": 0.0,
            "figurative_density": 0.0,
        }
    )

    assert "each paragraph change information, relationship pressure, or physical position" in prompt
    assert "remove repeated atmospheric beats" in prompt
    assert "sustained back-and-forth NPC exchanges" in prompt
    assert "standalone dialogue paragraphs" in prompt
    assert "do not replace intended dialogue with narrated reports" in prompt
