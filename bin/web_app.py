from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

from btc_tracker import __version__
from btc_tracker.config import load_config
from btc_tracker.db import (
    get_alert_events,
    get_latest_price_sample,
    get_price_history,
    get_settings,
    init_db,
    save_settings,
)
from btc_tracker.poller import SYMBOLS
from btc_tracker.poller import run_poll_cycle
from btc_tracker.schedule import (
    VALID_POLL_FREQUENCY_ERROR,
    is_valid_poll_frequency,
    next_scheduled_check_at,
)


config = load_config()
app = Flask(__name__, template_folder='../templates', static_folder='../static')
init_db(config.database_path)


@app.get("/")
def index():
    return render_template("index.html", app_version=__version__)


@app.get("/api/status")
def api_status():
    settings = get_settings(config.database_path)
    latest_prices = {s: get_latest_price_sample(config.database_path, symbol=s) for s in SYMBOLS}
    btc_latest = latest_prices.get("BTC")
    return jsonify(
        {
            "latest_price": btc_latest,
            "latest_prices": latest_prices,
            "next_check_at": _next_check_at(btc_latest, settings["poll_frequency_minutes"]),
            "settings": settings,
            "version": __version__,
        }
    )


@app.get("/api/history")
def api_history():
    requested_limit = request.args.get("limit", default=288, type=int)
    symbol = request.args.get("symbol", default="BTC").upper()
    if symbol not in SYMBOLS:
        return jsonify({"error": f"Unknown symbol. Valid: {', '.join(SYMBOLS)}"}), 400
    limit = max(1, min(requested_limit, 5000))
    return jsonify({"history": get_price_history(config.database_path, limit=limit, symbol=symbol)})


@app.get("/api/alerts")
def api_alerts():
    requested_limit = request.args.get("limit", default=50, type=int)
    requested_offset = request.args.get("offset", default=0, type=int)
    symbol = request.args.get("symbol", default=None)
    if symbol is not None:
        symbol = symbol.upper()
        if symbol not in SYMBOLS:
            return jsonify({"error": f"Unknown symbol. Valid: {', '.join(SYMBOLS)}"}), 400
    limit = max(1, min(requested_limit, 200))
    offset = max(0, requested_offset)
    return jsonify({"alerts": get_alert_events(config.database_path, limit=limit, offset=offset, symbol=symbol)})


@app.get("/api/settings")
def api_settings():
    return jsonify(get_settings(config.database_path))


@app.post("/api/settings")
def api_save_settings():
    payload = request.get_json(force=True, silent=False) or {}
    existing = get_settings(config.database_path)

    try:
        values = {
            "high_threshold": _number_or_none(payload.get("high_threshold", existing["high_threshold"])),
            "low_threshold": _number_or_none(payload.get("low_threshold", existing["low_threshold"])),
            "feth_high_threshold": _number_or_none(payload.get("feth_high_threshold", existing["feth_high_threshold"])),
            "feth_low_threshold": _number_or_none(payload.get("feth_low_threshold", existing["feth_low_threshold"])),
            "alert_phone": (payload.get("alert_phone", existing["alert_phone"]) or "").strip() or None,
            "sms_enabled": bool(payload.get("sms_enabled", existing["sms_enabled"])),
            "poll_frequency_minutes": _parse_minutes(
                payload.get("poll_frequency_minutes", existing["poll_frequency_minutes"]),
                minimum=5,
                field_name="poll_frequency_minutes",
            ),
            "alert_cooldown_minutes": _parse_minutes(
                payload.get("alert_cooldown_minutes", existing["alert_cooldown_minutes"]),
                minimum=1,
                field_name="alert_cooldown_minutes",
            ),
        }
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if values["high_threshold"] != existing["high_threshold"]:
        values["high_alert_active"] = False
    if values["low_threshold"] != existing["low_threshold"]:
        values["low_alert_active"] = False
    if values["feth_high_threshold"] != existing["feth_high_threshold"]:
        values["feth_high_alert_active"] = False
    if values["feth_low_threshold"] != existing["feth_low_threshold"]:
        values["feth_low_alert_active"] = False

    saved = save_settings(config.database_path, values)
    return jsonify(saved)


@app.post("/api/poll")
def api_poll():
    try:
        result = run_poll_cycle(config)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _number_or_none(value):
    if value in ("", None):
        return None
    return float(value)


def _parse_minutes(value, *, minimum: int, field_name: str) -> int:
    minutes = int(value)
    if minutes < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}.")
    if field_name == "poll_frequency_minutes" and not is_valid_poll_frequency(minutes):
        raise ValueError(VALID_POLL_FREQUENCY_ERROR)
    return minutes


def _next_check_at(latest_price, frequency_minutes: int):
    reference = datetime.now(timezone.utc)
    if latest_price:
        fetched_at = latest_price["fetched_at"].replace("Z", "+00:00")
        parsed = datetime.fromisoformat(fetched_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        if parsed > reference:
            reference = parsed
    return next_scheduled_check_at(reference, frequency_minutes).isoformat()


if __name__ == "__main__":
    app.run(host=config.flask_host, port=config.flask_port, debug=False)
