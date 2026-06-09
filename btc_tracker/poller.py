from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from btc_tracker.config import AppConfig
from btc_tracker.db import add_alert_event, add_price_sample, get_settings, init_db, save_settings
from btc_tracker.schedule import next_scheduled_check_at
from btc_tracker.sms import SmsDeliveryError, send_sms
from btc_tracker.telegram import TelegramDeliveryError, send_telegram
from btc_tracker.yahoo import YahooFinanceError, fetch_quote

SYMBOLS = ["BTC", "ETH"]

# BTC reuses the primary settings keys; ETH retains the existing secondary keys.
_SETTINGS_PREFIX = {
    "BTC": "",
    "ETH": "feth_",
}


def run_poll_cycle(config: AppConfig) -> dict[str, Any]:
    init_db(config.database_path)
    settings = get_settings(config.database_path)

    now = datetime.now(timezone.utc)
    all_updates: dict[str, Any] = {}
    results: dict[str, Any] = {}

    for symbol in SYMBOLS:
        try:
            quote = fetch_quote(symbol)
        except YahooFinanceError as exc:
            results[symbol] = {"error": str(exc)}
            continue

        price_usd = float(quote["price_usd"])
        fetched_at = str(quote["fetched_at"])
        add_price_sample(config.database_path, price_usd=price_usd, fetched_at=fetched_at, symbol=symbol)

        ts_now = _parse_timestamp(fetched_at)
        prefix = _SETTINGS_PREFIX[symbol]
        sym_settings = {**settings, **all_updates}
        updates, alert_results = _check_thresholds(
            config=config,
            settings=sym_settings,
            now=ts_now,
            price_usd=price_usd,
            symbol=symbol,
            prefix=prefix,
        )
        all_updates.update(updates)
        settings = {**settings, **all_updates}

        if not alert_results and not _thresholds_reached(price_usd, sym_settings, prefix):
            noop = _record_noop_event(config=config, now=ts_now, price_usd=price_usd, symbol=symbol)
            alert_results.append(noop)

        results[symbol] = {
            "price_usd": price_usd,
            "fetched_at": fetched_at,
            "alerts": alert_results,
        }

    if all_updates:
        settings = save_settings(config.database_path, all_updates)

    btc = results.get("BTC", {})
    return {
        "price_usd": btc.get("price_usd"),
        "fetched_at": btc.get("fetched_at"),
        "next_check_at": next_scheduled_check_at(now, settings["poll_frequency_minutes"]).isoformat(),
        "alerts": btc.get("alerts", []),
        "settings": settings,
        "symbols": results,
    }


