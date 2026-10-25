import pytest
from pydantic import ValidationError

from config import Settings

VALID = {
    "bot_token": "123456789:FAKE_TOKEN_FOR_TESTS",
    "admin_id": 123456789,
    "database_url": "postgresql+asyncpg://barber:password@localhost:5432/barber",
}


def test_valid_settings(monkeypatch):
    for key in ("BOT_TOKEN", "ADMIN_ID", "DATABASE_URL", "TIMEZONE", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    config = Settings(_env_file=None, **VALID)
    assert config.admin_id == 123456789
    assert config.timezone == "Asia/Dushanbe"
    assert "FAKE_TOKEN" not in repr(config)


def test_invalid_admin_id():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(VALID | {"admin_id": 0}))


def test_invalid_token():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(VALID | {"bot_token": "wrong-token"}))


def test_invalid_database_url():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(VALID | {"database_url": "sqlite:///demo.db"}))


def test_invalid_timezone():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(VALID | {"timezone": "Not/A_Timezone"}))
