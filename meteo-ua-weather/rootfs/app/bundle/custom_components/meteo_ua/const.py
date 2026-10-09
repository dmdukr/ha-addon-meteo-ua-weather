"""Constants for Meteo UA integration."""

DOMAIN = "meteo_ua"

CONF_CITY_ID = "city_id"
CONF_CITY_SLUG = "city_slug"
CONF_CITY_NAME = "city_name"

# One request to /api/wx/{id} returns current, hourly and daily data together.
UPDATE_INTERVAL_CURRENT = 1800   # 30 min
