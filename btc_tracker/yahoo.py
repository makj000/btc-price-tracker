from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone


class YahooFinanceError(RuntimeError):
    pass


YAHOO_SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}


def fetch_quote(symbol: str, *, timeout: int = 15) -> dict[str, str | float]:
    yahoo_symbol = YAHOO_SYMBOLS.get(symbol.upper(), symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?range=1d&interval=1m"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        raise YahooFinanceError(f"Failed to fetch {symbol} quote: {exc}") from exc

    try:
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        timestamp, price = next(
            (timestamp, float(price))
            for timestamp, price in reversed(list(zip(timestamps, closes)))
            if price is not None
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise YahooFinanceError(f"Unexpected Yahoo Finance response for {symbol}: {exc}") from exc
    except StopIteration as exc:
        raise YahooFinanceError(f"Yahoo Finance returned no price for {symbol}") from exc

    return {
        "price_usd": price,
        "fetched_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
    }


def fetch_btc_quote(*, timeout: int = 15) -> dict[str, str | float]:
    return fetch_quote("BTC", timeout=timeout)


def fetch_eth_quote(*, timeout: int = 15) -> dict[str, str | float]:
    return fetch_quote("ETH", timeout=timeout)
