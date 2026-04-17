from __future__ import annotations

from typing import Any

import requests

from btc_tracker.config import AppConfig


class SmsDeliveryError(RuntimeError):
    pass


def send_sms(config: AppConfig, *, to_number: str, body: str, timeout: int = 15) -> dict[str, Any]:
    if not config.twilio_account_sid or not config.twilio_auth_token or not config.twilio_from:
        raise SmsDeliveryError("Twilio credentials are incomplete.")

    response = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{config.twilio_account_sid}/Messages.json",
        auth=(config.twilio_account_sid, config.twilio_auth_token),
        data={
            "From": config.twilio_from,
            "To": to_number,
            "Body": body,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
