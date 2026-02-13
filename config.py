"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, model_validator

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Centralised app configuration backed by env vars."""

    # Shopify
    shopify_store_url: str = ""
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    shopify_access_token: str = ""  # legacy static token or auto-managed
    shopify_api_version: str = "2025-10"
    shopify_webhook_secret: str = ""

    # Gemini AI
    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # App paths
    database_path: str = str(_PROJECT_ROOT / "data" / "ebike_inventory.db")
    invoice_upload_dir: str = str(_PROJECT_ROOT / "data" / "invoices")
    label_output_dir: str = str(_PROJECT_ROOT / "data" / "labels")
    starting_serial: int = 1
    serial_prefix: str = "BIKE"

    # Flask
    flask_host: str = "127.0.0.1"
    flask_port: int = 5000
    flask_debug: bool = True
    flask_secret_key: str = "change-me-in-production"  # noqa: S105
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_size_mb: int = 20

    # Webhook server
    webhook_host: str = "0.0.0.0"  # noqa: S104
    webhook_port: int = 5001

    @model_validator(mode="after")
    def _warn_empty_critical_fields(self) -> Config:
        """Log warnings when critical integration fields are empty."""
        if not self.shopify_store_url:
            logger.warning("SHOPIFY_STORE_URL is not set — Shopify sync will fail")
        if not self.google_api_key:
            logger.warning("GOOGLE_API_KEY is not set — invoice parsing will fail")
        return self

    @classmethod
    def from_env(cls) -> Config:
        """Build config from environment variables."""
        cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
        cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]

        return cls(
            shopify_store_url=os.getenv("SHOPIFY_STORE_URL", ""),
            shopify_client_id=os.getenv("SHOPIFY_CLIENT_ID", ""),
            shopify_client_secret=os.getenv("SHOPIFY_CLIENT_SECRET", ""),
            shopify_access_token=os.getenv("SHOPIFY_ACCESS_TOKEN", ""),
            shopify_api_version=os.getenv("SHOPIFY_API_VERSION", "2025-10"),
            shopify_webhook_secret=os.getenv("SHOPIFY_WEBHOOK_SECRET", ""),
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            database_path=os.getenv(
                "DATABASE_PATH", str(_PROJECT_ROOT / "data" / "ebike_inventory.db")
            ),
            invoice_upload_dir=os.getenv(
                "INVOICE_UPLOAD_DIR", str(_PROJECT_ROOT / "data" / "invoices")
            ),
            label_output_dir=os.getenv("LABEL_OUTPUT_DIR", str(_PROJECT_ROOT / "data" / "labels")),
            starting_serial=int(os.getenv("STARTING_SERIAL", "1")),
            serial_prefix=os.getenv("SERIAL_PREFIX", "BIKE"),
            flask_host=os.getenv("FLASK_HOST", "127.0.0.1"),
            flask_port=int(os.getenv("FLASK_PORT", "5000")),
            flask_debug=os.getenv("FLASK_DEBUG", "true").lower() in ("1", "true", "yes"),
            flask_secret_key=os.getenv("FLASK_SECRET_KEY", "change-me-in-production"),
            cors_origins=cors_origins,
            max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "20")),
            webhook_host=os.getenv("WEBHOOK_HOST", "0.0.0.0"),  # noqa: S104
            webhook_port=int(os.getenv("WEBHOOK_PORT", "5001")),
        )


settings = Config.from_env()
