# Changelog

## 1.1.4

- No blocking file I/O in the event loop: the version is read at import and the card is
  copied in an executor (Home Assistant logged "Detected blocking call to read_text").

## 1.1.3

- **Fix: the automatic city-id migration from 1.1.0 never ran.** meteo.ua answers old and
  data-less ids with HTTP 404 (not an empty 200), which was treated as a network error.
  A 404 is now "no forecast for this id": installations from 1.0.x move to the new id on
  the first update, and the setup form shows "no data" instead of "cannot connect".

## 1.1.2

- Setup checks that meteo.ua actually has a forecast for the chosen settlement. Many villages
  are in the search index but return an empty payload; they now get a clear error in the form
  instead of an integration that never loads.

## 1.1.1

- The repository is also a HACS integration (`custom_components/meteo_ua` at the root, `hacs.json`).
  Installing through HACS avoids the add-on and its ~2 GB Chromium image; the integration no longer needs it.
- A test keeps the HACS copy and the add-on bundle identical.

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
