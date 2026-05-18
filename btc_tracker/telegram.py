from __future__ import annotations

from typing import Any

import requests

from btc_tracker.config import AppConfig


class TelegramDeliveryError(RuntimeError):
    pass


def send_telegram(config: AppConfig, *, text: str, timeout: int = 15) -> dict[str, Any]:
    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise TelegramDeliveryError("Telegram credentials are incomplete.")

    response = requests.post(
        f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
        json={"chat_id": config.telegram_chat_id, "text": text},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
