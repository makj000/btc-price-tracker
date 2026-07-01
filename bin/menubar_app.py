from __future__ import annotations

import os
import subprocess
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
    NSMakeRect,
    NSMinYEdge,
    NSMutableAttributedString,
    NSMutableParagraphStyle,
    NSPopover,
    NSParagraphStyleAttributeName,
    NSTextField,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSView,
    NSViewController,
)
from Foundation import NSObject

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from btc_tracker.config import load_config
from btc_tracker.db import get_latest_price_sample, get_settings, init_db, save_settings, seed_thresholds
from btc_tracker.poller import run_poll_cycle
from btc_tracker.schedule import next_scheduled_check_at


class ThresholdHoverController(NSObject):
    def initWithApp_(self, app):
        self = self.init()
        if self is None:
            return None
        self.app = app
        return self

    def mouseEntered_(self, event) -> None:
        self.app._show_threshold_popover()

    def mouseExited_(self, event) -> None:
        self.app._hide_threshold_popover()


class BTCMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("BTC", quit_button="Quit")
        self.config = load_config()
        init_db(self.config.database_path)
        seed_thresholds(self.config.database_path, self.config.seed_high_threshold, self.config.seed_low_threshold)
        self._last_poll_time = 0.0
        self._threshold_tooltip = "Thresholds loading..."
        self._hover_controller = ThresholdHoverController.alloc().initWithApp_(self)
        self._tracking_button = None
        self._threshold_popover = None

        self._btc_price_item = rumps.MenuItem("BTC: —")
        self._btc_high_item  = rumps.MenuItem("  ↑ High: not set", callback=self._set_btc_high)
        self._btc_low_item   = rumps.MenuItem("  ↓ Low: not set",  callback=self._set_btc_low)

        self._eth_price_item = rumps.MenuItem("ETH: —")
        self._eth_high_item  = rumps.MenuItem("  ↑ High: not set", callback=self._set_eth_high)
        self._eth_low_item   = rumps.MenuItem("  ↓ Low: not set",  callback=self._set_eth_low)

        self.menu = [
            rumps.MenuItem("↻  Refresh Prices", callback=self._run_check_now),
            rumps.MenuItem("⟳  Restart App",    callback=self._restart),
            None,
            self._btc_price_item,
            self._btc_high_item,
            self._btc_low_item,
            None,
            self._eth_price_item,
            self._eth_high_item,
            self._eth_low_item,
            None,
            rumps.MenuItem("Clear BTC High", callback=self._clear_btc_high),
            rumps.MenuItem("Clear BTC Low",  callback=self._clear_btc_low),
            None,
            rumps.MenuItem("Clear ETH High", callback=self._clear_eth_high),
            rumps.MenuItem("Clear ETH Low",  callback=self._clear_eth_low),
            None,
            rumps.MenuItem("BTC Chart ↗", callback=lambda _: webbrowser.open("https://finance.yahoo.com/chart/BTC-USD")),
            rumps.MenuItem("ETH Chart ↗", callback=lambda _: webbrowser.open("https://finance.yahoo.com/chart/ETH-USD")),
        ]

        self._timer = rumps.Timer(self._heartbeat, 30)
        self._timer.start()
        self._startup_timer = rumps.Timer(self._startup_poll, 1)
        self._startup_timer.start()

    def _set_title(self, btc_line: str, btc_bar: str, eth_line: str, eth_bar: str, status: str = "normal") -> None:
        if not hasattr(self, "_nsapp") or not hasattr(self._nsapp, "nsstatusitem"):
            return

        if status == "high":
            btc_color = NSColor.systemGreenColor()
            btc_bar_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.36, 0.18, 1.0)
        elif status == "low":
            btc_color = NSColor.systemRedColor()
            btc_bar_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.78, 0.0, 0.0, 1.0)
        else:
            btc_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.68, 0.27, 0.0, 1.0)
            btc_bar_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.36, 0.0, 1.0)
        eth_color = NSColor.systemBlueColor()
        eth_bar_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.2, 0.9, 1.0)

        text_font = NSFont.monospacedSystemFontOfSize_weight_(8.0, 0.0)
        bar_font  = NSFont.monospacedSystemFontOfSize_weight_(5.5, 0.3)

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
        full.appendAttributedString_(_seg(f"{btc_line}\n", _text_attrs(btc_color)))
        full.appendAttributedString_(_seg(f"{btc_bar}\n", _bar_attrs(btc_bar_color)))
        full.appendAttributedString_(_seg(f"{eth_line}\n", _text_attrs(eth_color)))
        full.appendAttributedString_(_seg(eth_bar,         _bar_attrs(eth_bar_color)))
        btn = self._nsapp.nsstatusitem.button()
        btn.setAttributedTitle_(full)
        btn.sizeToFit()
        self._nsapp.nsstatusitem.setLength_(btn.frame().size.width)
        self._install_hover_tracking(btn)
        btn.setWantsLayer_(True)
        btn.layer().setBackgroundColor_(NSColor.whiteColor().CGColor())
        btn.layer().setCornerRadius_(3.0)

    def _install_hover_tracking(self, btn) -> None:
        if btn is self._tracking_button:
            return
        options = NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            NSMakeRect(0, 0, 0, 0),
            options,
            self._hover_controller,
            None,
        )
        btn.addTrackingArea_(area)
        self._tracking_button = btn

    def _show_threshold_popover(self) -> None:
        if not hasattr(self, "_nsapp") or not hasattr(self._nsapp, "nsstatusitem"):
            return
        btn = self._nsapp.nsstatusitem.button()
        if btn is None:
            return
        if self._threshold_popover is not None and self._threshold_popover.isShown():
            return

        text = NSTextField.alloc().initWithFrame_(NSMakeRect(12, 10, 220, 108))
        text.setStringValue_(self._threshold_tooltip)
        text.setEditable_(False)
        text.setSelectable_(False)
        text.setBezeled_(False)
        text.setDrawsBackground_(False)
        text.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12.0, 0.0))

        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 244, 128))
        view.addSubview_(text)

        controller = NSViewController.alloc().init()
        controller.setView_(view)

        popover = NSPopover.alloc().init()
        popover.setContentViewController_(controller)
        popover.setAnimates_(False)
        popover.showRelativeToRect_ofView_preferredEdge_(btn.bounds(), btn, NSMinYEdge)
        self._threshold_popover = popover

    def _hide_threshold_popover(self) -> None:
        if self._threshold_popover is not None:
            self._threshold_popover.close()
            self._threshold_popover = None

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

    @staticmethod
    def _bar_width_for_lines(*lines: str) -> int:
        longest_line = max((len(line) for line in lines), default=8)
        return max(8, int(longest_line * 1.45) - 2)

    def _update_menu_items(self, prices: dict, settings: dict) -> None:
        btc = prices.get("BTC")
        eth = prices.get("ETH")
        btc_high = settings.get("high_threshold")
        btc_low  = settings.get("low_threshold")
        eth_high = settings.get("feth_high_threshold")
        eth_low  = settings.get("feth_low_threshold")

        self._btc_price_item.title = f"BTC: ${btc:,.2f}" if btc is not None else "BTC: —"
        self._btc_high_item.title  = f"  ↑ High: ${btc_high:,.2f}" if btc_high is not None else "  ↑ High: not set"
        self._btc_low_item.title   = f"  ↓ Low: ${btc_low:,.2f}"  if btc_low  is not None else "  ↓ Low: not set"

        self._eth_price_item.title = f"ETH: ${eth:,.2f}" if eth is not None else "ETH: —"
        self._eth_high_item.title  = f"  ↑ High: ${eth_high:,.2f}" if eth_high is not None else "  ↑ High: not set"
        self._eth_low_item.title   = f"  ↓ Low: ${eth_low:,.2f}"  if eth_low  is not None else "  ↓ Low: not set"
        self._threshold_tooltip = self._format_threshold_tooltip(prices, settings)
        self._apply_threshold_tooltip()

    def _apply_threshold_tooltip(self) -> None:
        if self._threshold_popover is not None and self._threshold_popover.isShown():
            self._hide_threshold_popover()
            self._show_threshold_popover()

    @staticmethod
    def _format_threshold_tooltip(prices: dict, settings: dict) -> str:
        def money(value: float | None) -> str:
            return f"${value:,.2f}" if value is not None else "not set"

        btc = prices.get("BTC")
        eth = prices.get("ETH")
        return "\n".join([
            f"BTC {money(btc)}",
            f"High: {money(settings.get('high_threshold'))}",
            f"Low: {money(settings.get('low_threshold'))}",
            "",
            f"ETH {money(eth)}",
            f"High: {money(settings.get('feth_high_threshold'))}",
            f"Low: {money(settings.get('feth_low_threshold'))}",
        ])

    def _startup_poll(self, timer: rumps.Timer) -> None:
        timer.stop()
        self._do_poll()

    def _heartbeat(self, _) -> None:
        settings = get_settings(self.config.database_path)
        latest = get_latest_price_sample(self.config.database_path, symbol="BTC")
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

        btc_price = prices.get("BTC")
        eth_price = prices.get("ETH")
        btc_high  = settings["high_threshold"]
        btc_low   = settings["low_threshold"]

        if btc_price is not None:
            if btc_low  is not None and btc_price <= btc_low:
                status = "low"
            elif btc_high is not None and btc_price >= btc_high:
                status = "high"
            else:
                status = "normal"
        else:
            status = "normal"

        eth_high = settings.get("feth_high_threshold")
        eth_low  = settings.get("feth_low_threshold")

        btc_line = f"B ${btc_price:.2f}" if btc_price is not None else "B —"
        eth_line = f"E ${eth_price:.2f}" if eth_price is not None else "E —"
        bar_width = self._bar_width_for_lines(btc_line, eth_line)
        btc_bar  = self._make_bar(btc_price, btc_low, btc_high, width=bar_width) if btc_price is not None else "─" * (bar_width + 2)
        eth_bar  = self._make_bar(eth_price, eth_low, eth_high, width=bar_width) if eth_price is not None else "─" * (bar_width + 2)
        self._update_menu_items(prices, settings)
        self._set_title(btc_line, btc_bar, eth_line, eth_bar, status=status)

        for sym in ["BTC", "ETH"]:
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

    # ── BTC threshold controls ───────────────────────────────────────────────

    def _set_btc_high(self, _) -> None:
        self._set_threshold("high_threshold", "BTC High",
                            "Alert when BTC rises above this price (USD).")

    def _set_btc_low(self, _) -> None:
        self._set_threshold("low_threshold", "BTC Low",
                            "Alert when BTC falls below this price (USD).")

    def _clear_btc_high(self, _) -> None:
        save_settings(self.config.database_path, {"high_threshold": None, "high_alert_active": False})
        self._refresh_display()

    def _clear_btc_low(self, _) -> None:
        save_settings(self.config.database_path, {"low_threshold": None, "low_alert_active": False})
        self._refresh_display()

    # ── ETH threshold controls ───────────────────────────────────────────────

    def _set_eth_high(self, _) -> None:
        self._set_threshold("feth_high_threshold", "ETH High",
                            "Alert when ETH rises above this price (USD).")

    def _set_eth_low(self, _) -> None:
        self._set_threshold("feth_low_threshold", "ETH Low",
                            "Alert when ETH falls below this price (USD).")

    def _clear_eth_high(self, _) -> None:
        save_settings(self.config.database_path, {"feth_high_threshold": None, "feth_high_alert_active": False})
        self._refresh_display()

    def _clear_eth_low(self, _) -> None:
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
            "BTC": (get_latest_price_sample(self.config.database_path, symbol="BTC") or {}).get("price_usd"),
            "ETH": (get_latest_price_sample(self.config.database_path, symbol="ETH") or {}).get("price_usd"),
        }
        self._update_menu_items(prices, settings)

    def _run_check_now(self, _) -> None:
        self._do_poll()

    def _restart(self, _) -> None:
        python_app = next((parent for parent in Path(sys.executable).parents if parent.suffix == ".app"), None)
        if python_app is not None:
            subprocess.Popen(["open", "-n", str(python_app), "--args", str(Path(__file__).resolve())])
            return

        log = Path("/tmp/crypto-price-tracker-menubar.log").open("a")
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            cwd=str(PROJECT_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    import signal
    my_pid = os.getpid()
    result = subprocess.run(["pgrep", "-f", "menubar_app.py"], capture_output=True, text=True)
    other_pids = [int(p) for p in result.stdout.split() if p.strip() and int(p) != my_pid]
    if other_pids:
        for pid in other_pids:
            os.kill(pid, signal.SIGTERM)
    BTCMenuBarApp().run()
