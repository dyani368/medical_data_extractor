import pytest
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import Mock

from app.schemas.user_schema import UserCreate
from app.routers import auth


def test_registration_rejects_weak_password():
    with pytest.raises(ValidationError):
        UserCreate(username="demo", email="demo@example.com", password="short")


def test_registration_accepts_long_password():
    user = UserCreate(username="demo", email="demo@example.com", password="correct horse battery")
    assert user.username == "demo"


@pytest.mark.parametrize("identifier, column", [("demo", "users.username"), ("DEMO@EXAMPLE.COM", "users.email")])
def test_login_accepts_username_or_email(monkeypatch, identifier, column):
    user = SimpleNamespace(id=7, hashed_password="stored-hash")
    db = Mock()
    db.execute.return_value.scalars.return_value.first.return_value = user
    monkeypatch.setattr(auth.security, "verify_password", lambda password, hashed: password == "correct" and hashed == "stored-hash")
    monkeypatch.setattr(auth.security, "create_access_token", lambda data: f"token-{data['sub']}")

    result = auth.login(SimpleNamespace(username=identifier, password="correct"), db)

    assert result["access_token"] == "token-7"
    assert column in str(db.execute.call_args.args[0])
