"""Config flow for Meteo UA — two-step: filter then create."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import DOMAIN, CONF_CITY_ID, CONF_CITY_SLUG, CONF_CITY_NAME
from .parsers.api import async_suggest

_LOGGER = logging.getLogger(__name__)

MAX_RESULTS = 50
MIN_CHARS = 3

# Regional centres with the ids of the redesigned meteo.ua (October 2026).
# Old ids (Kyiv 33345, …) return an empty payload now; existing entries are
# migrated by the coordinator.
DEFAULT_CITIES: list[dict] = [
    {"city_id": "34", "slug": "kiev", "title": "Київ"},
    {"city_id": "6", "slug": "chernigov", "title": "Чернігів"},
    {"city_id": "23", "slug": "sumyi", "title": "Суми"},
    {"city_id": "31", "slug": "jitomir", "title": "Житомир"},
    {"city_id": "28", "slug": "rovno", "title": "Рівне"},
    {"city_id": "13", "slug": "lutsk", "title": "Луцьк"},
    {"city_id": "44", "slug": "lvov", "title": "Львів"},
    {"city_id": "47", "slug": "ternopol", "title": "Тернопіль"},
    {"city_id": "49", "slug": "khmelnitskiy", "title": "Хмельницький"},
    {"city_id": "67", "slug": "ivano-frankovsk", "title": "Івано-Франківськ"},
    {"city_id": "83", "slug": "uzhgorod", "title": "Ужгород"},
    {"city_id": "91", "slug": "chernovtsyi", "title": "Чернівці"},
    {"city_id": "71", "slug": "vinnitsa", "title": "Вінниця"},
    {"city_id": "56", "slug": "cherkassyi", "title": "Черкаси"},
    {"city_id": "97", "slug": "kropivnitskiy-kirovograd", "title": "Кропивницький"},
    {"city_id": "58", "slug": "poltava", "title": "Полтава"},
    {"city_id": "164", "slug": "dnepr-dnepropetrovsk", "title": "Дніпро"},
    {"city_id": "150", "slug": "harkov", "title": "Харків"},
    {"city_id": "169", "slug": "donetsk", "title": "Донецьк"},
    {"city_id": "170", "slug": "lugansk", "title": "Луганськ"},
    {"city_id": "111", "slug": "odessa", "title": "Одеса"},
    {"city_id": "112", "slug": "nikolaev", "title": "Миколаїв"},
    {"city_id": "122", "slug": "herson", "title": "Херсон"},
    {"city_id": "172", "slug": "zaporizhia", "title": "Запоріжжя"},
    {"city_id": "134", "slug": "simferopol", "title": "Сімферополь"},
]


async def _fetch_cities(hass, phrase: str) -> list[dict]:
    """Search settlements via /api/suggest (Ukrainian names); [] on any failure."""
    try:
        return (await async_suggest(async_get_clientsession(hass), phrase, loc="ua"))[:MAX_RESULTS]
    except Exception as exc:
        _LOGGER.warning("meteo.ua city search failed: %s", exc)
        return []


def _build_options(cities: list[dict]) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=f"{c['city_id']}/{c['slug']}", label=c["title"])
        for c in cities
    ]


class MeteoUaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: filter → select & create."""

    VERSION = 2

    def __init__(self) -> None:
        self._cities: list[dict] = DEFAULT_CITIES

    async def async_step_user(self, user_input=None):
        """Step 1: search / filter. Empty = show top 20."""
        errors: dict[str, str] = {}

        if user_input is not None:
            phrase = user_input.get("phrase", "").strip()

            if phrase:
                if len(phrase) < MIN_CHARS:
                    errors["phrase"] = "too_short"
                else:
                    results = await _fetch_cities(self.hass, phrase)
                    if results:
                        self._cities = results
                    else:
                        errors["phrase"] = "no_results"
            else:
                self._cities = DEFAULT_CITIES

            if not errors:
                return await self.async_step_select()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional("phrase", default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
            }),
            errors=errors,
        )

    async def async_step_select(self, user_input=None):
        """Step 2: pick city from list → create entity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            city = user_input.get("city")

            if city == "_back":
                self._cities = DEFAULT_CITIES
                return await self.async_step_user()

            if city:
                parts = city.split("/", 1)
                if len(parts) == 2:
                    city_id, slug = parts
                    title = next(
                        (c["title"] for c in self._cities if c["city_id"] == city_id),
                        slug,
                    )
                    await self.async_set_unique_id(f"meteo_ua_{city_id}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Meteo UA \u2014 {title}",
                        data={
                            CONF_CITY_ID: city_id,
                            CONF_CITY_SLUG: slug,
                            CONF_CITY_NAME: title,
                        },
                    )
            errors["city"] = "invalid_selection"

        city_options = _build_options(self._cities)
        default_city = city_options[0]["value"] if city_options else None

        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema({
                vol.Required("city", default=default_city): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value="_back", label="\U0001f50d Новий пошук \u2014 натисніть Надіслати \u27a1"),
                            *city_options,
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            errors=errors,
        )
