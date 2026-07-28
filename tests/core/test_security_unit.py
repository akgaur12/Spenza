"""Unit tests for src/core/security.py — no DB, no HTTP."""

import uuid

import pytest

from src.core import security
from src.core.app_config import settings


def test_password_hash_and_verify_roundtrip() -> None:
    hashed = security.hash_password("SecureP@ss1")
    assert security.verify_password("SecureP@ss1", hashed)
    assert not security.verify_password("WrongPassword1!", hashed)


def test_verify_password_rejects_garbage_hash() -> None:
    assert not security.verify_password("anything", "not-a-real-argon2-hash")


def test_access_token_roundtrip() -> None:
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token = security.create_access_token(user_id, session_id)
    decoded = security.decode_token(token, expected_type=security.TokenType.ACCESS)
    assert decoded.subject == str(user_id)
    assert decoded.session_id == str(session_id)
    assert decoded.token_type is security.TokenType.ACCESS


def test_decode_token_wrong_type_raises() -> None:
    token = security.create_access_token(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(security.TokenInvalidError):
        security.decode_token(token, expected_type=security.TokenType.REFRESH)


def test_decode_token_tampered_signature_raises() -> None:
    token = security.create_access_token(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(security.TokenInvalidError):
        security.decode_token(token + "tampered", expected_type=security.TokenType.ACCESS)


def test_decode_token_expired_raises() -> None:
    original = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    try:
        settings.ACCESS_TOKEN_EXPIRE_MINUTES = -1
        token = security.create_access_token(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(security.TokenExpiredError):
            security.decode_token(token, expected_type=security.TokenType.ACCESS)
    finally:
        settings.ACCESS_TOKEN_EXPIRE_MINUTES = original


def test_refresh_token_hash_and_verify() -> None:
    raw = security.generate_refresh_token()
    hashed = security.hash_refresh_token(raw)
    assert security.verify_refresh_token(raw, hashed)
    assert not security.verify_refresh_token("some-other-token", hashed)


def test_otp_generate_hash_and_verify() -> None:
    otp = security.generate_otp()
    assert len(otp) == settings.OTP_LENGTH
    assert otp.isdigit()
    hashed = security.hash_otp(otp)
    assert security.verify_otp(otp, hashed)
    assert not security.verify_otp("000000" if otp != "000000" else "111111", hashed)


def test_action_token_roundtrip_and_wrong_purpose() -> None:
    token = security.create_action_token(
        subject="user-123", purpose="password_reset", expire_minutes=10
    )
    payload = security.decode_action_token(token, expected_purpose="password_reset")
    assert payload["sub"] == "user-123"

    with pytest.raises(security.TokenInvalidError):
        security.decode_action_token(token, expected_purpose="something_else")


def test_action_token_expired_raises() -> None:
    token = security.create_action_token(
        subject="user-123", purpose="password_reset", expire_minutes=-1
    )
    with pytest.raises(security.TokenExpiredError):
        security.decode_action_token(token, expected_purpose="password_reset")
