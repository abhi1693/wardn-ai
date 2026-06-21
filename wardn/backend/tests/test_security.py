import uuid

from app.core.security import (
    create_session_token,
    extract_api_token_key,
    generate_api_token,
    hash_api_token,
    hash_password,
    verify_api_token,
    verify_password,
    verify_session_token,
)


def test_password_hash_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_api_token_hash_round_trip() -> None:
    key, token = generate_api_token()
    token_hash = hash_api_token(token)

    assert extract_api_token_key(token) == key
    assert verify_api_token(token, token_hash)
    assert not verify_api_token(f"{token}x", token_hash)


def test_session_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(user_id)

    assert verify_session_token(token) == user_id
    assert verify_session_token(f"{token}x") is None
