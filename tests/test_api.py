"""Tests for the meteo.ua JSON API layer (parsers/api.py).

Fixtures are real responses captured on 2026-10-09 (Kyiv id 34, Brovary id 589).
The module is loaded by path, so neither Home Assistant nor aiohttp is needed:

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "custom_components/meteo_ua/parsers/api.py"
FIX = Path(__file__).resolve().parent / "fixtures"
KYIV = ZoneInfo("Europe/Kyiv")

_spec = importlib.util.spec_from_file_location("meteo_ua_api", API)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class CurrentTest(unittest.TestCase):
    def test_kyiv_matches_site(self):
        cur = api.build_current(load("wx_34_kiev.json"), "uk")
        # The site showed: +18°, Похмуро, 758 мм рт.ст., 0.9 м/с ПдСх, 78 %, 10.0 км, dew point 14°C
        self.assertAlmostEqual(cur["temperature"], 17.97)
        self.assertEqual(cur["condition"], "cloudy")
        self.assertEqual(cur["condition_text"], "Похмуро")
        self.assertAlmostEqual(cur["pressure"], 757.6, places=1)   # hPa → mmHg
        self.assertEqual(cur["wind_bearing"], 124)
        self.assertEqual(cur["wind_direction"], "SE")
        self.assertEqual(cur["humidity"], 78)
        self.assertEqual(cur["visibility"], 10.0)                  # m → km
        self.assertAlmostEqual(cur["dew_point"], 13.74)

    def test_english_text(self):
        cur = api.build_current(load("wx_34_kiev.json"), "en")
        self.assertEqual(cur["condition_text"], "Overcast")

    def test_unexpected_payload_raises(self):
        for bad in ({}, [], {"current": {}, "hourly": {"time": []}, "daily": {"time": []}}):
            with self.assertRaises(api.MeteoUaApiError):
                api.build_current(bad)


class HourlyTest(unittest.TestCase):
    def test_window_and_offset(self):
        now = datetime(2026, 10, 9, 14, 30, tzinfo=KYIV)
        hourly = api.build_hourly(load("wx_34_kiev.json"), "uk", now=now)
        self.assertEqual(hourly[0]["datetime"], "2026-10-09T13:00:00+03:00")  # one hour back
        self.assertEqual(len(hourly), api.HOURLY_LIMIT_HOURS)
        for h in hourly:
            self.assertIsNotNone(h["condition"], h)
            self.assertIsNotNone(h["temperature"], h)

    def test_dst_switch_on_oct_25(self):
        """Ukraine leaves summer time on 2026-10-25 at 04:00 (back to 03:00).

        The fixtures end on Oct 24, so the boundary is tested on a synthetic series,
        including a repeated local 03:00 that must become the later (+02:00) instant.
        """
        times = ["2026-10-25T02:00", "2026-10-25T03:00", "2026-10-25T03:00",
                 "2026-10-25T04:00", "2026-10-25T05:00"]
        wx = {
            "utc_offset_seconds": int(datetime.now(KYIV).utcoffset().total_seconds()),
            "current": {"weather_code": 0},
            "hourly": {"time": times, "weather_code": [0] * 5, "temperature_2m": [5.0] * 5},
            "daily": {"time": ["2026-10-25"], "sunrise": ["2026-10-25T07:30"],
                      "sunset": ["2026-10-25T17:10"]},
        }
        now = datetime(2026, 10, 25, 3, 0, tzinfo=KYIV)
        stamps = [h["datetime"] for h in api.build_hourly(wx, "uk", now=now)]
        self.assertEqual(stamps, [
            "2026-10-25T02:00:00+03:00",
            "2026-10-25T03:00:00+03:00",
            "2026-10-25T03:00:00+02:00",
            "2026-10-25T04:00:00+02:00",
            "2026-10-25T05:00:00+02:00",
        ])
        instants = [datetime.fromisoformat(s) for s in stamps]
        self.assertEqual(instants, sorted(instants))                      # strictly forward in time
        self.assertEqual(len(set(instants)), len(instants))

    def test_clear_night(self):
        now = datetime(2026, 10, 15, 12, 0, tzinfo=KYIV)
        conds = {(h["datetime"][11:13], h["condition"]) for h in
                 api.build_hourly(load("wx_34_kiev.json"), "uk", now=now)}
        self.assertIn(("02", "clear-night"), conds)
        self.assertNotIn(("02", "sunny"), conds)


class DailyTest(unittest.TestCase):
    def test_sixteen_days_from_today(self):
        wx = load("wx_34_kiev.json")
        daily = api.build_daily(wx, "uk")
        self.assertEqual(len(daily), 16)
        self.assertEqual(daily[0]["date"], wx["daily"]["time"][0])        # starts today, not tomorrow
        self.assertEqual(daily[0]["datetime"], "2026-10-09T00:00:00+03:00")
        for d in daily:
            self.assertIsNotNone(d["temp_max"])
            self.assertIsNotNone(d["temp_min"])
            self.assertLessEqual(d["temp_min"], d["temp_max"])
            self.assertIsNotNone(d["condition"])
            self.assertIsNotNone(d["wind_speed"])                        # from the windiest hour

    def test_second_city(self):
        daily = api.build_daily(load("wx_589_brovary.json"), "uk")
        self.assertEqual(len(daily), 16)
        self.assertTrue({d["condition"] for d in daily} - {"cloudy"})   # not everything collapses to cloudy


class MappingTest(unittest.TestCase):
    def test_every_code_is_mapped(self):
        for code in api.WMO_TEXT_UK:
            self.assertIn(code, api.WMO_TO_HA)
            self.assertIn(code, api.WMO_TEXT_EN)

    def test_unknown_code_is_none_not_cloudy(self):
        self.assertIsNone(api.ha_condition(12345))

    def test_tz_fallback_for_other_offsets(self):
        tz = api.payload_tz({"utc_offset_seconds": 3600})
        self.assertEqual(datetime(2026, 1, 1, tzinfo=tz).utcoffset(), timedelta(hours=1))


class SuggestTest(unittest.TestCase):
    def test_ukrainian_names(self):
        found = api.parse_suggest(load("suggest_brova_ua.json"))
        self.assertEqual(found[0], {"city_id": "589", "slug": "brovary", "title": "Бровари, Київська обл."})

    def test_garbage_is_ignored(self):
        self.assertEqual(api.parse_suggest("<html>"), [])
        self.assertEqual(api.parse_suggest([{"x": 1}, None]), [])


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    async def json(self, content_type=None):
        return self._body


class _Session:
    def __init__(self, status, body):
        self.resp = _Resp(status, body)

    def get(self, url, **kw):
        return self.resp


class FetchTest(unittest.TestCase):
    """meteo.ua answers 404 + "{}" for old (pre-redesign) and data-less ids."""

    def setUp(self):
        import sys, types
        if "aiohttp" not in sys.modules:
            fake = types.ModuleType("aiohttp")
            fake.ClientTimeout = lambda **kw: None
            sys.modules["aiohttp"] = fake
            self.addCleanup(sys.modules.pop, "aiohttp")

    def fetch(self, status, body):
        import asyncio
        return asyncio.run(api.async_fetch_wx(_Session(status, body), "33345"))

    def test_404_is_api_error_so_the_id_gets_migrated(self):
        with self.assertRaises(api.MeteoUaApiError):
            self.fetch(404, {})

    def test_server_error_is_not_api_error(self):
        with self.assertRaises(RuntimeError):
            self.fetch(503, {})

    def test_ok(self):
        self.assertIn("current", self.fetch(200, load("wx_34_kiev.json")))


class CityRefTest(unittest.TestCase):
    def test_urls_and_ids(self):
        for text, want in (
            ("https://meteo.ua/ua/8742/novoselki", ("8742", "novoselki")),
            ("meteo.ua/8742/novoselki/", ("8742", "novoselki")),
            ("https://www.meteo.ua/ua/8742?utm=x", ("8742", "")),
            (" 8742 ", ("8742", "")),
        ):
            self.assertEqual(api.parse_city_ref(text), want, text)

    def test_names_are_not_refs(self):
        for text in ("Новосілки", "Київ 2", "https://example.com/ua/8742", ""):
            self.assertIsNone(api.parse_city_ref(text), text)


if __name__ == "__main__":
    unittest.main()
