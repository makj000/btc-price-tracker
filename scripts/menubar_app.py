from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
import shlex
from urllib.error import URLError
from urllib.request import urlopen

import rumps
from AppKit import NSAttributedString, NSColor, NSForegroundColorAttributeName

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from btc_tracker.config import load_config
from btc_tracker.db import get_settings, init_db
from btc_tracker.poller import run_poll_cycle


class BTCMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("BTC", quit_button="Quit")
        self.config = load_config()
        init_db(self.config.database_path)
        self._last_poll_time = 0.0

        self.menu = [
            rumps.MenuItem("Open Dashboard", callback=self._open_dashboard),
            rumps.MenuItem("Run Check Now", callback=self._run_check_now),
            rumps.MenuItem("Restart", callback=self._restart_app),
            None,
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

    def _startup_poll(self, timer: rumps.Timer) -> None:
        timer.stop()
        self._do_poll()

    def _heartbeat(self, _) -> None:
        settings = get_settings(self.config.database_path)
        freq_seconds = settings["poll_frequency_minutes"] * 60
        if time.time() - self._last_poll_time >= freq_seconds:
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

        self._set_title(f"${price:,.0f}", status=status)

        for event in result["alerts"]:
            if event["alert_type"] in ("HIGH", "LOW"):
                direction = "above" if event["alert_type"] == "HIGH" else "below"
                threshold = event["threshold_value"]
                rumps.notification(
                    title="BTC Price Alert",
                    subtitle=f"${price:,.0f} - {direction} ${threshold:,.0f}",
                    message=event["sms_message"],
                )
                break

        self._last_poll_time = time.time()

    def _open_dashboard(self, _) -> None:
        self._ensure_dashboard_running()
        subprocess.Popen(["open", self._dashboard_url()])

    def _run_check_now(self, _) -> None:
        self._do_poll()

    def _restart_app(self, _) -> None:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        rumps.quit_application()

    def _dashboard_url(self) -> str:
        return f"http://{self.config.flask_host}:{self.config.flask_port}"

    def _dashboard_healthcheck_url(self) -> str:
        return f"{self._dashboard_url()}/api/status"

    def _is_dashboard_running(self) -> bool:
        try:
            with urlopen(self._dashboard_healthcheck_url(), timeout=1):
                return True
        except URLError:
            return False
        except Exception:
            return False

    def _server_command(self) -> list[str]:
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
        python_bin = venv_python if venv_python.exists() else Path(sys.executable)
        return [str(python_bin), str(PROJECT_ROOT / "app.py")]

    def _launch_dashboard_server_with_logs(self) -> None:
        command = " ".join(shlex.quote(part) for part in self._server_command())
        terminal_command = f"cd {shlex.quote(str(PROJECT_ROOT))} && {command}"
        subprocess.Popen(
            ["osascript", "-e", f'tell application "Terminal" to do script "{terminal_command}"'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _ensure_dashboard_running(self) -> None:
        if self._is_dashboard_running():
            return

        self._launch_dashboard_server_with_logs()

        deadline = time.time() + 10
        while time.time() < deadline:
            if self._is_dashboard_running():
                return
            time.sleep(0.25)


if __name__ == "__main__":
    BTCMenuBarApp().run()
