from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request

from btc_tracker.config import load_config
from btc_tracker.db import (
    get_alert_events,
    get_latest_price_sample,
    get_price_history,
    get_settings,
    init_db,
    save_settings,
)
from btc_tracker.poller import run_poll_cycle


config = load_config()
app = Flask(__name__)
init_db(config.database_path)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    latest_price = get_latest_price_sample(config.database_path)
    settings = get_settings(config.database_path)
    return jsonify(
        {
            "latest_price": latest_price,
            "next_check_at": _next_check_at(latest_price, settings["poll_frequency_minutes"]),
            "settings": settings,
        }
    )


@app.get("/api/history")
def api_history():
    requested_limit = request.args.get("limit", default=288, type=int)
    limit = max(1, min(requested_limit, 5000))
    return jsonify({"history": get_price_history(config.database_path, limit=limit)})


@app.get("/api/alerts")
def api_alerts():
    requested_limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(requested_limit, 200))
    return jsonify({"alerts": get_alert_events(config.database_path, limit=limit)})


@app.get("/api/settings")
def api_settings():
    return jsonify(get_settings(config.database_path))


@app.post("/api/settings")
def api_save_settings():
    payload = request.get_json(force=True, silent=False) or {}

    try:
        values = {
            "high_threshold": _number_or_none(payload.get("high_threshold")),
            "low_threshold": _number_or_none(payload.get("low_threshold")),
            "alert_phone": (payload.get("alert_phone") or "").strip() or None,
            "sms_enabled": bool(payload.get("sms_enabled", True)),
            "poll_frequency_minutes": _parse_minutes(
                payload.get("poll_frequency_minutes", 5),
                minimum=5,
                field_name="poll_frequency_minutes",
            ),
            "alert_cooldown_minutes": _parse_minutes(
                payload.get("alert_cooldown_minutes", 60),
                minimum=1,
                field_name="alert_cooldown_minutes",
            ),
        }
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    existing = get_settings(config.database_path)
    if values["high_threshold"] != existing["high_threshold"]:
        values["high_alert_active"] = False
    if values["low_threshold"] != existing["low_threshold"]:
        values["low_alert_active"] = False

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
    return minutes


def _next_check_at(latest_price, frequency_minutes: int):
    if not latest_price:
        return None
    fetched_at = latest_price["fetched_at"].replace("Z", "+00:00")
    parsed = datetime.fromisoformat(fetched_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return (parsed + timedelta(minutes=frequency_minutes)).isoformat()


if __name__ == "__main__":
    app.run(host=config.flask_host, port=config.flask_port, debug=True)
