from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS = {
    "high_threshold": "",
    "low_threshold": "",
    "alert_phone": "",
    "sms_enabled": "1",
    "poll_frequency_minutes": "5",
    "alert_cooldown_minutes": "60",
    "high_alert_active": "0",
    "low_alert_active": "0",
    "last_high_alert_at": "",
    "last_low_alert_at": "",
}


def _ensure_parent_dir(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect(database_path: Path):
    _ensure_parent_dir(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS price_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                price_usd REAL NOT NULL,
                fetched_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'coinmarketcap'
            );

            CREATE TABLE IF NOT EXISTS alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                threshold_value REAL,
                price_usd REAL NOT NULL,
                triggered_at TEXT NOT NULL,
                sms_status TEXT NOT NULL,
                sms_message TEXT NOT NULL
            );
            """
        )
        _migrate_alert_events_schema(connection)

        for key, value in DEFAULT_SETTINGS.items():
            connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def get_settings(database_path: Path) -> dict[str, Any]:
    with connect(database_path) as connection:
        rows = connection.execute("SELECT key, value FROM settings").fetchall()

    values = {row["key"]: row["value"] for row in rows}
    merged = {**DEFAULT_SETTINGS, **values}
    return {
        "high_threshold": _to_float_or_none(merged["high_threshold"]),
        "low_threshold": _to_float_or_none(merged["low_threshold"]),
        "alert_phone": merged["alert_phone"] or None,
        "sms_enabled": merged["sms_enabled"] == "1",
        "poll_frequency_minutes": int(merged["poll_frequency_minutes"]),
        "alert_cooldown_minutes": int(merged["alert_cooldown_minutes"]),
        "high_alert_active": merged["high_alert_active"] == "1",
        "low_alert_active": merged["low_alert_active"] == "1",
        "last_high_alert_at": merged["last_high_alert_at"] or None,
        "last_low_alert_at": merged["last_low_alert_at"] or None,
    }


def save_settings(database_path: Path, values: dict[str, Any]) -> dict[str, Any]:
    serialized = {
        key: _serialize_setting_value(key, value)
        for key, value in values.items()
        if key in DEFAULT_SETTINGS
    }
    with connect(database_path) as connection:
        for key, value in serialized.items():
            connection.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    return get_settings(database_path)


def add_price_sample(database_path: Path, price_usd: float, fetched_at: str, source: str = "coinmarketcap") -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO price_samples (price_usd, fetched_at, source)
            VALUES (?, ?, ?)
            """,
            (price_usd, fetched_at, source),
        )


def get_latest_price_sample(database_path: Path) -> dict[str, Any] | None:
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT id, price_usd, fetched_at, source
            FROM price_samples
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None
    return dict(row)


def get_price_history(database_path: Path, limit: int = 288) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, price_usd, fetched_at, source
            FROM price_samples
            ORDER BY fetched_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    history = [dict(row) for row in rows]
    history.reverse()
    return history


def add_alert_event(
    database_path: Path,
    *,
    alert_type: str,
    threshold_value: float | None,
    price_usd: float,
    triggered_at: str,
    sms_status: str,
    sms_message: str,
) -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO alert_events (
                alert_type,
                threshold_value,
                price_usd,
                triggered_at,
                sms_status,
                sms_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert_type,
                threshold_value,
                price_usd,
                triggered_at,
                sms_status,
                sms_message,
            ),
        )


def get_alert_events(database_path: Path, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, alert_type, threshold_value, price_usd, triggered_at, sms_status, sms_message
            FROM alert_events
            ORDER BY triggered_at DESC, id DESC
            LIMIT ?
            OFFSET ?
            """,
            (limit, max(0, offset)),
        ).fetchall()

    return [dict(row) for row in rows]


def _migrate_alert_events_schema(connection: sqlite3.Connection) -> None:
    columns = connection.execute("PRAGMA table_info(alert_events)").fetchall()
    threshold_column = next((column for column in columns if column["name"] == "threshold_value"), None)
    if threshold_column is None or threshold_column["notnull"] == 0:
        return

    connection.executescript(
        """
        ALTER TABLE alert_events RENAME TO alert_events_old;

        CREATE TABLE alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT NOT NULL,
            threshold_value REAL,
            price_usd REAL NOT NULL,
            triggered_at TEXT NOT NULL,
            sms_status TEXT NOT NULL,
            sms_message TEXT NOT NULL
        );

        INSERT INTO alert_events (
            id,
            alert_type,
            threshold_value,
            price_usd,
            triggered_at,
            sms_status,
            sms_message
        )
        SELECT
            id,
            alert_type,
            threshold_value,
            price_usd,
            triggered_at,
            sms_status,
            sms_message
        FROM alert_events_old;

        DROP TABLE alert_events_old;
        """
    )


def _serialize_setting_value(key: str, value: Any) -> str:
    if key in {"sms_enabled", "high_alert_active", "low_alert_active"}:
        return "1" if bool(value) else "0"
    if value is None:
        return ""
    return str(value)


def _to_float_or_none(value: str) -> float | None:
    if not value:
        return None
    return float(value)
