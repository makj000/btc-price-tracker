from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone


class YahooFinanceError(RuntimeError):
    pass


def fetch_quote(symbol: str, *, timeout: int = 15) -> dict[str, str | float]:
    # Use 5-day range so the most recent close is always available (handles weekends/holidays).
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        raise YahooFinanceError(f"Failed to fetch {symbol} quote: {exc}") from exc

    try:
        result = data["chart"]["result"][0]
        closes = [p for p in result["indicators"]["quote"][0]["close"] if p is not None]
        price = float(closes[-1])
    except (KeyError, IndexError, TypeError) as exc:
        raise YahooFinanceError(f"Unexpected Yahoo Finance response for {symbol}: {exc}") from exc

    return {
        "price_usd": price,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_fbtc_quote(*, timeout: int = 15) -> dict[str, str | float]:
    return fetch_quote("FBTC", timeout=timeout)


def fetch_feth_quote(*, timeout: int = 15) -> dict[str, str | float]:
    return fetch_quote("FETH", timeout=timeout)
