"""WAVIoT personal cabinet integration for Home Assistant."""

from __future__ import annotations

from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .api import WaviotApi
from .const import (
    CONF_API_KEY,
    CONF_ELEMENT_ID,
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DOMAIN,
    USER_AGENT,
)
from .coordinator import WaviotCoordinator

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Entry points are created from the UI only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
    api = WaviotApi(
        session,
        entry.data.get(CONF_LOGIN),
        entry.data.get(CONF_PASSWORD),
        entry.data.get(CONF_API_KEY),
    )
    minutes = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_MINUTES),
    )
    coordinator = WaviotCoordinator(
        hass,
        api,
        entry.data.get(CONF_ELEMENT_ID),
        minutes,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    if hasattr(entry, "runtime_data"):
        entry.runtime_data = coordinator

    entry.async_on_unload(session.close)
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    entry.async_on_unload(lambda: hass.data.get(DOMAIN, {}).pop(entry.entry_id, None))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    minutes = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_MINUTES),
    )
    get_coordinator(hass, entry).update_interval = timedelta(minutes=minutes)


def get_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> WaviotCoordinator:
    """The coordinator of this entry, from whichever place this HA version keeps it."""
    if hasattr(entry, "runtime_data"):
        return entry.runtime_data
    return hass.data[DOMAIN][entry.entry_id]
