import pytest
from pydantic import ValidationError

from app.schemas.user_schema import UserCreate


def test_registration_rejects_weak_password():
    with pytest.raises(ValidationError):
        UserCreate(username="demo", email="demo@example.com", password="short")


def test_registration_accepts_long_password():
    user = UserCreate(username="demo", email="demo@example.com", password="correct horse battery")
    assert user.username == "demo"
