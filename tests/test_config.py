"""Config loading tests."""

from __future__ import annotations

from config import Config


def test_config_defaults() -> None:
    """Config should load with sensible defaults when no env vars are set."""
    cfg = Config()
    assert cfg.flask_port == 5000
    assert cfg.webhook_port == 5001
    assert cfg.serial_prefix == "BIKE"
    assert cfg.starting_serial == 1
    assert cfg.gemini_model == "gemini-2.0-flash"
    assert cfg.shopify_api_version == "2025-10"
    assert "ebike_inventory.db" in cfg.database_path


def test_config_from_env(monkeypatch: object) -> None:
    """Config.from_env() reads from environment variables."""
    import os

    os.environ["FLASK_PORT"] = "9000"
    os.environ["SERIAL_PREFIX"] = "EBIKE"
    try:
        cfg = Config.from_env()
        assert cfg.flask_port == 9000
        assert cfg.serial_prefix == "EBIKE"
    finally:
        del os.environ["FLASK_PORT"]
        del os.environ["SERIAL_PREFIX"]
