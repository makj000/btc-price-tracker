* Goal
use CoinMarketCap API to build a background BTC price checker with SMS alerts when configured thresholds are crossed.

the check frequency is configurable in minutes, with a minimum value of 5.

the app stores price history locally and shows the expected next check time based on the saved frequency.

the actual background scheduler still needs to be configured separately to match the saved frequency.

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
