"""Unit tests for src/modules/users/validators.py."""

import pytest

from src.modules.users.validators import validate_password_strength, validate_username


@pytest.mark.parametrize("username", ["jane_doe", "abc", "J_1", "a" * 30])
def test_validate_username_accepts_valid(username: str) -> None:
    assert validate_username(username) == username


@pytest.mark.parametrize(
    "username",
    [
        "ab",  # too short
        "1abc",  # must start with a letter
        "a" * 31,  # too long
        "jane doe",  # spaces not allowed
        "jane-doe",  # hyphen not allowed
    ],
)
def test_validate_username_rejects_invalid(username: str) -> None:
    with pytest.raises(ValueError, match="Username"):
        validate_username(username)


def test_validate_password_strength_accepts_strong_password() -> None:
    assert validate_password_strength("SecureP@ss1") == "SecureP@ss1"


@pytest.mark.parametrize(
    "password",
    [
        "short1!",  # too short
        "alllowercase1!",  # no uppercase
        "ALLUPPERCASE1!",  # no lowercase
        "NoDigitsHere!",  # no digit
        "NoSpecialChar1",  # no special character
    ],
)
def test_validate_password_strength_rejects_weak(password: str) -> None:
    with pytest.raises(ValueError, match="Password must"):
        validate_password_strength(password)
