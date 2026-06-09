from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from btc_tracker.schedule import coerce_poll_frequency


DEFAULT_SETTINGS = {
    "high_threshold": "",
    "low_threshold": "",
    "alert_phone": "",
    "sms_enabled": "1",
    "poll_frequency_minutes": "10",
    "alert_cooldown_minutes": "60",
    "high_alert_active": "0",
    "low_alert_active": "0",
    "last_high_alert_at": "",
    "last_low_alert_at": "",
    # ETH
    "feth_high_threshold": "",
    "feth_low_threshold": "",
    "feth_high_alert_active": "0",
    "feth_low_alert_active": "0",
    "feth_last_high_alert_at": "",
    "feth_last_low_alert_at": "",
    "tracked_pair": "BTC_ETH",
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
        _migrate_telegram_status_column(connection)
        _migrate_symbol_columns(connection)
        _migrate_tracked_pair_settings(connection)

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
    poll_frequency_minutes = coerce_poll_frequency(int(merged["poll_frequency_minutes"]))
    return {
        "high_threshold": _to_float_or_none(merged["high_threshold"]),
        "low_threshold": _to_float_or_none(merged["low_threshold"]),
        "alert_phone": merged["alert_phone"] or None,
        "sms_enabled": merged["sms_enabled"] == "1",
        "poll_frequency_minutes": poll_frequency_minutes,
        "alert_cooldown_minutes": int(merged["alert_cooldown_minutes"]),
        "high_alert_active": merged["high_alert_active"] == "1",
        "low_alert_active": merged["low_alert_active"] == "1",
        "last_high_alert_at": merged["last_high_alert_at"] or None,
        "last_low_alert_at": merged["last_low_alert_at"] or None,
        "feth_high_threshold": _to_float_or_none(merged["feth_high_threshold"]),
        "feth_low_threshold": _to_float_or_none(merged["feth_low_threshold"]),
        "feth_high_alert_active": merged["feth_high_alert_active"] == "1",
        "feth_low_alert_active": merged["feth_low_alert_active"] == "1",
        "feth_last_high_alert_at": merged["feth_last_high_alert_at"] or None,
        "feth_last_low_alert_at": merged["feth_last_low_alert_at"] or None,
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


def seed_thresholds(database_path: Path, high: float | None, low: float | None) -> None:
    if high is None and low is None:
        return
    settings = get_settings(database_path)
    updates = {}
    if high is not None and settings["high_threshold"] is None:
        updates["high_threshold"] = high
    if low is not None and settings["low_threshold"] is None:
        updates["low_threshold"] = low
    if updates:
        save_settings(database_path, updates)


def add_price_sample(
    database_path: Path,
    price_usd: float,
    fetched_at: str,
    source: str = "yahoo",
    symbol: str = "BTC",
) -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO price_samples (price_usd, fetched_at, source, symbol)
            VALUES (?, ?, ?, ?)
            """,
            (price_usd, fetched_at, source, symbol.upper()),
        )


def get_latest_price_sample(
    database_path: Path,
    symbol: str = "BTC",
) -> dict[str, Any] | None:
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT id, price_usd, fetched_at, source, symbol
            FROM price_samples
            WHERE symbol = ?
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()

    if row is None:
        return None
    return dict(row)


def get_price_history(
    database_path: Path,
    limit: int = 288,
    symbol: str = "BTC",
) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, price_usd, fetched_at, source, symbol
            FROM price_samples
            WHERE symbol = ?
            ORDER BY fetched_at DESC, id DESC
            LIMIT ?
            """,
            (symbol.upper(), limit),
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
    telegram_status: str = "skipped",
    symbol: str = "BTC",
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
                sms_message,
                telegram_status,
                symbol
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_type,
                threshold_value,
                price_usd,
                triggered_at,
                sms_status,
                sms_message,
                telegram_status,
                symbol.upper(),
            ),
        )


def get_alert_events(
    database_path: Path,
    limit: int = 50,
    offset: int = 0,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    with connect(database_path) as connection:
        if symbol is not None:
            rows = connection.execute(
                """
                SELECT id, alert_type, threshold_value, price_usd, triggered_at,
                       sms_status, sms_message, telegram_status, symbol
                FROM alert_events
                WHERE symbol = ?
                ORDER BY triggered_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (symbol.upper(), limit, max(0, offset)),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, alert_type, threshold_value, price_usd, triggered_at,
                       sms_status, sms_message, telegram_status, symbol
                FROM alert_events
                ORDER BY triggered_at DESC, id DESC
                LIMIT ? OFFSET ?
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


def _migrate_telegram_status_column(connection: sqlite3.Connection) -> None:
    columns = connection.execute("PRAGMA table_info(alert_events)").fetchall()
    column_names = [c["name"] for c in columns]
    if "telegram_status" not in column_names:
        connection.execute(
            "ALTER TABLE alert_events ADD COLUMN telegram_status TEXT NOT NULL DEFAULT 'skipped'"
        )


def _migrate_symbol_columns(connection: sqlite3.Connection) -> None:
    ps_cols = [c["name"] for c in connection.execute("PRAGMA table_info(price_samples)").fetchall()]
    if "symbol" not in ps_cols:
        connection.execute("ALTER TABLE price_samples ADD COLUMN symbol TEXT NOT NULL DEFAULT 'FBTC'")

    ae_cols = [c["name"] for c in connection.execute("PRAGMA table_info(alert_events)").fetchall()]
    if "symbol" not in ae_cols:
        connection.execute("ALTER TABLE alert_events ADD COLUMN symbol TEXT NOT NULL DEFAULT 'FBTC'")


def _migrate_tracked_pair_settings(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT value FROM settings WHERE key = 'tracked_pair'"
    ).fetchone()
    if row is not None and row["value"] == "BTC_ETH":
        return

    reset_values = {
        "high_threshold": "",
        "low_threshold": "",
        "high_alert_active": "0",
        "low_alert_active": "0",
        "last_high_alert_at": "",
        "last_low_alert_at": "",
        "feth_high_threshold": "",
        "feth_low_threshold": "",
        "feth_high_alert_active": "0",
        "feth_low_alert_active": "0",
        "feth_last_high_alert_at": "",
        "feth_last_low_alert_at": "",
        "poll_frequency_minutes": "10",
        "tracked_pair": "BTC_ETH",
    }
    for key, value in reset_values.items():
        connection.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _serialize_setting_value(key: str, value: Any) -> str:
    if key in {"sms_enabled", "high_alert_active", "low_alert_active",
               "feth_high_alert_active", "feth_low_alert_active"}:
        return "1" if bool(value) else "0"
    if value is None:
        return ""
    return str(value)


def _to_float_or_none(value: str) -> float | None:
    if not value:
        return None
    return float(value)
