# Changelog

## 1.1.0

meteo.ua was redesigned in October 2026: the old pages and city ids stopped working
and the integration showed no data. This release moves to the site's JSON API.

- Data comes from `/api/wx/{id}` (current, 16-day daily, hourly) instead of HTML scraping.
- Daily forecast: 16 real forecast days. The site's month page continues with
  60-year climate normals ("Кліматична норма"); those are no longer reported as a forecast.
- Hourly forecast: 7 days, day/night conditions from sunrise and sunset.
- Timestamps use Europe/Kyiv, so the summer/winter time switch is handled (was fixed +02:00).
- Existing installations migrate automatically: the old city id is replaced by the new one,
  found by the stored city name. Entity ids and unique ids do not change.
- City search uses the new `/api/suggest`; the default list is the regional centres.
- New attributes: apparent temperature, dew point, visibility, precipitation.
- Weather codes mapped completely (WMO), unknown codes are no longer shown as cloudy.
- Unit tests with captured API responses (`tests/`).

Note: the add-on's Chromium HTTP server (port 5581) is no longer used by the integration.

## 1.0.0

First release
