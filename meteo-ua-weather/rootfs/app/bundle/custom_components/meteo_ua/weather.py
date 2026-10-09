"""Weather platform for Meteo UA."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CITY_NAME, CONF_CITY_SLUG, DOMAIN
from .coordinator import MeteoUaCoordinator

_MONTHS = {
    "uk": ["січня", "лютого", "березня", "квітня", "травня", "червня",
           "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"],
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MeteoUaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MeteoUaWeather(coordinator, entry)])


def _legacy_day(i: int, day: dict[str, Any], locale: str) -> dict[str, Any]:
    """Daily entry in the attribute shape of v1.0 (kept for cards and templates)."""
    d = date.fromisoformat(day["date"])
    hi, speed = day.get("temp_max"), day.get("wind_speed")
    unit = "м/с" if locale == "uk" else "m/s"
    return {
        "day": i + 1,
        "date": f"{d.day} {_MONTHS.get(locale, _MONTHS['en'])[d.month - 1]}",
        "date_iso": day["date"],
        "temp": "" if hi is None else f"{round(hi):+d}°",
        "temp_day": hi,
        "temp_night": day.get("temp_min"),
        "condition": day.get("condition_text", ""),
        "ha_condition": day.get("condition"),
        "wind": "" if speed is None else f"{speed:.1f} {unit}",
        "precipitation": day.get("precipitation"),
        "icon": "" if day.get("weather_code") is None else f"wmo-{day['weather_code']}",
    }


class MeteoUaWeather(CoordinatorEntity[MeteoUaCoordinator], WeatherEntity):
    """Current weather + daily and hourly forecast."""

    _attr_has_entity_name = True
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.MMHG
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(self, coordinator: MeteoUaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        # Built from the slug stored at setup: keep it stable across the city-id migration.
        self._attr_unique_id = f"meteo_ua_weather_{entry.data[CONF_CITY_SLUG]}"
        self._attr_name = f"Meteo UA {entry.data[CONF_CITY_NAME]}"
        self._attr_attribution = "meteo.ua"

    @property
    def _current(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("current", {})

    @property
    def condition(self) -> str | None:
        return self._current.get("condition")

    @property
    def native_temperature(self) -> float | None:
        return self._current.get("temperature")

    @property
    def native_apparent_temperature(self) -> float | None:
        return self._current.get("apparent_temperature")

    @property
    def native_dew_point(self) -> float | None:
        return self._current.get("dew_point")

    @property
    def humidity(self) -> float | None:
        return self._current.get("humidity")

    @property
    def native_pressure(self) -> float | None:
        return self._current.get("pressure")

    @property
    def native_wind_speed(self) -> float | None:
        return self._current.get("wind_speed")

    @property
    def wind_bearing(self) -> float | None:
        return self._current.get("wind_bearing")

    @property
    def native_visibility(self) -> float | None:
        return self._current.get("visibility")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        locale = data.get("locale", "uk")
        daily = data.get("daily", [])
        return {
            "condition_text": self._current.get("condition_text", ""),
            "wind_direction": self._current.get("wind_direction", ""),
            "observed_at": self._current.get("observed_at"),
            "forecast": [_legacy_day(i, d, locale) for i, d in enumerate(daily)],
            "forecast_days": len(daily),
            "forecast_city": self.coordinator.city_slug,
        }

    async def async_forecast_daily(self) -> list[Forecast]:
        """Daily forecast for the days the API actually forecasts (16).

        meteo.ua's month page continues with 60-year climate normals ("Кліматична норма");
        those are statistics, not a forecast, and are not reported as one.
        """
        return [
            Forecast(
                datetime=day["datetime"],
                condition=day.get("condition"),
                native_temperature=day.get("temp_max"),
                native_templow=day.get("temp_min"),
                native_precipitation=day.get("precipitation"),
                native_wind_speed=day.get("wind_speed"),
                wind_bearing=day.get("wind_bearing"),
            )
            for day in (self.coordinator.data or {}).get("daily", [])
        ]

    async def async_forecast_hourly(self) -> list[Forecast]:
        """Hourly forecast from one hour ago, up to 7 days.

        Re-filtered on every call: the coordinator refreshes every 30 minutes, so the
        head of the cached list ages between updates.
        """
        start = datetime.now(timezone.utc) - timedelta(hours=1, minutes=59)
        return [
            Forecast(
                datetime=h["datetime"],
                condition=h.get("condition"),
                native_temperature=h.get("temperature"),
                native_apparent_temperature=h.get("apparent_temperature"),
                native_dew_point=h.get("dew_point"),
                humidity=h.get("humidity"),
                native_pressure=h.get("pressure"),
                native_wind_speed=h.get("wind_speed"),
                wind_bearing=h.get("wind_bearing"),
                native_precipitation=h.get("precipitation"),
            )
            for h in (self.coordinator.data or {}).get("hourly", [])
            if datetime.fromisoformat(h["datetime"]) >= start
        ]
