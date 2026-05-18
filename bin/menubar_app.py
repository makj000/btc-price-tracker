from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import rumps
from AppKit import NSAttributedString, NSColor, NSForegroundColorAttributeName

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from btc_tracker.config import load_config
from btc_tracker.db import get_latest_price_sample, get_settings, init_db, save_settings, seed_thresholds
from btc_tracker.poller import run_poll_cycle
from btc_tracker.schedule import next_scheduled_check_at


class BTCMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("BTC", quit_button="Quit")
        self.config = load_config()
        init_db(self.config.database_path)
        seed_thresholds(self.config.database_path, self.config.seed_high_threshold, self.config.seed_low_threshold)
        self._last_poll_time = 0.0

        self._price_item = rumps.MenuItem("BTC: —")
        self._high_item = rumps.MenuItem("↑ High: not set")
        self._low_item = rumps.MenuItem("↓ Low: not set")

        self.menu = [
            self._price_item,
            None,
            self._high_item,
            self._low_item,
            None,
            rumps.MenuItem("Set High Threshold…", callback=self._set_high_threshold),
            rumps.MenuItem("Set Low Threshold…", callback=self._set_low_threshold),
            rumps.MenuItem("Clear High Threshold", callback=self._clear_high_threshold),
            rumps.MenuItem("Clear Low Threshold", callback=self._clear_low_threshold),
            None,
            rumps.MenuItem("Run Check Now", callback=self._run_check_now),
        ]

        self._timer = rumps.Timer(self._heartbeat, 30)
        self._timer.start()
        self._startup_timer = rumps.Timer(self._startup_poll, 1)
        self._startup_timer.start()

    def _set_title(self, text: str, status: str = "normal") -> None:
        if not hasattr(self, "_nsapp") or not hasattr(self._nsapp, "nsstatusitem"):
            return
        if status == "high":
            color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.45, 0.0, 1.0)
        elif status == "low":
            color = NSColor.redColor()
        else:
            color = NSColor.labelColor()
        attrs = {NSForegroundColorAttributeName: color}
        attributed = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        self._nsapp.nsstatusitem.button().setAttributedTitle_(attributed)

    def _update_menu_items(self, price: float | None, settings: dict) -> None:
        high = settings.get("high_threshold")
        low = settings.get("low_threshold")
        self._price_item.title = f"BTC: ${price:,.0f}" if price is not None else "BTC: —"
        self._high_item.title = f"↑ High: ${high:,.0f}" if high is not None else "↑ High: not set"
        self._low_item.title = f"↓ Low: ${low:,.0f}" if low is not None else "↓ Low: not set"

    def _startup_poll(self, timer: rumps.Timer) -> None:
        timer.stop()
        self._do_poll()

    def _heartbeat(self, _) -> None:
        settings = get_settings(self.config.database_path)
        latest = get_latest_price_sample(self.config.database_path)
        if latest is None:
            self._do_poll()
            return
        fetched_at = self._parse_timestamp(latest["fetched_at"])
        next_check_at = next_scheduled_check_at(fetched_at, settings["poll_frequency_minutes"])
        if datetime.now(timezone.utc) >= next_check_at and time.time() - self._last_poll_time >= 30:
            self._do_poll()

    def _do_poll(self) -> None:
        try:
            result = run_poll_cycle(self.config)
        except Exception:
            self._set_title("--")
            return

        price = result["price_usd"]
        settings = result["settings"]
        high = settings["high_threshold"]
        low = settings["low_threshold"]

        if low is not None and price <= low:
            status = "low"
        elif high is not None and price >= high:
            status = "high"
        else:
            status = "normal"

        self._set_title(f"${price / 1000:.0f}k", status=status)
        self._update_menu_items(price, settings)

        for event in result["alerts"]:
            if event["alert_type"] in ("HIGH", "LOW"):
                direction = "above" if event["alert_type"] == "HIGH" else "below"
                rumps.notification(
                    title="BTC Price Alert",
                    subtitle=f"${price:,.0f} — {direction} ${event['threshold_value']:,.0f}",
                    message=event["sms_message"],
                )
                break

        self._last_poll_time = time.time()

    def _set_high_threshold(self, _) -> None:
        current = get_settings(self.config.database_path)["high_threshold"]
        window = rumps.Window(
            title="Set High Threshold",
            message="Alert when BTC rises above this price (USD).\nLeave blank to clear.",
            default_text=f"{current:.0f}" if current is not None else "",
            ok="Save",
            cancel="Cancel",
            dimensions=(220, 22),
        )
        response = window.run()
        if response.clicked:
            raw = response.text.strip()
            value = float(raw) if raw else None
            save_settings(self.config.database_path, {"high_threshold": value, "high_alert_active": False})
            self._refresh_display()

    def _set_low_threshold(self, _) -> None:
        current = get_settings(self.config.database_path)["low_threshold"]
        window = rumps.Window(
            title="Set Low Threshold",
            message="Alert when BTC falls below this price (USD).\nLeave blank to clear.",
            default_text=f"{current:.0f}" if current is not None else "",
            ok="Save",
            cancel="Cancel",
            dimensions=(220, 22),
        )
        response = window.run()
        if response.clicked:
            raw = response.text.strip()
            value = float(raw) if raw else None
            save_settings(self.config.database_path, {"low_threshold": value, "low_alert_active": False})
            self._refresh_display()

    def _clear_high_threshold(self, _) -> None:
        save_settings(self.config.database_path, {"high_threshold": None, "high_alert_active": False})
        self._refresh_display()

    def _clear_low_threshold(self, _) -> None:
        save_settings(self.config.database_path, {"low_threshold": None, "low_alert_active": False})
        self._refresh_display()

    def _refresh_display(self) -> None:
        settings = get_settings(self.config.database_path)
        latest = get_latest_price_sample(self.config.database_path)
        price = latest["price_usd"] if latest else None
        self._update_menu_items(price, settings)

    def _run_check_now(self, _) -> None:
        self._do_poll()

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    BTCMenuBarApp().run()
