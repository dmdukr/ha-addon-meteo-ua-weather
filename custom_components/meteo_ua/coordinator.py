"""DataUpdateCoordinator for Meteo UA."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_CITY_ID, CONF_CITY_NAME, CONF_CITY_SLUG, DOMAIN, UPDATE_INTERVAL_CURRENT
from .parsers.api import (
    MeteoUaApiError,
    async_fetch_wx,
    async_suggest,
    build_current,
    build_daily,
    build_hourly,
    resolve_locale,
)

_LOGGER = logging.getLogger(__name__)


class MeteoUaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch current weather, hourly and daily forecast from the meteo.ua JSON API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.city_slug: str = entry.data[CONF_CITY_SLUG]
        super().__init__(
            hass, _LOGGER,
            name=f"{DOMAIN}_{self.city_slug}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_CURRENT),
        )

    @property
    def city_id(self) -> str:
        return str(self.entry.data[CONF_CITY_ID])

    async def _async_migrate_city_id(self, session) -> bool:
        """Map a pre-October-2026 city id to the new site's id by the stored name.

        The redesigned meteo.ua renumbered every settlement (Kyiv 33345 → 34) and
        the old ids return an empty payload. Only CONF_CITY_ID is rewritten:
        CONF_CITY_SLUG stays, because the entity unique_id is built from it.
        """
        name = (self.entry.data.get(CONF_CITY_NAME) or "").split(",")[0].strip()
        if not name:
            return False
        try:
            found = await async_suggest(session, name, loc="ua")
        except Exception as exc:  # network error: retry on the next update
            _LOGGER.warning("City id migration for '%s' failed: %s", name, exc)
            return False
        exact = [c for c in found if c["title"].split(",")[0].strip().lower() == name.lower()]
        pick = (exact or found or [None])[0]
        if pick is None:
            _LOGGER.error("City '%s' not found on meteo.ua — re-add the integration", name)
            return False
        old = self.city_id
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_CITY_ID: pick["city_id"]},
        )
        _LOGGER.warning("meteo.ua city id migrated for '%s': %s → %s (%s)",
                        name, old, pick["city_id"], pick["title"])
        return True

    async def _async_update_data(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        try:
            try:
                wx = await async_fetch_wx(session, self.city_id)
            except MeteoUaApiError:
                if not await self._async_migrate_city_id(session):
                    raise
                wx = await async_fetch_wx(session, self.city_id)
        except MeteoUaApiError as exc:
            raise UpdateFailed(f"meteo.ua returned an unexpected payload: {exc}") from exc
        except Exception as exc:
            raise UpdateFailed(f"meteo.ua request failed: {exc}") from exc

        locale = resolve_locale(self.hass.config.language)
        return {
            "current": build_current(wx, locale),
            "hourly": build_hourly(wx, locale),
            "daily": build_daily(wx, locale),
            "locale": locale,
        }
