* Goal
use CoinMarketCap API to build a background BTC price checker with SMS alerts when configured thresholds are crossed.

the check frequency is configurable in minutes, with a minimum value of 5.

the app stores price history locally and shows the expected next check time based on the saved frequency.

the actual background scheduler still needs to be configured separately to match the saved frequency.

the project also includes a standalone macOS menu bar app that reads the same SQLite DB, displays the live BTC price, and uses native notifications for newly triggered threshold alerts.

the menu bar text should use dark green when the price is at or above the high threshold, red when it is at or below the low threshold, and the default system label color otherwise.

the menu bar app should offer actions to open the dashboard, run a check immediately, and restart itself.

when opening the dashboard from the menu bar app, it should start the Flask server first if needed and show the server logs in Terminal.

* UI
index.html reports price history and recent alert activity.

the settings section allows configuring:
- high threshold
- low threshold
- check frequency in minutes
- cooldown minutes
- alert phone number
- sms on/off

the UI should keep the settings section compact.

show the app version in the interface.
