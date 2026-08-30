"""Tests for safe database environment configuration."""

import pytest

from app import database
from app.config import Settings


def test_sqlite_is_allowed_in_local_mode(tmp_path, monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        app_env="local",
        database_url=f"sqlite:///{tmp_path / 'local.db'}",
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)

    engine = database._engine()

    assert engine.url.get_backend_name() == "sqlite"
    engine.dispose()


def test_sqlite_is_rejected_outside_local_mode(tmp_path, monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url=f"sqlite:///{tmp_path / 'production.db'}",
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="Production requires a PostgreSQL"):
        database._engine()