def _check_thresholds(
    *,
    config: AppConfig,
    settings: dict[str, Any],
    now: datetime,
    price_usd: float,
    symbol: str,
    prefix: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updates: dict[str, Any] = {}
    alert_results: list[dict[str, Any]] = []

    high_result = _handle_threshold(
        config=config,
        settings=settings,
        now=now,
        price_usd=price_usd,
        symbol=symbol,
        threshold=settings[f"{prefix}high_threshold"],
        active_key=f"{prefix}high_alert_active",
        last_key=f"{prefix}last_high_alert_at",
        alert_type="HIGH",
        comparison=lambda p, t: p >= t,
    )
    updates.update(high_result["settings_updates"])
    if high_result["alert_event"]:
        alert_results.append(high_result["alert_event"])

    settings = {**settings, **updates}

    low_result = _handle_threshold(
        config=config,
        settings=settings,
        now=now,
        price_usd=price_usd,
        symbol=symbol,
        threshold=settings[f"{prefix}low_threshold"],
        active_key=f"{prefix}low_alert_active",
        last_key=f"{prefix}last_low_alert_at",
        alert_type="LOW",
        comparison=lambda p, t: p <= t,
    )
    updates.update(low_result["settings_updates"])
    if low_result["alert_event"]:
        alert_results.append(low_result["alert_event"])

    return updates, alert_results


def _handle_threshold(
    *,
    config: AppConfig,
    settings: dict[str, Any],
    now: datetime,
    price_usd: float,
    symbol: str,
    threshold: float | None,
    active_key: str,
    last_key: str,
    alert_type: str,
    comparison,
) -> dict[str, Any]:
    settings_updates: dict[str, Any] = {}
    if threshold is None:
        if settings.get(active_key):
            settings_updates[active_key] = False
        return {"settings_updates": settings_updates, "alert_event": None}

    threshold_hit = comparison(price_usd, threshold)
    if not threshold_hit:
        if settings.get(active_key):
            settings_updates[active_key] = False
        return {"settings_updates": settings_updates, "alert_event": None}

    cooldown_ready = _cooldown_has_elapsed(now, settings.get(last_key), settings["alert_cooldown_minutes"])
    if settings.get(active_key):
        return {
            "settings_updates": settings_updates,
            "alert_event": _record_suppressed_event(
                config=config, now=now, price_usd=price_usd,
                threshold=threshold, alert_type=alert_type,
                reason="threshold already active", symbol=symbol,
            ),
        }
    if not cooldown_ready:
        return {
            "settings_updates": settings_updates,
            "alert_event": _record_suppressed_event(
                config=config, now=now, price_usd=price_usd,
                threshold=threshold, alert_type=alert_type,
                reason="cooldown not elapsed", symbol=symbol,
            ),
        }

    direction = "above" if alert_type == "HIGH" else "below"
    message = (
        f"{symbol} price alert: {symbol} is ${price_usd:,.2f}, "
        f"{direction} your ${threshold:,.2f} threshold."
    )
    sms_status = "skipped"
    recipient = settings.get("alert_phone") or config.default_alert_to

    if settings.get("sms_enabled") and recipient:
        try:
            send_sms(config, to_number=recipient, body=message)
            sms_status = "sent"
        except SmsDeliveryError as exc:
            sms_status = f"failed: {exc}"
        except Exception as exc:
            sms_status = f"failed: {exc}"
    elif settings.get("sms_enabled") and not recipient:
        sms_status = "skipped: no recipient configured"

    telegram_status = "skipped"
    if config.telegram_bot_token and config.telegram_chat_id:
        try:
            send_telegram(config, text=message)
            telegram_status = "sent"
        except TelegramDeliveryError as exc:
            telegram_status = f"failed: {exc}"
        except Exception as exc:
            telegram_status = f"failed: {exc}"

    timestamp = now.isoformat()
    add_alert_event(
        config.database_path,
        alert_type=alert_type,
        threshold_value=threshold,
        price_usd=price_usd,
        triggered_at=timestamp,
        sms_status=sms_status,
        sms_message=message,
        telegram_status=telegram_status,
        symbol=symbol,
    )

    settings_updates[active_key] = True
    settings_updates[last_key] = timestamp
    return {
        "settings_updates": settings_updates,
        "alert_event": {
            "alert_type": alert_type,
            "threshold_value": threshold,
            "price_usd": price_usd,
            "triggered_at": timestamp,
            "sms_status": sms_status,
            "sms_message": message,
            "telegram_status": telegram_status,
            "symbol": symbol,
        },
    }


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cooldown_has_elapsed(now: datetime, last_sent_at: str | None, cooldown_minutes: int) -> bool:
    if not last_sent_at:
        return True
    previous = _parse_timestamp(last_sent_at)
    return now >= previous + timedelta(minutes=cooldown_minutes)


def _thresholds_reached(price_usd: float, settings: dict[str, Any], prefix: str) -> bool:
    high = settings.get(f"{prefix}high_threshold")
    low = settings.get(f"{prefix}low_threshold")
    return (high is not None and price_usd >= high) or (low is not None and price_usd <= low)


def _record_noop_event(*, config: AppConfig, now: datetime, price_usd: float, symbol: str) -> dict[str, Any]:
    timestamp = now.isoformat()
    message = "No thresholds were reached on this check."
    event = {
        "alert_type": "NOOP",
        "threshold_value": None,
        "price_usd": price_usd,
        "triggered_at": timestamp,
        "sms_status": "not_applicable",
        "sms_message": message,
        "symbol": symbol,
    }
    add_alert_event(config.database_path, **event)
    return event


def _record_suppressed_event(
    *,
    config: AppConfig,
    now: datetime,
    price_usd: float,
    threshold: float,
    alert_type: str,
    reason: str,
    symbol: str,
) -> dict[str, Any]:
    direction = "above" if alert_type == "HIGH" else "below"
    timestamp = now.isoformat()
    message = (
        f"{symbol} is ${price_usd:,.2f}, {direction} your ${threshold:,.2f} threshold, "
        f"but no new alert was sent because {reason}."
    )
    event = {
        "alert_type": "SUPPRESSED",
        "threshold_value": threshold,
        "price_usd": price_usd,
        "triggered_at": timestamp,
        "sms_status": f"suppressed: {reason}",
        "sms_message": message,
        "symbol": symbol,
    }
    add_alert_event(config.database_path, **event)
    return event
