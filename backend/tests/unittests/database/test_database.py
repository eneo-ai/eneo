from types import SimpleNamespace
from unittest.mock import MagicMock

from eneo.database import database as database_module


def test_database_engine_honors_configured_pool_settings(monkeypatch):
    settings = SimpleNamespace(
        db_pool_size=7,
        db_pool_max_overflow=3,
        db_pool_timeout=11,
        db_pool_pre_ping=False,
        db_pool_recycle=90,
        db_pool_debug=True,
    )
    engine = MagicMock()
    create_async_engine = MagicMock(return_value=engine)
    monkeypatch.setattr(
        database_module, "get_settings", lambda: settings, raising=False
    )
    monkeypatch.setattr(database_module, "create_async_engine", create_async_engine)

    manager = database_module.DatabaseSessionManager()
    manager.init("postgresql+asyncpg://database")

    create_async_engine.assert_called_once_with(
        "postgresql+asyncpg://database",
        pool_size=7,
        max_overflow=3,
        pool_timeout=11,
        pool_pre_ping=False,
        pool_recycle=90,
        echo_pool=True,
    )


def test_database_pool_defaults_are_unchanged(test_settings):
    assert test_settings.db_pool_size == 20
    assert test_settings.db_pool_max_overflow == 10
    assert test_settings.db_pool_debug is False
