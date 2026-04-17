from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    cmc_api_key: str
    cmc_base_url: str
    database_path: Path
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from: str
    default_alert_to: str
    flask_host: str
    flask_port: int


def load_config() -> AppConfig:
    load_dotenv(BASE_DIR / ".env")

    database_path = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "app.db")))
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path

    return AppConfig(
        cmc_api_key=os.getenv("CMC_API_KEY", "").strip(),
        cmc_base_url=os.getenv("CMC_BASE_URL", "https://pro-api.coinmarketcap.com").rstrip("/"),
        database_path=database_path,
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
        twilio_from=os.getenv("TWILIO_FROM", "").strip(),
        default_alert_to=os.getenv("DEFAULT_ALERT_TO", "").strip(),
        flask_host=os.getenv("FLASK_HOST", "127.0.0.1"),
        flask_port=int(os.getenv("FLASK_PORT", "8000")),
    )
