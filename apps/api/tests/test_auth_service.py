from app.services.auth_service import (
    hash_action_token,
    hash_password,
    hash_session_token,
    make_login_throttle_key,
    normalize_email,
    verify_password,
)


def test_scrypt_password_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")

    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("incorrect", encoded)


def test_password_hashes_use_unique_salts() -> None:
    first = hash_password("same password")
    second = hash_password("same password")

    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


def test_email_normalization() -> None:
    assert normalize_email("  Author@Example.COM ") == "author@example.com"


def test_session_tokens_are_stored_as_digests() -> None:
    digest = hash_session_token("opaque-session-token")

    assert len(digest) == 64
    assert digest != "opaque-session-token"


def test_action_tokens_are_stored_as_digests() -> None:
    digest = hash_action_token("one-time-email-token")

    assert len(digest) == 64
    assert digest != "one-time-email-token"


def test_login_throttle_keys_normalize_email_and_isolate_client_hosts() -> None:
    first = make_login_throttle_key(" Author@Example.COM ", "192.0.2.1")

    assert first == make_login_throttle_key("author@example.com", "192.0.2.1")
    assert first != make_login_throttle_key("author@example.com", "192.0.2.2")
    assert "author@example.com" not in first
