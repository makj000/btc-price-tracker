# Crypto Price Tracker

macOS menubar app + local web dashboard that polls FBTC and FETH prices via Yahoo Finance, stores history in SQLite, and sends Telegram/SMS alerts when configured thresholds are crossed.

## Features

- macOS menubar item showing live FBTC (orange) and FETH (blue) prices with progress bars
- Local web dashboard for price history, settings, and alert log
- Telegram and SMS (Twilio) alerts on threshold crossings
- Threshold re-arming logic to avoid repeated alerts while price stays above/below
- SQLite storage for price history and alert log

## Setup

1. Create a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create your env file:

   ```bash
   cp .env.example .env
   ```

4. Fill in your Twilio and Telegram credentials in `.env`.

## Running

**Menubar app:**

```bash
bin/start_menubar.sh
```

**Web dashboard:**

```bash
bin/start_webapp.sh
```

Open `http://127.0.0.1:8000`.

> **Note:** The web dashboard has no authentication. Keep `FLASK_HOST` set to `127.0.0.1` (the default). Do not expose it to the network.

## Notes

- Prices are fetched from Yahoo Finance — no API key required.
- SMS alerts are skipped gracefully if Twilio credentials are missing.
- Telegram alerts are skipped gracefully if bot token/chat ID are missing.
- The saved poll frequency affects the menubar's next-check timer; the launchd/cron job must be configured separately to match.
