from __future__ import annotations

import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import rumps
from AppKit import (
    NSAttributedString,
    NSBaselineOffsetAttributeName,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMutableAttributedString,
    NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
    NSStatusBar,
    NSVariableStatusItemLength,
)
import objc
from Foundation import NSObject

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from btc_tracker.config import load_config
from btc_tracker.db import get_latest_price_sample, get_settings, init_db, save_settings, seed_thresholds
from btc_tracker.poller import run_poll_cycle
from btc_tracker.schedule import next_scheduled_check_at


class _RefreshTarget(NSObject):
    def initWithApp_(self, app):
        self = objc.super(_RefreshTarget, self).init()
        if self is None:
            return None
        self._app = app
        return self

    def refresh_(self, sender):
        self._app._do_poll()


class BTCMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("FBTC", quit_button="Quit")
        self.config = load_config()
        init_db(self.config.database_path)
        seed_thresholds(self.config.database_path, self.config.seed_high_threshold, self.config.seed_low_threshold)
        self._last_poll_time = 0.0

        self._fbtc_price_item = rumps.MenuItem("FBTC: —")
        self._fbtc_high_item  = rumps.MenuItem("  ↑ High: not set")
        self._fbtc_low_item   = rumps.MenuItem("  ↓ Low: not set")

        self._feth_price_item = rumps.MenuItem("FETH: —")
        self._feth_high_item  = rumps.MenuItem("  ↑ High: not set")
        self._feth_low_item   = rumps.MenuItem("  ↓ Low: not set")

        self.menu = [
            rumps.MenuItem("↻  Refresh Prices", callback=self._run_check_now),
            None,
            self._fbtc_price_item,
            self._fbtc_high_item,
            self._fbtc_low_item,
            None,
            self._feth_price_item,
            self._feth_high_item,
            self._feth_low_item,
            None,
            rumps.MenuItem("Set FBTC High…",  callback=self._set_fbtc_high),
            rumps.MenuItem("Set FBTC Low…",   callback=self._set_fbtc_low),
            rumps.MenuItem("Clear FBTC High", callback=self._clear_fbtc_high),
            rumps.MenuItem("Clear FBTC Low",  callback=self._clear_fbtc_low),
            None,
            rumps.MenuItem("Set FETH High…",  callback=self._set_feth_high),
            rumps.MenuItem("Set FETH Low…",   callback=self._set_feth_low),
            rumps.MenuItem("Clear FETH High", callback=self._clear_feth_high),
            rumps.MenuItem("Clear FETH Low",  callback=self._clear_feth_low),
            None,
            rumps.MenuItem("FBTC Chart ↗", callback=lambda _: webbrowser.open("https://finance.yahoo.com/chart/FBTC")),
            rumps.MenuItem("FETH Chart ↗", callback=lambda _: webbrowser.open("https://finance.yahoo.com/chart/FETH")),
        ]

        self._timer = rumps.Timer(self._heartbeat, 30)
        self._timer.start()
        self._startup_timer = rumps.Timer(self._startup_poll, 1)
        self._startup_timer.start()

        self._refresh_target = _RefreshTarget.alloc().initWithApp_(self)
        self._refresh_status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        btn = self._refresh_status_item.button()
        btn.setTitle_("↻")
        btn.setTarget_(self._refresh_target)
        btn.setAction_("refresh:")

    def _set_title(self, fbtc_line: str, fbtc_bar: str, feth_line: str, feth_bar: str, status: str = "normal") -> None:
        if not hasattr(self, "_nsapp") or not hasattr(self._nsapp, "nsstatusitem"):
            return

        if status == "high":
            fbtc_color = NSColor.systemGreenColor()
        elif status == "low":
            fbtc_color = NSColor.systemRedColor()
        else:
            fbtc_color = NSColor.systemOrangeColor()
        feth_color = NSColor.systemBlueColor()

        text_font = NSFont.monospacedSystemFontOfSize_weight_(8.0, 0.0)
        bar_font  = NSFont.monospacedSystemFontOfSize_weight_(5.0, 0.0)

        text_para = NSMutableParagraphStyle.alloc().init()
        text_para.setMinimumLineHeight_(8.5)
        text_para.setMaximumLineHeight_(8.5)
        text_para.setParagraphSpacing_(2.5)

        bar_para = NSMutableParagraphStyle.alloc().init()
        bar_para.setMinimumLineHeight_(2.0)
        bar_para.setMaximumLineHeight_(2.0)

        def _text_attrs(color):
            return {
                NSForegroundColorAttributeName: color,
                NSFontAttributeName: text_font,
                NSParagraphStyleAttributeName: text_para,
                NSBaselineOffsetAttributeName: -9.0,
            }

        def _bar_attrs(color):
            return {
                NSForegroundColorAttributeName: color,
                NSFontAttributeName: bar_font,
                NSParagraphStyleAttributeName: bar_para,
                NSBaselineOffsetAttributeName: -9.0,
            }

        def _seg(text, attrs):
            return NSAttributedString.alloc().initWithString_attributes_(text, attrs)

        full = NSMutableAttributedString.alloc().init()
        full.appendAttributedString_(_seg(f"{fbtc_line}\n", _text_attrs(fbtc_color)))
        full.appendAttributedString_(_seg(f"{fbtc_bar}\n", _bar_attrs(fbtc_color)))
        full.appendAttributedString_(_seg(f"{feth_line}\n", _text_attrs(feth_color)))
        full.appendAttributedString_(_seg(feth_bar,         _bar_attrs(feth_color)))
        btn = self._nsapp.nsstatusitem.button()
        btn.setAttributedTitle_(full)
        btn.sizeToFit()
        self._nsapp.nsstatusitem.setLength_(btn.frame().size.width)
        btn.setWantsLayer_(True)
        btn.layer().setBackgroundColor_(NSColor.whiteColor().CGColor())
        btn.layer().setCornerRadius_(3.0)

    @staticmethod
    def _make_bar(price: float, low: float | None, high: float | None, width: int = 8) -> str:
        if low is None and high is None:
            return "─" * (width + 2)
        # If only one threshold, mirror it around the price so the bar has a range
        if low is None:
            low = price - abs(high - price)
        if high is None:
            high = price + abs(price - low)
        if high <= low:
            return "─" * (width + 2)
        pos = max(0.0, min(1.0, (price - low) / (high - low)))
        slot = round(pos * (width - 1))
        inner = "".join("█" if i < slot else ("◆" if i == slot else "░") for i in range(width))
        return f"↓{inner}↑"

    def _update_menu_items(self, prices: dict, settings: dict) -> None:
        fbtc = prices.get("FBTC")
        feth = prices.get("FETH")
        fbtc_high = settings.get("high_threshold")
        fbtc_low  = settings.get("low_threshold")
        feth_high = settings.get("feth_high_threshold")
        feth_low  = settings.get("feth_low_threshold")

        self._fbtc_price_item.title = f"FBTC: ${fbtc:,.2f}" if fbtc is not None else "FBTC: —"
        self._fbtc_high_item.title  = f"  ↑ High: ${fbtc_high:,.2f}" if fbtc_high is not None else "  ↑ High: not set"
        self._fbtc_low_item.title   = f"  ↓ Low: ${fbtc_low:,.2f}"  if fbtc_low  is not None else "  ↓ Low: not set"

        self._feth_price_item.title = f"FETH: ${feth:,.2f}" if feth is not None else "FETH: —"
        self._feth_high_item.title  = f"  ↑ High: ${feth_high:,.2f}" if feth_high is not None else "  ↑ High: not set"
        self._feth_low_item.title   = f"  ↓ Low: ${feth_low:,.2f}"  if feth_low  is not None else "  ↓ Low: not set"

    def _startup_poll(self, timer: rumps.Timer) -> None:
        timer.stop()
        self._do_poll()

    def _heartbeat(self, _) -> None:
        settings = get_settings(self.config.database_path)
        latest = get_latest_price_sample(self.config.database_path, symbol="FBTC")
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
            self._set_title("B —", "──────────", "E —", "──────────")
            return

        settings = result["settings"]
        symbols  = result.get("symbols", {})
        prices   = {s: symbols[s]["price_usd"] for s in symbols if "price_usd" in symbols[s]}

        fbtc_price = prices.get("FBTC")
        feth_price = prices.get("FETH")
        fbtc_high  = settings["high_threshold"]
        fbtc_low   = settings["low_threshold"]

        if fbtc_price is not None:
            if fbtc_low  is not None and fbtc_price <= fbtc_low:
                status = "low"
            elif fbtc_high is not None and fbtc_price >= fbtc_high:
                status = "high"
            else:
                status = "normal"
        else:
            status = "normal"

        feth_high = settings.get("feth_high_threshold")
        feth_low  = settings.get("feth_low_threshold")

        fbtc_line = f"B ${fbtc_price:.2f}" if fbtc_price is not None else "B —"
        fbtc_bar  = self._make_bar(fbtc_price, fbtc_low, fbtc_high, width=6) if fbtc_price is not None else "────────"
        feth_line = f"E ${feth_price:.2f}" if feth_price is not None else "E —"
        feth_bar  = self._make_bar(feth_price, feth_low, feth_high, width=6) if feth_price is not None else "────────"
        self._set_title(fbtc_line, fbtc_bar, feth_line, feth_bar, status=status)

        self._update_menu_items(prices, settings)

        for sym in ["FBTC", "FETH"]:
            sym_result = symbols.get(sym, {})
            for event in sym_result.get("alerts", []):
                if event["alert_type"] in ("HIGH", "LOW"):
                    price = sym_result["price_usd"]
                    direction = "above" if event["alert_type"] == "HIGH" else "below"
                    rumps.notification(
                        title=f"{sym} Price Alert",
                        subtitle=f"${price:,.2f} — {direction} ${event['threshold_value']:,.2f}",
                        message=event["sms_message"],
                    )

        self._last_poll_time = time.time()

    # ── FBTC threshold controls ──────────────────────────────────────────────

    def _set_fbtc_high(self, _) -> None:
        self._set_threshold("high_threshold", "FBTC High",
                            "Alert when FBTC rises above this price (USD).")

    def _set_fbtc_low(self, _) -> None:
        self._set_threshold("low_threshold", "FBTC Low",
                            "Alert when FBTC falls below this price (USD).")

    def _clear_fbtc_high(self, _) -> None:
        save_settings(self.config.database_path, {"high_threshold": None, "high_alert_active": False})
        self._refresh_display()

    def _clear_fbtc_low(self, _) -> None:
        save_settings(self.config.database_path, {"low_threshold": None, "low_alert_active": False})
        self._refresh_display()

    # ── FETH threshold controls ──────────────────────────────────────────────

    def _set_feth_high(self, _) -> None:
        self._set_threshold("feth_high_threshold", "FETH High",
                            "Alert when FETH rises above this price (USD).")

    def _set_feth_low(self, _) -> None:
        self._set_threshold("feth_low_threshold", "FETH Low",
                            "Alert when FETH falls below this price (USD).")

    def _clear_feth_high(self, _) -> None:
        save_settings(self.config.database_path, {"feth_high_threshold": None, "feth_high_alert_active": False})
        self._refresh_display()

    def _clear_feth_low(self, _) -> None:
        save_settings(self.config.database_path, {"feth_low_threshold": None, "feth_low_alert_active": False})
        self._refresh_display()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _set_threshold(self, key: str, title: str, message: str) -> None:
        current = get_settings(self.config.database_path)[key]
        window = rumps.Window(
            title=f"Set {title} Threshold",
            message=f"{message}\nLeave blank to clear.",
            default_text=f"{current:.2f}" if current is not None else "",
            ok="Save",
            cancel="Cancel",
            dimensions=(220, 22),
        )
        response = window.run()
        if response.clicked:
            raw = response.text.strip()
            value = float(raw) if raw else None
            active_key = key.replace("_threshold", "_alert_active")
            save_settings(self.config.database_path, {key: value, active_key: False})
            self._refresh_display()

    def _refresh_display(self) -> None:
        settings = get_settings(self.config.database_path)
        prices = {
            "FBTC": (get_latest_price_sample(self.config.database_path, symbol="FBTC") or {}).get("price_usd"),
            "FETH": (get_latest_price_sample(self.config.database_path, symbol="FETH") or {}).get("price_usd"),
        }
        self._update_menu_items(prices, settings)

    def _run_check_now(self, _) -> None:
        self._do_poll()

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    import os, signal
    my_pid = os.getpid()
    import subprocess
    result = subprocess.run(["pgrep", "-f", "menubar_app.py"], capture_output=True, text=True)
    other_pids = [int(p) for p in result.stdout.split() if p.strip() and int(p) != my_pid]
    if other_pids:
        for pid in other_pids:
            os.kill(pid, signal.SIGTERM)
    BTCMenuBarApp().run()
