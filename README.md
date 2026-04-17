# BTC Price Tracker

Small Python app that polls the CoinMarketCap API for the BTC/USD price on a configurable interval, stores local history in SQLite, and sends SMS alerts through Twilio when the configured thresholds are crossed.

## Features

- Local dashboard for current price, history, settings, and recent alerts
- Cron-friendly polling script
- SQLite storage for price history and alert log
- Threshold crossing logic that avoids repeated SMS spam while the price remains above or below a threshold

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

4. Fill in your CoinMarketCap and Twilio credentials in `.env`.

5. Start the web app:

   ```bash
   python app.py
   ```

6. Open `http://127.0.0.1:8000`.

## Cron

Run the polling worker on the same interval you save in the dashboard. The minimum supported frequency is 5 minutes:

```cron
*/5 * * * * cd /Users/kma/dev/data-scraping/crypto/btc-price-tracker && /usr/bin/env python3 scripts/poll_price.py >> data/poll.log 2>&1
```

If you use a virtualenv, point cron to the venv's `python` binary instead.

## Notes

- The dashboard reads from local SQLite history instead of hitting CoinMarketCap from the browser.
- The saved check frequency affects the dashboard's expected next check time, but cron still needs to be configured separately to match it.
- SMS alerts fire on threshold crossings, then re-arm once the price moves back across the threshold boundary.
- If SMS credentials are missing, alerts are still recorded in the database as skipped.
