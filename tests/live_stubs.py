"""Minimal Home Assistant stubs so the integration package can be imported outside HA."""

import sys
import types
from typing import Generic, TypeVar

T = TypeVar("T")


def stub_homeassistant() -> None:
    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha

    # Only needed for the type annotations of the client; tests inject their
    # own session object and never open a connection.
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

    for name in (
        "config_entries",
        "core",
        "exceptions",
        "helpers",
        "helpers.typing",
        "helpers.update_coordinator",
    ):
        sys.modules[f"homeassistant.{name}"] = types.ModuleType(f"homeassistant.{name}")

    entries = sys.modules["homeassistant.config_entries"]
    entries.ConfigEntry = object
    entries.ConfigFlow = object
    entries.ConfigFlowResult = object
    entries.OptionsFlow = object

    exceptions = sys.modules["homeassistant.exceptions"]
    exceptions.ConfigEntryAuthFailed = RuntimeError
    exceptions.HomeAssistantError = RuntimeError

    sys.modules["homeassistant.core"].HomeAssistant = object
    sys.modules["homeassistant.helpers.typing"].ConfigType = object

    update = sys.modules["homeassistant.helpers.update_coordinator"]

    class DataUpdateCoordinator(Generic[T]):
        def __init__(self, hass, logger, name=None, update_interval=None):
            self._logger = logger
            self.update_interval = update_interval
            self.data = None
            self.last_update_success = True

        def async_add_listener(self, callback):
            return lambda: None

    update.DataUpdateCoordinator = DataUpdateCoordinator
    update.UpdateFailed = RuntimeError
