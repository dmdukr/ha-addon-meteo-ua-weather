"""meteo.ua JSON API client (site redesign of October 2026).

The redesigned meteo.ua renders its pages from its own JSON endpoints, so the
integration reads those instead of scraping HTML:

  GET /api/wx/{city_id}           current + hourly (16 days, 1 h) + daily (16 days)
  GET /api/suggest?q=..&loc=ua    settlement search: [{"i": id, "s": slug, "n": name, "r": region}]

The weather payload uses Open-Meteo field names and WMO weather codes. Times are
local wall-clock strings; ``utc_offset_seconds`` gives the offset at fetch time.

Pure functions (``build_*``) take the decoded payload and are tested against saved
responses; only the ``async_*`` functions touch the network.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://meteo.ua"
WX_URL = BASE_URL + "/api/wx/{city_id}"
SUGGEST_URL = BASE_URL + "/api/suggest?q={phrase}&loc={loc}"
USER_AGENT = "HomeAssistant/MeteoUA"

HPA_TO_MMHG = 0.750062
HOURLY_LIMIT_HOURS = 7 * 24

_KYIV = ZoneInfo("Europe/Kyiv")

# Wording taken from meteo.ua's own front-end table (js/meteo.*.js, "wmo"),
# so condition texts match the site exactly.
WMO_TEXT_UK: dict[int, str] = {
    0: "Ясно", 1: "Переважно ясно", 2: "Мінлива хмарність", 3: "Похмуро",
    45: "Туман", 48: "Паморозь",
    51: "Слабка мряка", 53: "Мряка", 55: "Сильна мряка", 56: "Крижана мряка", 57: "Крижана мряка",
    61: "Невеликий дощ", 63: "Дощ", 65: "Сильний дощ", 66: "Крижаний дощ", 67: "Крижаний дощ",
    71: "Невеликий сніг", 73: "Сніг", 75: "Сильний сніг", 77: "Снігова крупа",
    80: "Короткочасний дощ", 81: "Зливи", 82: "Сильні зливи", 85: "Снігові зливи", 86: "Снігові зливи",
    95: "Гроза", 96: "Гроза з градом", 99: "Сильна гроза з градом",
}

WMO_TEXT_EN: dict[int, str] = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Rain showers", 81: "Heavy showers", 82: "Violent showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}

WMO_TO_HA: dict[int, str] = {
    0: "sunny", 1: "partlycloudy", 2: "partlycloudy", 3: "cloudy",
    45: "fog", 48: "fog",
    51: "rainy", 53: "rainy", 55: "rainy", 56: "snowy-rainy", 57: "snowy-rainy",
    61: "rainy", 63: "rainy", 65: "pouring", 66: "snowy-rainy", 67: "snowy-rainy",
    71: "snowy", 73: "snowy", 75: "snowy", 77: "snowy",
    80: "rainy", 81: "rainy", 82: "pouring", 85: "snowy", 86: "snowy",
    95: "lightning-rainy", 96: "hail", 99: "hail",
}

_CARDINALS_EN = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


class MeteoUaApiError(Exception):
    """meteo.ua answered, but not with the payload this integration understands."""


def resolve_locale(lang: str | None) -> str:
    """uk/ru → 'uk' (site wording), everything else → 'en'."""
    return "uk" if (lang or "uk") in ("uk", "ru") else "en"


def condition_text(code: int | None, locale: str) -> str:
    if code is None:
        return ""
    table = WMO_TEXT_UK if locale == "uk" else WMO_TEXT_EN
    return table.get(int(code), "")


def ha_condition(code: int | None, is_day: bool = True) -> str | None:
    if code is None:
        return None
    cond = WMO_TO_HA.get(int(code))
    if cond is None:
        _LOGGER.debug("Unknown WMO weather code %s", code)
        return None
    if cond == "sunny" and not is_day:
        return "clear-night"
    return cond


def deg_to_cardinal(deg: float | None) -> str:
    if deg is None:
        return ""
    return _CARDINALS_EN[round(float(deg) / 22.5) % 16]


def to_mmhg(hpa: float | None) -> float | None:
    return None if hpa is None else round(float(hpa) * HPA_TO_MMHG, 1)


def payload_tz(wx: dict[str, Any]) -> tzinfo:
    """Timezone for the payload's local times.

    The API reports one ``utc_offset_seconds`` for the whole response, but the 16-day
    range can cross a DST switch. For Ukrainian settlements (offset equals Kyiv's at
    fetch time) use Europe/Kyiv so stamps after the switch stay correct; otherwise
    fall back to the fixed offset the API reported.
    """
    offset = wx.get("utc_offset_seconds")
    if offset is None:
        return _KYIV
    now_kyiv = datetime.now(_KYIV).utcoffset()
    if now_kyiv is not None and int(now_kyiv.total_seconds()) == int(offset):
        return _KYIV
    return timezone(timedelta(seconds=int(offset)))


def _local(ts: str, tz: tzinfo) -> datetime:
    return datetime.fromisoformat(ts).replace(tzinfo=tz)


def _require(wx: Any) -> None:
    if not isinstance(wx, dict):
        raise MeteoUaApiError("payload is not a JSON object")
    for key in ("current", "hourly", "daily"):
        if not isinstance(wx.get(key), dict):
            raise MeteoUaApiError(f"payload has no '{key}' block")
    if not wx["hourly"].get("time") or not wx["daily"].get("time"):
        raise MeteoUaApiError("payload has empty hourly/daily series")


def _col(block: dict[str, Any], key: str, i: int) -> Any:
    values = block.get(key) or []
    return values[i] if i < len(values) else None


def build_current(wx: dict[str, Any], locale: str = "uk") -> dict[str, Any]:
    """Current conditions in the dict shape weather.py reads."""
    _require(wx)
    cur = wx["current"]
    code = cur.get("weather_code")
    bearing = cur.get("wind_direction_10m")
    visibility_m = cur.get("visibility")
    return {
        "temperature": cur.get("temperature_2m"),
        "apparent_temperature": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "pressure": to_mmhg(cur.get("surface_pressure")),
        "wind_speed": cur.get("wind_speed_10m"),
        "wind_bearing": bearing,
        "wind_direction": deg_to_cardinal(bearing),
        "dew_point": cur.get("dew_point_2m"),
        "visibility": None if visibility_m is None else round(visibility_m / 1000, 1),
        "condition": ha_condition(code, bool(cur.get("is_day", 1))),
        "condition_text": condition_text(code, locale),
        "observed_at": cur.get("time"),
    }


def _daylight(wx: dict[str, Any], tz: tzinfo) -> dict[date, tuple[datetime, datetime]]:
    daily = wx["daily"]
    out: dict[date, tuple[datetime, datetime]] = {}
    for i, day in enumerate(daily.get("time") or []):
        rise, sett = _col(daily, "sunrise", i), _col(daily, "sunset", i)
        if rise and sett:
            out[date.fromisoformat(day)] = (_local(rise, tz), _local(sett, tz))
    return out


def build_hourly(wx: dict[str, Any], locale: str = "uk",
                 now: datetime | None = None) -> list[dict[str, Any]]:
    """Hourly forecast from one hour ago, at most ``HOURLY_LIMIT_HOURS`` points."""
    _require(wx)
    tz = payload_tz(wx)
    hourly = wx["hourly"]
    daylight = _daylight(wx, tz)
    now = (now or datetime.now(tz)).astimezone(tz)
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    out: list[dict[str, Any]] = []
    prev_naive: datetime | None = None
    for i, ts in enumerate(hourly.get("time") or []):
        naive = datetime.fromisoformat(ts)
        # On the autumn DST switch local 03:00 occurs twice: the repeat is the later instant.
        dt = naive.replace(tzinfo=tz, fold=1 if naive == prev_naive else 0)
        prev_naive = naive
        if dt < start:
            continue
        code = _col(hourly, "weather_code", i)
        window = daylight.get(dt.date())
        is_day = True if window is None else window[0] <= dt < window[1]
        bearing = _col(hourly, "wind_direction_10m", i)
        out.append({
            "datetime": dt.isoformat(),
            "temperature": _col(hourly, "temperature_2m", i),
            "apparent_temperature": _col(hourly, "apparent_temperature", i),
            "humidity": _col(hourly, "relative_humidity_2m", i),
            "pressure": to_mmhg(_col(hourly, "surface_pressure", i)),
            "wind_speed": _col(hourly, "wind_speed_10m", i),
            "wind_bearing": bearing,
            "dew_point": _col(hourly, "dew_point_2m", i),
            "condition": ha_condition(code, is_day),
            "condition_text": condition_text(code, locale),
            "precipitation": _col(hourly, "precipitation", i),
        })
        if len(out) >= HOURLY_LIMIT_HOURS:
            break
    return out


def build_daily(wx: dict[str, Any], locale: str = "uk") -> list[dict[str, Any]]:
    """Daily forecast for every day the API covers (16 today).

    Daily wind is not in the payload; it is taken from the windiest hour of the day.
    """
    _require(wx)
    tz = payload_tz(wx)
    daily, hourly = wx["daily"], wx["hourly"]
    windiest: dict[date, tuple[float, Any]] = {}
    for i, ts in enumerate(hourly.get("time") or []):
        speed = _col(hourly, "wind_speed_10m", i)
        if speed is None:
            continue
        d = _local(ts, tz).date()
        if d not in windiest or speed > windiest[d][0]:
            windiest[d] = (speed, _col(hourly, "wind_direction_10m", i))
    out: list[dict[str, Any]] = []
    for i, day in enumerate(daily.get("time") or []):
        d = date.fromisoformat(day)
        code = _col(daily, "weather_code", i)
        speed, bearing = windiest.get(d, (None, None))
        out.append({
            "date": d.isoformat(),
            "datetime": datetime(d.year, d.month, d.day, tzinfo=tz).isoformat(),
            "temp_max": _col(daily, "temperature_2m_max", i),
            "temp_min": _col(daily, "temperature_2m_min", i),
            "precipitation": _col(daily, "precipitation_sum", i),
            "wind_speed": speed,
            "wind_bearing": bearing,
            "condition": ha_condition(code, True),
            "condition_text": condition_text(code, locale),
            "weather_code": code,
            "sunrise": _col(daily, "sunrise", i),
            "sunset": _col(daily, "sunset", i),
        })
    return out


def parse_suggest(items: Any, limit: int = 20) -> list[dict[str, str]]:
    """Normalize /api/suggest results to {city_id, slug, title}."""
    out: list[dict[str, str]] = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict) or it.get("i") is None or not it.get("s"):
            continue
        name, region = it.get("n") or it["s"], it.get("r") or ""
        out.append({
            "city_id": str(it["i"]),
            "slug": str(it["s"]),
            "title": f"{name}, {region}" if region else name,
        })
        if len(out) >= limit:
            break
    return out


async def async_fetch_wx(session, city_id: str) -> dict[str, Any]:
    """GET /api/wx/{city_id}. Raises on network errors and on unexpected payloads."""
    import aiohttp

    async with session.get(
        WX_URL.format(city_id=city_id),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        resp.raise_for_status()
        wx = await resp.json(content_type=None)
    _require(wx)
    return wx


async def async_suggest(session, phrase: str, loc: str = "ua") -> list[dict[str, str]]:
    """Settlement search. ``loc=ua`` returns Ukrainian names, ``loc=uk`` Russian ones."""
    import aiohttp

    async with session.get(
        SUGGEST_URL.format(phrase=quote(phrase), loc=loc),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        resp.raise_for_status()
        items = await resp.json(content_type=None)
    return parse_suggest(items)
