"""Meteo UA — weather + 30-day forecast from meteo.ua."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import MeteoUaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS_LIST = [Platform.WEATHER]

CARD_FILENAME = "meteo-ua-weather-forecast-card.js"


def _get_version() -> str:
    """Read version from manifest.json."""
    manifest = Path(__file__).parent / "manifest.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "0")
    except Exception:
        return "0"


def _card_url(version: str | None = None) -> str:
    """Build card URL with cache-busting query param."""
    v = version or _get_version()
    return f"/local/{CARD_FILENAME}?v={v}"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version < 2:
        _LOGGER.info("Migrating Meteo UA config entry %s from v%s to v2", entry.entry_id, entry.version)
        new_data = dict(entry.data)
        new_data.pop("station_id", None)
        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = MeteoUaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_LIST)

    await _register_card(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS_LIST)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up card resources when the last config entry is removed."""
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if remaining:
        return

    # Last entry removed — unregister Lovelace resource and delete JS
    await _unregister_card(hass)


async def _register_card(hass: HomeAssistant) -> None:
    """Copy card JS to www/ and register as Lovelace resource."""
    if hass.data.get(DOMAIN, {}).get("_card_registered"):
        return

    # Copy JS to www/
    src = Path(__file__).parent / "frontend" / CARD_FILENAME
    www_dir = Path(hass.config.path("www"))
    www_dir.mkdir(exist_ok=True)
    dst = www_dir / CARD_FILENAME

    try:
        # Always copy on version bump (file might differ even if same size)
        needs_copy = not dst.exists() or src.read_bytes() != dst.read_bytes()
        if needs_copy:
            await hass.async_add_executor_job(shutil.copy2, str(src), str(dst))
            _LOGGER.info("Copied %s to %s", CARD_FILENAME, dst)
    except Exception as exc:
        _LOGGER.error("Failed to copy card: %s", exc)
        return

    # Register / update Lovelace resource with cache-busting version
    url = _card_url()
    try:
        from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        lovelace_data = hass.data.get(LOVELACE_DOMAIN)
        if lovelace_data is None:
            _LOGGER.warning("Lovelace not loaded — add card resource manually: %s", url)
            return

        resources: ResourceStorageCollection | None = getattr(lovelace_data, "resources", None)
        if resources is None:
            _LOGGER.warning("Lovelace resources not available — add manually: %s", url)
            return

        existing = [
            r for r in resources.async_items()
            if CARD_FILENAME in r.get("url", "")
        ]
        if not existing:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Registered Lovelace resource: %s", url)
        elif existing[0].get("url") != url:
            # Version changed — update URL for cache busting
            await resources.async_update_item(existing[0]["id"], {"url": url})
            _LOGGER.info("Updated Lovelace resource: %s", url)
        else:
            _LOGGER.debug("Lovelace resource up to date")
    except ImportError:
        _LOGGER.warning("Cannot import lovelace resources — add card manually: %s", url)
    except Exception as exc:
        _LOGGER.warning("Could not auto-register card: %s — add manually: %s", exc, url)

    hass.data.setdefault(DOMAIN, {})["_card_registered"] = True


async def _unregister_card(hass: HomeAssistant) -> None:
    """Remove Lovelace resource and delete JS file from www/."""
    # Remove Lovelace resource
    try:
        from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )

        lovelace_data = hass.data.get(LOVELACE_DOMAIN)
        if lovelace_data is not None:
            resources: ResourceStorageCollection | None = getattr(
                lovelace_data, "resources", None
            )
            if resources is not None:
                existing = [
                    r for r in resources.async_items()
                    if CARD_FILENAME in r.get("url", "")
                ]
                for resource in existing:
                    await resources.async_delete_item(resource["id"])
                    _LOGGER.info("Removed Lovelace resource: %s", resource.get("url"))
    except Exception as exc:
        _LOGGER.warning("Failed to remove Lovelace resource: %s", exc)

    # Delete JS file from www/
    dst = Path(hass.config.path("www")) / CARD_FILENAME
    try:
        if dst.exists():
            await hass.async_add_executor_job(dst.unlink)
            _LOGGER.info("Deleted %s", dst)
    except Exception as exc:
        _LOGGER.warning("Failed to delete card file: %s", exc)

    hass.data.get(DOMAIN, {}).pop("_card_registered", None)
