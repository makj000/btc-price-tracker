from __future__ import annotations

from datetime import datetime, timezone

import requests


class CoinMarketCapError(RuntimeError):
    pass


def fetch_btc_quote(*, api_key: str, base_url: str, timeout: int = 15) -> dict[str, str | float]:
    if not api_key:
        raise CoinMarketCapError("CMC_API_KEY is not configured.")

    response = requests.get(
        f"{base_url}/v1/cryptocurrency/quotes/latest",
        headers={"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"},
        params={"symbol": "BTC", "convert": "USD"},
        timeout=timeout,
    )
    response.raise_for_status()

    payload = response.json()
    btc_data = payload["data"]["BTC"]
    quote = btc_data["quote"]["USD"]
    fetched_at = payload.get("status", {}).get("timestamp") or datetime.now(timezone.utc).isoformat()

    return {
        "price_usd": float(quote["price"]),
        "fetched_at": fetched_at,
    }
