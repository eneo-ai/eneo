from unittest.mock import MagicMock

from intric.database import database
from intric.main.config import Settings


def test_database_session_manager_defaults_match_settings_defaults(monkeypatch):
    captured: dict[str, object] = {}
    settings = Settings.model_construct()

    def fake_create_async_engine(host: str, **kwargs: object) -> object:
        captured["host"] = host
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)

    manager = database.DatabaseSessionManager()
    manager.init("postgresql+asyncpg://test")

    assert captured == {
        "host": "postgresql+asyncpg://test",
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_pool_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_pre_ping": settings.db_pool_pre_ping,
        "pool_recycle": settings.db_pool_recycle,
        "echo_pool": "debug" if settings.db_pool_debug else False,
    }


def test_database_session_manager_passes_pool_settings_to_engine(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_async_engine(host: str, **kwargs: object) -> object:
        captured["host"] = host
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(database, "create_async_engine", fake_create_async_engine)

    manager = database.DatabaseSessionManager()
    manager.init(
        "postgresql+asyncpg://test",
        pool_size=7,
        max_overflow=3,
        pool_timeout=11,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_debug=True,
    )

    assert captured == {
        "host": "postgresql+asyncpg://test",
        "pool_size": 7,
        "max_overflow": 3,
        "pool_timeout": 11,
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "echo_pool": "debug",
    }
